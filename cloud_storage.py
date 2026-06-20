# -*- coding: utf-8 -*-
"""
云端数据存储 - 使用 GitHub Private Gist
每个用户一个 Gist 文件，存储自选股数据
"""
import json
import os
import base64
import urllib.request

# 从环境变量读取 PAT（Streamlit Cloud 用 secrets.toml）
PAT = os.environ.get("GITHUB_PAT", "")
USER = os.environ.get("GITHUB_USER", "kM-OD")


def _api(method, path, data=None):
    """调用 GitHub API"""
    if not PAT:
        return None
    url = f"https://api.github.com/{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", "token " + PAT)
    req.add_header("Accept", "application/vnd.github.v3+json")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        resp = urllib.request.urlopen(req)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": True, "code": e.code}
    except Exception as e:
        return {"error": True, "msg": str(e)}


def get_gist_id(username):
    """查找用户的 Gist ID（通过 description 匹配）"""
    result = _api("GET", f"users/{USER}/gists")
    if not result or isinstance(result, dict):
        return None
    for gist in result:
        desc = gist.get("description", "")
        tag = f"[blackbook:{username}]"
        if tag in desc:
            return gist["id"]
    return None


def load_watchlist_cloud(username):
    """从云端 Gist 读取自选列表"""
    gist_id = get_gist_id(username)
    if not gist_id:
        return []
    result = _api("GET", f"gists/{gist_id}")
    if not result or isinstance(result, dict) and result.get("error"):
        return []
    # 找到 watchlist.json 文件
    files = result.get("files", {})
    for fname, finfo in files.items():
        if fname.endswith("_watchlist.json") or fname == "watchlist.json":
            content = finfo.get("content", "[]")
            try:
                return json.loads(content)
            except Exception:
                return []
    return []


def save_watchlist_cloud(username, watchlist):
    """保存自选列表到云端 Gist"""
    content = json.dumps(watchlist, ensure_ascii=False, indent=2)
    filename = f"{username}_watchlist.json"
    desc = f"[blackbook:{username}] 自选股数据"

    gist_id = get_gist_id(username)

    data = {
        "description": desc,
        "files": {filename: {"content": content}},
        "public": False,
    }

    if gist_id:
        # 更新已有 Gist
        result = _api("PATCH", f"gists/{gist_id}", data)
    else:
        # 创建新 Gist
        result = _api("POST", "gists", data)

    if result and not result.get("error"):
        return True
    return False
