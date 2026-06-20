"""
用户认证模块 v3.1 - 支持云端存储自选股
- 本地存储: users.json / sessions.json (项目目录下 data/)
- 云端存储: GitHub Gist（当 PAT 配置时自动启用）
- 邀请码: 1916416299 (硬编码)
- 密码: SHA256哈希存储
- 自选: 按用户隔离存储，优先云端
- Session: 用 URL query_param 传递 token，刷新不丢失
"""
import os
import json
import hashlib
import uuid
from datetime import datetime, timedelta

# ===== 尝试导入云端存储 =====
try:
    from cloud_storage import load_watchlist_cloud, save_watchlist_cloud, PAT as CLOUD_PAT
    _CLOUD_ENABLED = bool(CLOUD_PAT)
except Exception:
    _CLOUD_ENABLED = False


# ===== 配置 =====
INVITE_CODE = "1916416299"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
SESSIONS_FILE = os.path.join(DATA_DIR, "sessions.json")
SESSION_EXPIRE_DAYS = 30  # Session 30天有效


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)
    users_dir = os.path.join(DATA_DIR, "users")
    os.makedirs(users_dir, exist_ok=True)


def _load_users() -> dict:
    _ensure_data_dir()
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_users(users: dict):
    _ensure_data_dir()
    tmp = USERS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)
    os.replace(tmp, USERS_FILE)


def _load_sessions() -> dict:
    _ensure_data_dir()
    if not os.path.exists(SESSIONS_FILE):
        return {}
    try:
        with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_sessions(sessions: dict):
    _ensure_data_dir()
    tmp = SESSIONS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sessions, f, ensure_ascii=False, indent=2)
    os.replace(tmp, SESSIONS_FILE)


def _hash_password(password: str) -> str:
    salt = "blackbook_v3"
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()


def _clean_expired_sessions(sessions: dict) -> dict:
    """清理过期 session"""
    now = datetime.now()
    return {
        k: v for k, v in sessions.items()
        if datetime.fromisoformat(v.get("expire_at", "2000-01-01")) > now
    }


# ===== 注册 =====
def register(username: str, password: str, invite_code: str) -> dict:
    if not username or not password:
        return {"success": False, "msg": "用户名和密码不能为空"}
    if len(username) < 2 or len(username) > 20:
        return {"success": False, "msg": "用户名长度2-20字符"}
    if len(password) < 4:
        return {"success": False, "msg": "密码至少4位"}
    if invite_code != INVITE_CODE:
        return {"success": False, "msg": "邀请码错误，无法注册"}
    users = _load_users()
    if username in users:
        return {"success": False, "msg": "用户名已被注册"}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    users[username] = {
        "password_hash": _hash_password(password),
        "created_at": now,
        "last_login": None,
    }
    _save_users(users)
    return {"success": True, "msg": "注册成功"}


# ===== 登录 =====
def login(username: str, password: str) -> dict:
    users = _load_users()
    if username not in users:
        return {"success": False, "msg": "用户名或密码错误"}
    if users[username]["password_hash"] != _hash_password(password):
        return {"success": False, "msg": "用户名或密码错误"}
    # 更新最后登录时间
    users[username]["last_login"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _save_users(users)
    # 创建 session
    token = _create_session(username)
    return {"success": True, "msg": "登录成功", "token": token}


def _create_session(username: str) -> str:
    """创建 session，返回 token"""
    sessions = _load_sessions()
    sessions = _clean_expired_sessions(sessions)
    token = uuid.uuid4().hex
    expire_at = (datetime.now() + timedelta(days=SESSION_EXPIRE_DAYS)).isoformat()
    sessions[token] = {
        "username": username,
        "created_at": datetime.now().isoformat(),
        "expire_at": expire_at,
    }
    _save_sessions(sessions)
    return token


def validate_session(token: str) -> str | None:
    """
    验证 session token，返回用户名或 None
    用在每次页面加载时检查登录状态
    """
    if not token:
        return None
    sessions = _load_sessions()
    sessions = _clean_expired_sessions(sessions)
    _save_sessions(sessions)  # 顺手清理过期 session
    if token in sessions:
        return sessions[token]["username"]
    return None


def logout(token: str):
    """注销 session"""
    sessions = _load_sessions()
    sessions.pop(token, None)
    _save_sessions(sessions)


# ===== 用户存在检查 =====
def user_exists(username: str) -> bool:
    users = _load_users()
    return username in users


# ===== 自选股数据(按用户隔离，优先云端) =====
def get_watchlist_file(username: str) -> str:
    user_dir = os.path.join(DATA_DIR, "users")
    os.makedirs(user_dir, exist_ok=True)
    return os.path.join(user_dir, f"{username}_watchlist.json")


def load_user_watchlist(username: str) -> list:
    """加载自选股：优先云端，失败则本地"""
    # 优先云端
    if _CLOUD_ENABLED:
        try:
            cloud_data = load_watchlist_cloud(username)
            if cloud_data:
                return cloud_data
        except Exception:
            pass
    # 本地兜底
    fpath = get_watchlist_file(username)
    if not os.path.exists(fpath):
        return []
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_user_watchlist(username: str, watchlist: list):
    """保存自选股：云端+本地双写"""
    # 保存云端
    if _CLOUD_ENABLED:
        try:
            save_watchlist_cloud(username, watchlist)
        except Exception:
            pass
    # 保存本地
    fpath = get_watchlist_file(username)
    tmp = fpath + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(watchlist, f, ensure_ascii=False, indent=2)
    os.replace(tmp, fpath)


# ===== 获取所有用户名 =====
def list_users() -> list:
    users = _load_users()
    return list(users.keys())
