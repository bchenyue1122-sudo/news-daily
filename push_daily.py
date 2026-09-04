# -*- coding: utf-8 -*-
"""每日热点日报主入口。

用法：
  python push_daily.py             # 完整流程：查重 → 抓取 → 发布 → 推送
  python push_daily.py --dry-run   # 只抓取渲染，写本地 docs/，不 git、不推送
  python push_daily.py --force     # 跳过查重强制执行
  python push_daily.py --no-git    # 跳过 git 发布（仅测试推送链路时用）
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

# 版块顺序：国内在前，AI 在后
SECTION_ORDER = ["yaowen", "weibo", "zhihu", "baidu", "douyin", "bilibili",
                 "wechat_hot", "qbitai", "aibase", "kr36", "hf_papers",
                 "github_trending", "jiqizhixin"]


def load_env(path: Path):
    """极简 .env 解析：KEY=VALUE，不覆盖已存在的环境变量。"""
    if not path.exists():
        return {}
    loaded = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        loaded[k] = v
        os.environ.setdefault(k, v)
    return loaded


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def fetch_all(enabled_cfg):
    """并发抓取所有启用的源，返回按 SECTION_ORDER 排序的 sections。"""
    jobs = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futs = {}
        for name in SECTION_ORDER:
            cfg = enabled_cfg.get(name)
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

    order = {n: i for i, n in enumerate(SECTION_ORDER)}
    jobs.sort(key=lambda s: order[s["name"]])
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
    push = run("push", "origin", branch)
    if push.returncode != 0:
        return False, f"push 失败: {push.stderr.strip()}"
    return True, "pushed"


def main():
    ap = argparse.ArgumentParser(description="每日热点日报：抓取 → GitHub Pages → 微信测试号")
    ap.add_argument("--dry-run", action="store_true", help="只抓取渲染，不发布不推送")
    ap.add_argument("--force", action="store_true", help="跳过查重强制执行")
    ap.add_argument("--no-git", action="store_true", help="跳过 git 发布（测试推送链路）")
    args = ap.parse_args()

    cfg = yaml.safe_load((BASE_DIR / "config.yaml").read_text(encoding="utf-8"))
    # .env 文件值会 setdefault 进 os.environ（不覆盖已有变量）；
    # GitHub Actions 的 Secrets 以进程环境变量注入，因此统一从 os.environ 读
    load_env(BASE_DIR / ".env")
    env = os.environ

    fetchers.configure(cfg.get("dailyhot_instances"), cfg.get("sixty_instances"))

    now = datetime.now(ZoneInfo(cfg.get("timezone", "Asia/Shanghai")))
    date_str = f"{now:%Y-%m-%d}"
    branch = cfg.get("publish", {}).get("branch", "main")
    docs_dir = Path(cfg.get("publish", {}).get("docs_dir", "docs"))
    repo = env.get("GH_REPO") or cfg.get("publish", {}).get("gh_repo", "")
    pages_url = (env.get("PAGES_URL")
                 or cfg.get("publish", {}).get("pages_url", "")).rstrip("/")

    log(f"=== 每日热点日报 {date_str} ===")

    # 1. 查重
    if not args.dry_run and not args.force:
        token = env.get("GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if dedupe.already_pushed(repo, date_str, branch=branch, docs_dir=docs_dir.as_posix(),
                                 token=token):
            log(f"今日日报已存在（{repo} docs/{date_str}.html），跳过。")
            return 0
        log("今日尚未推送，继续。")

    # 2. 抓取
    enabled = {k: v for k, v in (cfg.get("sources") or {}).items() if v.get("enabled")}
    sections = fetch_all(enabled)
    if all(not s["items"] for s in sections):
        log("❌ 所有数据源均失败，中止（不做空推送，等待备用触发端重试）。")
        return 1

    # 3. 渲染
    digest_text = render.build_digest_text(sections, cfg.get("digest", {}))
    daily_html = render.build_daily_html(sections, now)
    log(f"摘要 {len(digest_text)} 字符。")

    # 4. 落盘
    docs_path = BASE_DIR / docs_dir
    docs_path.mkdir(exist_ok=True)
    (docs_path / f"{date_str}.html").write_text(daily_html, encoding="utf-8")
    dates = sorted((p.stem for p in docs_path.glob("????-??-??.html")), reverse=True)
    (docs_path / "index.html").write_text(render.build_index_html(dates, now),
                                          encoding="utf-8")
    log(f"已写入 {docs_dir}/{date_str}.html 与 index.html")

    if args.dry_run:
        print("\n----- 微信卡片摘要预览 -----")
        print(digest_text)
        print("----------------------------")
        log("dry-run 完成：未发布、未推送。")
        return 0

    # 5. 发布（git push → Pages 自动部署）
    if not args.no_git:
        if not repo:
            log("⚠️ 未配置 GH_REPO（本地看 .env，云端看仓库 Secrets），跳过 git 发布"
                "（卡片将没有可跳转的日报页）。")
        else:
            ok, msg = publish_git(date_str, branch)
            log(("✅ 已发布到 GitHub" if ok else f"⚠️ 发布失败：{msg}"))

    # 6. 推送微信测试号
    need = ["WX_APPID", "WX_SECRET", "WX_OPENID", "WX_TEMPLATE_ID"]
    missing = [k for k in need if not env.get(k)]
    if missing:
        where = ("GitHub Actions 运行：请到仓库 Settings → Secrets and variables → "
                 "Actions 添加 Repository secrets（本地 .env 不会上传，云端只认 Secrets）"
                 if os.environ.get("GITHUB_ACTIONS")
                 else "请把 .env.example 复制为 .env 并填写")
        log(f"❌ 缺少微信配置: {', '.join(missing)}（{where}）。")
        return 1
    card_url = f"{pages_url}/{date_str}.html" if pages_url else ""
    if not pages_url:
        log("⚠️ 未配置 PAGES_URL，卡片点击将不跳转。")
    try:
        push_wechat.push_daily(env["WX_APPID"], env["WX_SECRET"], env["WX_OPENID"],
                               env["WX_TEMPLATE_ID"], date_str=date_str,
                               digest_text=digest_text, url=card_url)
        log(f"🎉 已推送微信（{card_url or '无跳转链接'}）")
    except push_wechat.WeChatError as e:
        log(f"❌ {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
