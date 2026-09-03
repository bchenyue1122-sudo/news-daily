# -*- coding: utf-8 -*-
"""数据源适配器：每个源提供 1..N 个抓取通道，按顺序兜底；单源失败不影响整体。

统一输出：list[{"title": str, "url": str, "extra": str}]
url 可为空字符串（纯文本条目，如 60s 要闻）。
"""
import json
import re
import time
import html as htmllib
import urllib.parse
import xml.etree.ElementTree as ET

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
TIMEOUT = 15


class FetchError(Exception):
    pass


def _get(url, *, headers=None, timeout=TIMEOUT, retries=1, params=None):
    last = None
    for i in range(retries + 1):
        try:
            r = requests.get(url, headers=headers or HEADERS,
                             timeout=timeout, params=params)
            r.raise_for_status()
            return r
        except Exception as e:  # noqa: BLE001 网络层统一兜底
            last = e
            if i < retries:
                time.sleep(1.5 * (i + 1))
    raise FetchError(f"GET {url} 失败: {last}")


# 运行时配置（实例列表），由 configure() 注入
_SETTINGS = {
    "dailyhot_instances": ["https://api-hot.imsyy.top"],
    "sixty_instances": ["https://60s.b23.run", "https://60s.viki.moe"],
}


def configure(dailyhot_instances, sixty_instances):
    if dailyhot_instances:
        _SETTINGS["dailyhot_instances"] = dailyhot_instances
    if sixty_instances:
        _SETTINGS["sixty_instances"] = sixty_instances


def _cfg(key):
    return _SETTINGS[key]


# ---------------------------------------------------------------------------
# 兜底通道一：60s API（60s.b23.run 实测可用，viki.moe 备用）
# ---------------------------------------------------------------------------

def _sixty(route):
    errs = []
    for base in _cfg("sixty_instances"):
        try:
            r = _get(f"{base.rstrip('/')}/v2/{route}", timeout=12)
            j = r.json()
            data = j.get("data")
            if not data:
                raise FetchError(f"code={j.get('code')}")
            return data
        except Exception as e:  # noqa: BLE001
            errs.append(f"{base}: {e}")
    raise FetchError("所有 60s 实例失败: " + " | ".join(errs))


def ch_yaowen_60s():
    data = _sixty("60s")
    news = data.get("news") if isinstance(data, dict) else data
    items = [{"title": re.sub(r"^\d+、\s*", "", str(t)).strip(), "url": "", "extra": ""}
             for t in (news or []) if str(t).strip()]
    if not items:
        raise FetchError("news 为空")
    return items


def ch_weibo_60s():
    data = _sixty("weibo")
    rows = data if isinstance(data, list) else (data.get("data") or data.get("hot") or [])
    items = []
    for it in rows:
        if not isinstance(it, dict):
            continue
        title = (it.get("word") or it.get("title") or "").strip()
        if not title:
            continue
        q = urllib.parse.quote(f"#{title}#")
        items.append({"title": title,
                      "url": it.get("url") or f"https://s.weibo.com/weibo?q={q}",
                      "extra": str(it.get("hot") or it.get("num") or "")})
    if not items:
        raise FetchError("weibo 为空")
    return items


# ---------------------------------------------------------------------------
# 兜底通道二：DailyHotApi（imsyy 实例，本机可能不可达，云端常可达）
# ---------------------------------------------------------------------------

def _dailyhot(route):
    errs = []
    for base in _cfg("dailyhot_instances"):
        try:
            r = _get(f"{base.rstrip('/')}/{route}", timeout=12)
            j = r.json()
            if j.get("code") != 200 or not j.get("data"):
                raise FetchError(f"code={j.get('code')}")
            items = []
            for it in j["data"]:
                title = (it.get("title") or "").strip()
                if not title:
                    continue
                items.append({
                    "title": title,
                    "url": (it.get("url") or it.get("mobileUrl") or "").strip(),
                    "extra": str(it.get("hot") or "").strip(),
                })
            if items:
                return items
            raise FetchError("空数据")
        except Exception as e:  # noqa: BLE001
            errs.append(f"{base}: {e}")
    raise FetchError("所有实例失败: " + " | ".join(errs))


# ---------------------------------------------------------------------------
# 兜底通道三：codelife（今日热榜数据，实测可用，自带原文链接）
# ---------------------------------------------------------------------------

_CODELIFE_IDS = {
    "weibo": "KqndgxeLl9",      # 微博热搜榜
    "zhihu": "mproPpoq6O",      # 知乎热榜
    "douyin": "Y2KeDGQdNP",     # 抖音热点
    "bilibili": "74KvxwokxM",   # 哔哩哔哩热榜
    "wechat_hot": "WnBe01o371", # 微信 24h 热文榜
    "kr36": "Q1Vd5Ko85R",       # 36氪热榜
}


def _codelife(name):
    list_id = _CODELIFE_IDS[name]
    r = _get("https://api.codelife.cc/api/top/list",
             params={"lang": "cn", "id": list_id}, timeout=12)
    j = r.json()
    data = j.get("data") or []
    items = []
    for it in data:
        title = (it.get("title") or "").strip()
        if not title:
            continue
        items.append({
            "title": title,
            "url": (it.get("link") or "").strip(),
            "extra": (it.get("hotValue") or "").strip(),
        })
    if not items:
        raise FetchError(f"{name} 空数据")
    return items


def _codelife_factory(name):
    return lambda: _codelife(name)


# ---------------------------------------------------------------------------
# 直连通道（可用性随时会变，只作为优先尝试）
# ---------------------------------------------------------------------------

def ch_weibo_direct():
    r = _get("https://weibo.com/ajax/side/hotSearch", timeout=12)
    realtime = (r.json().get("data") or {}).get("realtime") or []
    items = []
    for it in realtime:
        if it.get("is_ad"):
            continue
        word = (it.get("word") or "").strip()
        if not word:
            continue
        q = urllib.parse.quote(f"#{word}#")
        items.append({"title": word,
                      "url": f"https://s.weibo.com/weibo?q={q}",
                      "extra": str(it.get("num") or "")})
    if not items:
        raise FetchError("realtime 为空")
    return items


def _zhihu_map_url(api_url):
    m = re.search(r"/questions/(\d+)", api_url or "")
    if m:
        return f"https://www.zhihu.com/question/{m.group(1)}"
    m = re.search(r"/articles/(\d+)", api_url or "")
    if m:
        return f"https://zhuanlan.zhihu.com/p/{m.group(1)}"
    return ""


def ch_zhihu_direct():
    r = _get("https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total",
             params={"limit": 50, "desktop": "true"}, timeout=12)
    rows = r.json().get("data") or []
    items = []
    for row in rows:
        tgt = row.get("target") or {}
        title = (tgt.get("title") or (tgt.get("title_area") or {}).get("text") or "").strip()
        if not title:
            continue
        items.append({"title": title,
                      "url": _zhihu_map_url(tgt.get("url") or tgt.get("fetch_url") or ""),
                      "extra": (row.get("detail_text") or "").strip()})
    if not items:
        raise FetchError("热榜为空")
    return items


def ch_baidu_direct():
    r = _get("https://top.baidu.com/board?tab=realtime", timeout=15)
    m = re.search(r"<!--s-data:(.*?)-->", r.text, re.S)
    if not m:
        raise FetchError("未找到 s-data JSON")
    j = json.loads(m.group(1))
    cards = (j.get("data") or {}).get("cards") or []
    items = []
    for card in cards:
        for it in (card.get("content") or []):
            word = (it.get("word") or "").strip()
            if not word:
                continue
            items.append({
                "title": word,
                "url": it.get("url") or it.get("rawUrl")
                or f"https://www.baidu.com/s?wd={urllib.parse.quote(word)}",
                "extra": str(it.get("hotScore") or ""),
            })
        if items:
            break
    if not items:
        raise FetchError("解析为空")
    return items


# ---------------------------------------------------------------------------
# RSS / 网页解析通道
# ---------------------------------------------------------------------------

def _rss(url, summary_len=70):
    r = _get(url, timeout=15)
    root = ET.fromstring(r.content)
    items = []
    for item in root.iter():
        if item.tag.rsplit("}", 1)[-1] != "item":
            continue
        title = link = desc = ""
        for child in item:
            name = child.tag.rsplit("}", 1)[-1]
            if name == "title":
                title = (child.text or "").strip()
            elif name == "link":
                link = (child.text or "").strip()
            elif name == "description":
                desc = (child.text or "").strip()
        if not title:
            continue
        extra = re.sub(r"<[^>]+>", "", htmllib.unescape(desc)).strip()
        extra = re.sub(r"\s+", " ", extra)[:summary_len]
        items.append({"title": htmllib.unescape(title), "url": link, "extra": extra})
    if not items:
        raise FetchError("RSS 无条目")
    return items


def ch_qbitai_rss():
    return _rss("https://www.qbitai.com/feed")


def _aibase_parse(html_text, base):
    seen, items = set(), []
    for m in re.finditer(
            r'<a[^>]+href="((?:https?://www\.aibase\.com)?/news/\d+[^"]*)"[^>]*>(.*?)</a>',
            html_text, re.S):
        href, title = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        title = htmllib.unescape(title)
        # 清洗 "/news" 页混入的时间前缀与品牌词；"/zh/daily" 页去掉序号
        title = re.sub(r"^(just now|\d+\s*(?:min(?:ute)?|hour|day)s? ago)[.\s]*", "",
                       title, flags=re.I)
        title = re.sub(r"^AIbase", "", title).strip()
        title = re.sub(r"^\d+、\s*", "", title)
        if not title or len(title) < 6 or title in seen:
            continue
        seen.add(title)
        items.append({
            "title": title,
            "url": href if href.startswith("http") else base.rstrip("/") + href,
            "extra": "",
        })
    if not items:
        raise FetchError("未解析到条目")
    return items


def ch_aibase_daily():
    base = "https://www.aibase.com"
    r = _get(f"{base}/zh/daily", timeout=15)
    return _aibase_parse(r.text, base)


def ch_aibase_news():
    base = "https://www.aibase.com"
    r = _get(f"{base}/news", timeout=15)
    return _aibase_parse(r.text, base)


# ---------------------------------------------------------------------------
# HuggingFace 热门论文（近期论文按点赞排序，天然规避周末无日报）
# ---------------------------------------------------------------------------

def ch_hf_papers():
    r = _get("https://huggingface.co/api/daily_papers", timeout=15)
    rows = r.json()
    items = []
    for row in rows:
        p = row.get("paper") or {}
        pid = (p.get("id") or "").strip()
        title = (p.get("title") or "").strip()
        if not title:
            continue
        up = int(p.get("upvotes") or 0)
        items.append({"title": title,
                      "url": f"https://huggingface.co/papers/{pid}" if pid else "",
                      "extra": f"{up} 赞" if up else "", "_up": up})
    if not items:
        raise FetchError("无论文数据")
    items.sort(key=lambda x: x.pop("_up", 0), reverse=True)
    return items


# ---------------------------------------------------------------------------
# GitHub Trending（倾向 AI 关键词，不足再补通用热榜）
# ---------------------------------------------------------------------------

_AI_WORDS = ("ai", "llm", "gpt", "agent", "rag", "diffus", "transformer",
             "model", "ml", "neural", "deep", "mcp", "vision", "speech",
             "chat", "prompt", "embedding", "inference", "training")


def ch_github_trending():
    r = _get("https://github.com/trending", timeout=15)
    blocks = re.findall(r'<article class="Box-row">(.*?)</article>', r.text, re.S)
    items = []
    for b in blocks:
        m = re.search(r'href="/([^"]+)/([^"/#?]+)"', b)
        if not m:
            continue
        owner, repo = m.group(1), m.group(2)
        dm = re.search(r"<p[^>]*>(.*?)</p>", b, re.S)
        desc = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", dm.group(1))).strip() if dm else ""
        sm = re.search(r"([\d,\.]+k?)\s*stars today", b)
        today = sm.group(1).replace(",", "") if sm else ""
        items.append({
            "title": f"{owner}/{repo}",
            "url": f"https://github.com/{owner}/{repo}",
            "extra": " ".join(x for x in (f"今日 {today} star" if today else "",
                                          desc[:60]) if x),
            "_blob": f"{owner}/{repo} {desc}".lower(),
        })
    if not items:
        raise FetchError("解析为空")

    def is_ai(it):
        return any(w in it["_blob"] for w in _AI_WORDS)

    ai = [i for i in items if is_ai(i)]
    chosen = (ai if len(ai) >= 3 else items)[:10]
    for it in chosen:
        it.pop("_blob", None)
    return chosen


# ---------------------------------------------------------------------------
# 源注册表：源名 -> 通道列表（按序兜底）
# ---------------------------------------------------------------------------

CHANNELS = {
    # 国内热点
    "yaowen": [ch_yaowen_60s, lambda: _dailyhot("people")],
    "weibo": [ch_weibo_direct, _codelife_factory("weibo"), ch_weibo_60s,
              lambda: _dailyhot("weibo")],
    "zhihu": [ch_zhihu_direct, _codelife_factory("zhihu"),
              lambda: _dailyhot("zhihu")],
    "baidu": [ch_baidu_direct, lambda: _dailyhot("baidu")],
    "douyin": [_codelife_factory("douyin"), lambda: _dailyhot("douyin")],
    "bilibili": [_codelife_factory("bilibili"), lambda: _dailyhot("bilibili")],
    "wechat_hot": [_codelife_factory("wechat_hot")],
    # AI 圈
    "qbitai": [ch_qbitai_rss],
    "aibase": [ch_aibase_daily, ch_aibase_news],
    "kr36": [_codelife_factory("kr36")],
    "hf_papers": [ch_hf_papers],
    "github_trending": [ch_github_trending],
    # 依赖海外实例，国内环境常不可达（默认关闭，留着做云端备用）
    "jiqizhixin": [lambda: _dailyhot("jiqizhixin")],
}


def fetch_source(name, top_n):
    """按兜底链抓取一个源，返回 (items, 通道名, 错误信息)。"""
    errors = []
    for fn in CHANNELS.get(name, []):
        try:
            items = [i for i in fn() if i.get("title")]
            if items:
                return items[:top_n], fn.__name__, None
            errors.append(f"{fn.__name__}: 空数据")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{fn.__name__}: {e}")
    return [], None, "；".join(errors) or "未注册的源"
