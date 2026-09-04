# -*- coding: utf-8 -*-
"""每日热点日报主入口（双流水线：国内新闻 + AI 快报）。

用法：
  python push_daily.py             # 完整流程：查重 → 抓取 → 发布 → 推送两条
  python push_daily.py --dry-run   # 只抓取渲染，写本地 docs/，不 git、不推送
  python push_daily.py --force     # 跳过查重强制执行
  python push_daily.py --only ai   # 只跑 AI 流水线（或 news）
"""
import argparse
import concurrent.futures
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

# Windows 下输出被重定向到文件时默认 GBK 编码，日志里的 emoji 会导致
# UnicodeEncodeError 崩溃（2026-09-04 实际发生），统一改为 UTF-8
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR / "src"))

import dedupe  # noqa: E402
import fetchers  # noqa: E402
import push_wechat  # noqa: E402
import render  # noqa: E402

# 两条流水线的版块顺序（国内在前，AI 在后）
PIPELINES = {
    "news": {
        "title": "📰 国内新闻日报",
        "template_key": "WX_TEMPLATE_ID",
        "order": ["yaowen", "weibo", "zhihu", "baidu", "toutiao", "douyin",
                  "bilibili", "wechat_hot", "ithome", "sspai", "kr36"],
    },
    "ai": {
        "title": "🤖 每日AI快报",
        "template_key": "WX_TEMPLATE_ID_AI",
        "order": ["qbitai", "aibase", "jiqizhixin", "vendor_blogs", "hf_papers",
                  "hf_releases", "vendor_news", "hn", "reddit", "baai",
                  "juejin_ai", "github_trending"],
    },
}


def load_env(path: Path):
    """极简 .env 解析：KEY=VALUE，不覆盖已存在的环境变量（Actions Secrets 优先）。"""
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def fetch_all(order, sources_cfg):
    """并发抓取流水线内所有启用的源，按 order 排序返回 sections。"""
    jobs = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futs = {}
        for name in order:
            cfg = sources_cfg.get(name)
            if not cfg or not cfg.get("enabled"):
                continue
            futs[pool.submit(fetchers.fetch_source, name, int(cfg.get("top_n", 10)))] = (
                name, cfg)
        for fut in concurrent.futures.as_completed(futs):
            name, cfg = futs[fut]
            items, source, err = fut.result()
            jobs.append({
                "name": name,
                "tag": cfg.get("tag", name),
                "items": items,
                "source": source,
                "error": err,
            })
            if err:
                log(f"⚠️  {name}: {err}")
            else:
                log(f"✅ {name}: {len(items)} 条 (via {source})")

    order_idx = {n: i for i, n in enumerate(order)}
    jobs.sort(key=lambda s: order_idx.get(s["name"], 99))
    return jobs


def publish_git(date_str, branch):
    """git 提交并推送 docs/ 目录。返回 (ok, 输出信息)。"""
    def run(*args):
        return subprocess.run(["git", *args], cwd=BASE_DIR, capture_output=True,
                              text=True, encoding="utf-8", errors="replace")

    # Actions 的 checkout 环境没有 git 身份，未配置时用机器人身份补上
    if not run("config", "user.email").stdout.strip():
        run("config", "user.name", "news-daily-bot")
        run("config", "user.email", "news-daily-bot@users.noreply.github.com")

    run("add", "docs")
    commit = run("commit", "-m", f"daily {date_str}")
    if commit.returncode != 0 and "nothing to commit" not in commit.stdout:
        return False, f"commit 失败: {commit.stdout} {commit.stderr}"
    # 远端可能刚被另一条流水线/另一触发端推过，先 rebase 再推
    for attempt in range(3):
        pull = run("pull", "--rebase", "-q", "origin", branch)
        if pull.returncode != 0:
            return False, f"pull 失败: {pull.stderr.strip()[:200]}"
        push = run("push", "origin", branch)
        if push.returncode == 0:
            return True, "pushed"
    return False, f"push 失败: {push.stderr.strip()[:200]}"


def run_pipeline(key, cfg, now, *, dry_run=False, force=False, no_git=False,
                 docs_dirty=False):
    """跑一条流水线：查重 → 抓取 → 渲染 → 落盘 →（发布/推送）。"""
    spec = PIPELINES[key]
    date_str = f"{now:%Y-%m-%d}"
    branch = cfg.get("publish", {}).get("branch", "main")
    docs_dir = Path(cfg.get("publish", {}).get("docs_dir", "docs"))
    repo = os.environ.get("GH_REPO", "")
    pages_url = os.environ.get("PAGES_URL", "").rstrip("/")
    filename = f"{date_str}-{key}.html"

    log(f"===== {spec['title']} {date_str} =====")

    # 1. 查重（本地 docs 里已有且不是本次运行写的，视为已发过）
    if not dry_run and not force:
        if dedupe.already_pushed(repo, f"{date_str}-{key}",
                                 branch=branch, docs_dir=docs_dir.as_posix()):
            log(f"今日 {key} 日报已存在（docs/{filename}），跳过。")
            return True

    # 2. 抓取
    enabled = {k: v for k, v in (cfg.get("sources") or {}).items() if v.get("enabled")}
    order = [n for n in spec["order"] if n in enabled]
    sections = fetch_all(order, enabled)
    if all(not s["items"] for s in sections):
        log("❌ 本流水线所有数据源均失败，跳过发布与推送。")
        return False

    # 3. 渲染
    digest_text = render.build_digest_text(sections, cfg.get("digest", {}))
    daily_html = render.build_daily_html(spec["title"], sections, now)
    log(f"摘要 {len(digest_text)} 字符。")

    # 4. 落盘
    docs_path = BASE_DIR / docs_dir
    docs_path.mkdir(exist_ok=True)
    (docs_path / filename).write_text(daily_html, encoding="utf-8")
    docs_dirty = True

    if dry_run:
        print("\n----- 微信卡片摘要预览 -----")
        print(digest_text)
        print("----------------------------")
        return True

    # 5. 发布（git push → Pages 自动部署）
    if not no_git:
        if not repo:
            log("⚠️ 未配置 GH_REPO（本地看 .env，云端看仓库 Secrets），跳过 git 发布"
                "（卡片将没有可跳转的日报页）。")
        else:
            ok, msg = publish_git(date_str, branch)
            log(("✅ 已发布到 GitHub" if ok else f"⚠️ 发布失败：{msg}"))

    # 6. 推送微信
    need = ["WX_APPID", "WX_SECRET", "WX_OPENID", spec["template_key"]]
    missing = [k for k in need if not os.environ.get(k)]
    if missing:
        where = ("GitHub Actions 运行：请到仓库 Settings → Secrets and variables → "
                 "Actions 添加 Repository secrets（本地 .env 不会上传，云端只认 Secrets）"
                 if os.environ.get("GITHUB_ACTIONS")
                 else "请把 .env.example 复制为 .env 并填写")
        log(f"❌ 缺少微信配置: {', '.join(missing)}（{where}）。")
        return False
    card_url = f"{pages_url}/{filename}" if pages_url else ""
    if not pages_url:
        log("⚠️ 未配置 PAGES_URL，卡片点击将不跳转。")
    try:
        push_wechat.push_daily(os.environ["WX_APPID"], os.environ["WX_SECRET"],
                               os.environ["WX_OPENID"], os.environ[spec["template_key"]],
                               title=spec["title"], date_str=date_str,
                               digest_text=digest_text, url=card_url)
        log(f"🎉 已推送微信（{card_url or '无跳转链接'}）")
    except push_wechat.WeChatError as e:
        log(f"❌ {e}")
        return False
    return True


def rebuild_index(cfg, now):
    """根据 docs/ 里现有文件重建归档页：每天两条（news + ai），新的在前。"""
    docs_dir = Path(cfg.get("publish", {}).get("docs_dir", "docs"))
    dates = sorted((p.stem for p in docs_dir.glob("????-??-??-??.html")), reverse=True)
    entries = []
    for stem in dates:
        date, key = stem.rsplit("-", 1)
        label = "国内新闻" if key == "news" else "AI快报"
        entries.append((f"{date} · {label}", f"{stem}.html"))
    (docs_dir / "index.html").write_text(render.build_index_html(entries, now),
                                         encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="每日热点日报：抓取 → GitHub Pages → 微信测试号")
    ap.add_argument("--dry-run", action="store_true", help="只抓取渲染，不发布不推送")
    ap.add_argument("--force", action="store_true", help="跳过查重强制执行")
    ap.add_argument("--no-git", action="store_true", help="跳过 git 发布（测试推送链路）")
    ap.add_argument("--only", choices=["news", "ai"], help="只跑指定流水线")
    args = ap.parse_args()

    cfg = yaml.safe_load((BASE_DIR / "config.yaml").read_text(encoding="utf-8"))
    # .env 文件值 setdefault 进 os.environ（不覆盖）；
    # GitHub Actions 的 Secrets 以进程环境变量注入，因此统一从 os.environ 读
    load_env(BASE_DIR / ".env")

    fetchers.configure(cfg.get("dailyhot_instances"), cfg.get("sixty_instances"),
                       cfg.get("vendor_keywords"), cfg.get("hf_orgs"),
                       cfg.get("reddit_subs"))

    now = datetime.now(ZoneInfo(cfg.get("timezone", "Asia/Shanghai")))

    # 1. 跑流水线
    keys = [args.only] if args.only else ["news", "ai"]
    results = {}
    for key in keys:
        results[key] = run_pipeline(key, cfg, now, dry_run=args.dry_run,
                                    force=args.force, no_git=args.no_git)
        if args.dry_run:
            continue
        # 流水线之间留点间隔，避免微信侧速率限制
        if key != keys[-1]:
            import time
            time.sleep(5)

    # 2. 重建归档页（本地或发布前都刷新）
    rebuild_index(cfg, now)

    if args.dry_run:
        log("dry-run 完成：未发布、未推送。")
        return 0 if all(results.values()) else 1

    ok = all(results.values())
    log("全部流水线完成 ✅" if ok else "部分流水线失败 ⚠️")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
