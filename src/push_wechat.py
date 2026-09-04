# -*- coding: utf-8 -*-
"""微信公众号测试号推送：access_token 获取 + 模板消息发送。"""
import requests

API_BASE = "https://api.weixin.qq.com"


class WeChatError(Exception):
    pass


def get_access_token(appid, secret):
    r = requests.get(f"{API_BASE}/cgi-bin/token",
                     params={"grant_type": "client_credential",
                             "appid": appid, "secret": secret},
                     timeout=10)
    j = r.json()
    if "access_token" not in j:
        raise WeChatError(f"获取 access_token 失败: {j}")
    return j["access_token"]


def send_template(appid, secret, *, openid, template_id, url, data):
    """data 形如 {"date": {"value": "...", "color": "#173177"}, ...}"""
    token = get_access_token(appid, secret)
    payload = {
        "touser": openid,
        "template_id": template_id,
        "url": url or "",
        "data": data,
    }
    r = requests.post(f"{API_BASE}/cgi-bin/message/template/send",
                      params={"access_token": token},
                      json=payload, timeout=10)
    j = r.json()
    if j.get("errcode") != 0:
        raise WeChatError(f"模板消息发送失败: {j}")
    return j


def push_daily(appid, secret, openid, template_id, *, title, date_str,
               digest_text, url):
    """按日报模板约定发送。模板内容参考 README：
        {{date.DATA}}
        {{digest.DATA}}
        点击本条消息查看完整日报
    title 形如 "📰 国内新闻日报" / "🤖 每日AI快报"。
    """
    data = {
        "date": {"value": f"{date_str} {title}", "color": "#173177"},
        "digest": {"value": digest_text, "color": "#333333"},
    }
    return send_template(appid, secret, openid=openid, template_id=template_id,
                         url=url, data=data)
