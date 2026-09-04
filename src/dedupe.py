# -*- coding: utf-8 -*-
"""去重：通过 GitHub contents API 判断今天的日报是否已推送（两个触发端共用）。"""
import requests


def already_pushed(repo, date_str, *, branch="main", docs_dir="docs", token=None):
    """docs/<date_str>.html 在 GitHub 上已存在 → True（date_str 形如 2026-09-05-news）。

    网络异常时按 False 处理（宁可多发一条，不漏发）。
    """
    if not repo:
        return False
    url = f"https://api.github.com/repos/{repo}/contents/{docs_dir}/{date_str}.html"
    headers = {"User-Agent": "wechat-news-daily"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.get(url, headers=headers, params={"ref": branch}, timeout=10)
        return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False
