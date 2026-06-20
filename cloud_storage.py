# -*- coding: utf-8 -*-
"""
云端数据存储 - 使用 GitHub Private Gist
每个用户一个 Gist 文件，存储自选股数据

⚠️ PAT/USER 改为 lazy 读取（每次调用时读 st.secrets），
避免模块加载时 Streamlit 尚未初始化导致读不到 secrets。
"""


import json
import base64
import urllib.request
import urllib.error


def _get_pat_and_user():
    """延迟读取 PAT / USER，兼容 Streamlit secrets 和 os.environ"""
    # 1. 尝试 st.secrets（Streamlit Cloud 正式方式）
    try:
        import streamlit as st
        pat = st.secrets.get("GITHUB_PAT", "").strip()
        user = st.secrets.get("GITHUB_USER", "kM-OD").strip()
        if pat:
            return pat, user
    except Exception:
        pass

    # 2. fallback: 环境变量（本地调试用）
    import os
    pat = os.environ.get("GITHUB_PAT", "").strip()
    user = os.environ.get("GITHUB_USER", "kM-OD").strip()
    return pat, user


def _api(method, path, data=None, pat=None):
    """调用 GitHub API"""
    if pat is None:
        pat, _ = _get_pat_and_user()
    if not pat:
        return None
    url = f"https://api.github.com/{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", "token " + pat)
    req.add_header("Accept", "application/vnd.github.v3+json")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": True, "code": e.code}
    except Exception as e:
        return {"error": True, "msg": str(e)}


def get_gist_id(username, pat=None):
    """查找用户的 Gist ID（通过 description 匹配）"""
    if pat is None:
        pat, user = _get_pat_and_user()
    if not pat:
        return None
    result = _api("GET", f"users/{user}/gists?per_page=100", pat=pat)
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
    pat, user = _get_pat_and_user()
    if not pat:
        return []
    gist_id = get_gist_id(username, pat=pat)
    if not gist_id:
        return []
    result = _api("GET", f"gists/{gist_id}", pat=pat)
    if not result or isinstance(result, dict) and result.get("error"):
        return []
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
    pat, user = _get_pat_and_user()
    if not pat:
        return False
    content = json.dumps(watchlist, ensure_ascii=False, indent=2)
    filename = f"{username}_watchlist.json"
    desc = f"[blackbook:{username}] 自选股数据"

    gist_id = get_gist_id(username, pat=pat)

    data = {
        "description": desc,
        "files": {filename: {"content": content}},
        "public": False,
    }

    if gist_id:
        result = _api("PATCH", f"gists/{gist_id}", data, pat=pat)
    else:
        result = _api("POST", "gists", data, pat=pat)

    if result and not result.get("error"):
        return True
    return False


# ==================== Sessions 云端读写 ====================

def _get_sessions_gist_id(pat=None):
    """查找 sessions Gist ID"""
    if pat is None:
        pat, user = _get_pat_and_user()
    if not pat:
        return None
    result = _api("GET", f"users/{user}/gists?per_page=100", pat=pat)
    if not result or isinstance(result, dict):
        return None
    for gist in result:
        if gist.get("description") == "[blackbook:sessions]":
            return gist["id"]
    return None


def load_sessions_cloud():
    """从云端读取 sessions"""
    pat, user = _get_pat_and_user()
    if not pat:
        return None
    gist_id = _get_sessions_gist_id(pat=pat)
    if not gist_id:
        return None
    result = _api("GET", f"gists/{gist_id}", pat=pat)
    if not result or isinstance(result, dict) and result.get("error"):
        return None
    files = result.get("files", {})
    for fname, finfo in files.items():
        if fname == "sessions.json":
            content = finfo.get("content", "{}")
            try:
                return json.loads(content)
            except Exception:
                return None
    return None


def save_sessions_cloud(sessions):
    """保存 sessions 到云端"""
    pat, user = _get_pat_and_user()
    if not pat:
        return False
    content = json.dumps(sessions, ensure_ascii=False, indent=2)
    desc = "[blackbook:sessions]"
    filename = "sessions.json"

    gist_id = _get_sessions_gist_id(pat=pat)

    data = {
        "description": desc,
        "files": {filename: {"content": content}},
        "public": False,
    }

    if gist_id:
        result = _api("PATCH", f"gists/{gist_id}", data, pat=pat)
    else:
        result = _api("POST", "gists", data, pat=pat)

    if result and not result.get("error"):
        return True
    return False
