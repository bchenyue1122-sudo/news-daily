# -*- coding: utf-8 -*-
"""渲染：微信卡片摘要文本 + GitHub Pages 日报 HTML + index 归档页。"""
import html as htmllib
from datetime import datetime

WEEKDAY_CN = "一二三四五六日"

# HTML 里各版块的中文名与 emoji
SECTION_META = {
    "yaowen": ("📰 国内要闻", "每天60秒读懂世界"),
    "weibo": ("🔥 微博热搜", "微博"),
    "zhihu": ("💬 知乎热榜", "知乎"),
    "baidu": ("🔍 百度热搜", "百度"),
    "douyin": ("🎵 抖音热点", "抖音"),
    "bilibili": ("📺 B站热榜", "哔哩哔哩"),
    "wechat_hot": ("💬 微信热文", "微信公众号"),
    "jiqizhixin": ("🤖 机器之心", "机器之心"),
    "qbitai": ("⚡ 量子位", "量子位"),
    "aibase": ("🛰️ AI 快讯", "AIbase"),
    "kr36": ("🚀 36氪热榜", "36氪"),
    "hf_papers": ("📄 HF 热门论文", "HuggingFace Daily Papers"),
    "github_trending": ("💻 GitHub Trending", "GitHub"),
}


def _clean(title, max_len=None):
    t = htmllib.unescape(str(title)).strip().replace("\n", " ")
    if max_len and len(t) > max_len:
        t = t[: max_len - 1] + "…"
    return t


# ---------------------------------------------------------------------------
# 微信卡片摘要（模板消息 digest 字段）
# ---------------------------------------------------------------------------

def build_digest_text(sections, digest_cfg):
    per = int(digest_cfg.get("items_per_section", 3))
    max_title = int(digest_cfg.get("max_title_chars", 20))
    max_total = int(digest_cfg.get("max_chars", 480))

    lines = []
    for sec in sections:
        meta = SECTION_META.get(sec["name"], (sec["name"], ""))
        tag = sec.get("tag") or meta[1] or sec["name"]
        items = sec.get("items") or []
        if not items:
            continue
        titles = [_clean(i["title"], max_title) for i in items[:per]]
        numbered = "；".join(f"{n+1}.{t}" for n, t in enumerate(titles))
        lines.append(f"【{tag}】{numbered}")

    text = "\n".join(lines)
    if len(text) > max_total:
        kept, out = 0, []
        for line in lines:
            if kept + len(line) + 1 > max_total:
                break
            out.append(line)
            kept += len(line) + 1
        text = "\n".join(out)
    return text


# ---------------------------------------------------------------------------
# 日报 HTML（手机端排版）
# ---------------------------------------------------------------------------

_CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;
     background:#f4f5f7;color:#222;line-height:1.6;padding:14px 10px 30px}
.wrap{max-width:640px;margin:0 auto}
.head{background:linear-gradient(135deg,#1f6feb,#5b8def);border-radius:14px;
      padding:22px 18px;color:#fff;margin-bottom:14px}
.head h1{font-size:22px;letter-spacing:1px}
.head .sub{margin-top:6px;font-size:13px;opacity:.9}
.sec{background:#fff;border-radius:12px;padding:14px 16px;margin-bottom:12px;
     box-shadow:0 1px 3px rgba(0,0,0,.05)}
.sec h2{font-size:16px;margin-bottom:8px;padding-bottom:8px;border-bottom:1px solid #f0f0f0}
.sec .src{font-size:11px;color:#aaa;font-weight:normal;margin-left:6px}
.sec ol{list-style:none}
.sec li{padding:7px 0;border-bottom:1px dashed #f5f5f5;font-size:14.5px;display:flex;gap:8px}
.sec li:last-child{border-bottom:none}
.rank{flex:none;width:20px;height:20px;border-radius:5px;background:#eef1f6;color:#8a94a6;
      font-size:12px;text-align:center;line-height:20px;margin-top:2px}
.rank.top{background:#ff5f57;color:#fff}
.rank.top2{background:#ff9f43;color:#fff}
.rank.top3{background:#fbc531;color:#fff}
.item{flex:1}
.item a{color:#222;text-decoration:none}
.item a:active{color:#1f6feb}
.no-url{color:#333}
.extra{font-size:12px;color:#9aa1ac;margin-top:1px;word-break:break-all}
.err{font-size:13px;color:#b0b6bf}
.foot{text-align:center;font-size:11px;color:#b0b6bf;margin-top:18px}
.nav{background:#fff;border-radius:12px;padding:14px 16px;margin-bottom:12px}
.nav h2{font-size:16px;margin-bottom:8px}
.nav a{display:inline-block;margin:3px 4px;font-size:12px;color:#1f6feb;
       text-decoration:none;background:#eef4ff;border-radius:6px;padding:3px 8px}
"""


def _sec_html(sec):
    meta = SECTION_META.get(sec["name"], ("📄 " + sec["name"], sec["name"]))
    title, src_label = meta
    src = sec.get("source") or ""
    body = []
    items = sec.get("items") or []
    if not items:
        body.append('<li><span class="err">⚠️ 暂不可用（源暂时无法访问）</span></li>')
    for n, it in enumerate(items):
        rank_cls = "top" if n == 0 else ("top2" if n == 1 else ("top3" if n == 2 else ""))
        title_txt = _clean(it["title"], 80)
        if it.get("url"):
            core = f'<a href="{htmllib.escape(it["url"], quote=True)}" target="_blank" rel="noopener">{htmllib.escape(title_txt)}</a>'
        else:
            core = f'<span class="no-url">{htmllib.escape(title_txt)}</span>'
        extra = f'<div class="extra">{htmllib.escape(it["extra"])}</div>' if it.get("extra") else ""
        body.append(
            f'<li><span class="rank {rank_cls}">{n+1}</span>'
            f'<span class="item">{core}{extra}</span></li>')
    src_note = f'<span class="src">via {htmllib.escape(src_label)}</span>' if src else ""
    return (f'<div class="sec"><h2>{title}{src_note}</h2>'
            f'<ol>{"".join(body)}</ol></div>')


def _toc(sections):
    links = []
    for sec in sections:
        meta = SECTION_META.get(sec["name"], (sec["name"], ""))
        name = meta[0].split(" ", 1)[-1]
        links.append(f'<a href="#sec-{sec["name"]}">{name}</a>')
    return f'<div class="nav"><h2>📖 本期导航</h2>{"".join(links)}</div>'


def build_daily_html(sections, now, source_err_map=None):
    date_str = now.strftime("%Y-%m-%d")
    weekday = f"星期{WEEKDAY_CN[now.weekday()]}"
    gen_time = now.strftime("%Y-%m-%d %H:%M")

    # 加上锚点 id
    secs = []
    for sec in sections:
        meta = SECTION_META.get(sec["name"], ("📄 " + sec["name"], sec["name"]))
        title, src_label = meta
        src = sec.get("source") or ""
        inner = _sec_html({**sec})
        inner = inner.replace(f"<h2>{title}", f'<h2 id="sec-{sec["name"]}">{title}', 1)
        secs.append(inner)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>每日热点早报 · {date_str}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
  <div class="head">
    <h1>📰 每日热点早报</h1>
    <div class="sub">{date_str} {weekday} ｜ 生成于 {gen_time}</div>
  </div>
  {_toc(sections)}
  {"".join(secs)}
  <div class="foot">由 wechat-news-daily 自动聚合生成 ｜ 数据来自公开榜单与官方 RSS，版权属原作者</div>
</div>
</body>
</html>"""


def build_index_html(dates_desc, now):
    """docs/index.html：最新一期置顶 + 历史归档列表。"""
    gen_time = now.strftime("%Y-%m-%d %H:%M")
    rows = []
    for i, d in enumerate(dates_desc):
        first = ' style="font-weight:600"' if i == 0 else ""
        rows.append(f'<li{first}><a href="{d}.html">{d}</a>'
                    f'{"（最新）" if i == 0 else ""}</li>')
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>每日热点早报 · 归档</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
  <div class="head">
    <h1>📰 每日热点早报</h1>
    <div class="sub">往期日报归档 ｜ 更新于 {gen_time}</div>
  </div>
  <div class="sec"><h2>🗂 日报列表</h2><ol>{"".join(rows)}</ol></div>
</div>
</body>
</html>"""
