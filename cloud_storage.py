# -*- coding: utf-8 -*-
"""
云端数据存储 - 使用 GitHub Repo Contents API
每个用户一个 JSON 文件，存在 blackbook 仓库的 data/ 目录下
只需 repo 权限，不依赖 Gist
"""

import json
import base64
import urllib.request
import urllib.error


def _get_conf():
    """读取 PAT / USER / REPO，兼容 st.secrets 和 os.environ"""
    try:
        import streamlit as st
        pat = st.secrets.get("GITHUB_PAT", "").strip()
        user = st.secrets.get("GITHUB_USER", "kM-OD").strip()
        repo = st.secrets.get("GITHUB_REPO", "blackbook").strip()
        if pat:
            return pat, user, repo
    except Exception:
        pass

    import os
    pat = os.environ.get("GITHUB_PAT", "").strip()
    user = os.environ.get("GITHUB_USER", "kM-OD").strip()
    repo = os.environ.get("GITHUB_REPO", "blackbook").strip()
    return pat, user, repo


def _gh_get(path, pat):
    """GET 请求 GitHub API"""
    url = "https://api.github.com/repos/{}/{}".format(_get_conf()[1], path)
    req = urllib.request.Request(url)
    req.add_header("Authorization", "token " + pat)
    req.add_header("Accept", "application/vnd.github.v3+json")
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        return {"error": True, "code": e.code}
    except Exception:
        return {"error": True}


def _gh_put(path, data, pat):
    """PUT 请求 GitHub API（创建/更新文件）"""
    url = "https://api.github.com/repos/{}/{}".format(_get_conf()[1], path)
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method="PUT")
    req.add_header("Authorization", "token " + pat)
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("Content-Type", "application/json")
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": True, "code": e.code}
    except Exception:
        return {"error": True}


# ==================== 自选股读写 ====================

def load_watchlist_cloud(username):
    """从仓库 data/<username>_watchlist.json 读取自选"""
    pat, user, repo = _get_conf()
    if not pat:
        return []
    path = "{}/contents/data/{}_watchlist.json".format(repo, username)
    result = _gh_get(path, pat)
    if not result or result.get("error"):
        return []
    content_b64 = result.get("content", "")
    try:
        content = base64.b64decode(content_b64).decode("utf-8")
        return json.loads(content)
    except Exception:
        return []


def save_watchlist_cloud(username, watchlist):
    """保存自选到仓库 data/<username>_watchlist.json"""
    pat, user, repo = _get_conf()
    if not pat:
        return False
    # 先获取 SHA（更新需要）
    path = "{}/contents/data/{}_watchlist.json".format(repo, username)
    existing = _gh_get(path, pat)
    sha = existing.get("sha") if existing and not existing.get("error") else None

    content = json.dumps(watchlist, ensure_ascii=False, indent=2)
    content_b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")

    data = {
        "message": "save watchlist: {}".format(username),
        "content": content_b64,
        "branch": "main",
    }
    if sha:
        data["sha"] = sha

    result = _gh_put(path, data, pat)
    return bool(result and not result.get("error"))


# ==================== Sessions 读写 ====================

def load_sessions_cloud():
    """从仓库 data/sessions.json 读取 sessions"""
    pat, user, repo = _get_conf()
    if not pat:
        return None
    path = "{}/contents/data/sessions.json".format(repo)
    result = _gh_get(path, pat)
    if not result or result.get("error"):
        return None
    content_b64 = result.get("content", "")
    try:
        content = base64.b64decode(content_b64).decode("utf-8")
        return json.loads(content)
    except Exception:
        return None


def save_sessions_cloud(sessions):
    """保存 sessions 到仓库 data/sessions.json"""
    pat, user, repo = _get_conf()
    if not pat:
        return False
    path = "{}/contents/data/sessions.json".format(repo)
    existing = _gh_get(path, pat)
    sha = existing.get("sha") if existing and not existing.get("error") else None

    content = json.dumps(sessions, ensure_ascii=False, indent=2)
    content_b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")

    data = {
        "message": "save sessions",
        "content": content_b64,
        "branch": "main",
    }
    if sha:
        data["sha"] = sha

    result = _gh_put(path, data, pat)
    return bool(result and not result.get("error"))
