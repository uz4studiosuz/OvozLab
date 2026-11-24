"""Foydalanuvchi hisoblari: Telegram ID bo'yicha bitta hisob (sayt + bot + API), token balansi, API kalitlar.

Ma'lumotlar SQLite'da: ``<OVOZLAB_HOME>/accounts.db``.

Token narxlari (muhit o'zgaruvchilari bilan o'zgartiriladi):
    OVOZLAB_FREE_TOKENS     — yangi hisobga beriladigan bepul token (standart 2000)
    OVOZLAB_COST_TTS_CHAR   — matndan nutq: 1 belgi uchun (standart 1)
    OVOZLAB_COST_STT_SEC    — nutqdan matn: 1 soniya audio uchun (standart 1)
    OVOZLAB_COST_CLONE      — bitta ovoz klonlash (standart 100)
    OVOZLAB_ADMINS          — admin Telegram ID lari, vergul bilan (standart 5427799219)
"""

from __future__ import annotations

import hashlib
import hmac
import math
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path

from ovozlab import config


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


FREE_TOKENS = _int_env("OVOZLAB_FREE_TOKENS", 2000)
COST_TTS_CHAR = _int_env("OVOZLAB_COST_TTS_CHAR", 1)
COST_STT_SEC = _int_env("OVOZLAB_COST_STT_SEC", 1)
COST_CLONE = _int_env("OVOZLAB_COST_CLONE", 100)
ADMINS = {int(x) for x in os.environ.get("OVOZLAB_ADMINS", "5427799219").replace(" ", "").split(",") if x.isdigit()}
CONTACT = os.environ.get("OVOZLAB_CONTACT", "usmoxan").lstrip("@")
MAX_KEYS = 5
SESSION_DAYS = 30
KEY_PREFIX = "olk_"
ROLES = ("user", "vip", "admin")

DB_PATH = config.HOME / "accounts.db"
_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,               -- Telegram user id
    first_name TEXT, last_name TEXT, username TEXT, photo_url TEXT,
    role TEXT NOT NULL DEFAULT 'user',    -- user | vip | admin
    tokens INTEGER NOT NULL DEFAULT 0,
    used INTEGER NOT NULL DEFAULT 0,      -- jami sarflangan
    blocked INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    created_at INTEGER NOT NULL, last_seen INTEGER
);
CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT, key_hash TEXT UNIQUE NOT NULL, hint TEXT,
    created_at INTEGER NOT NULL, last_used INTEGER, revoked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL, ts INTEGER NOT NULL,
    kind TEXT NOT NULL,                   -- tts | stt | clone | grant
    amount INTEGER NOT NULL, source TEXT, detail TEXT
);
CREATE INDEX IF NOT EXISTS usage_user_ts ON usage(user_id, ts);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""


class NotEnoughTokens(Exception):
    def __init__(self, need: int, have: int) -> None:
        super().__init__(need, have)
        self.need, self.have = need, have

    def message(self) -> str:
        return (f"Tokeningiz yetarli emas: kerak {need_fmt(self.need)}, sizda {need_fmt(self.have)}. "
                f"Token olish uchun Telegram'da @{CONTACT} ga yozing: https://t.me/{CONTACT}")


def need_fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def db() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, isolation_level=None)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.executescript(SCHEMA)
        return _conn


def _q(sql: str, args=()) -> list[dict]:
    with _lock:
        return [dict(r) for r in db().execute(sql, args).fetchall()]


def _x(sql: str, args=()) -> sqlite3.Cursor:
    with _lock:
        return db().execute(sql, args)


# ------------------------------------------------------------------ secret
def secret() -> bytes:
    """Sessiya cookie'larini imzolash uchun doimiy kalit (birinchi marta yaratiladi)."""
    env = os.environ.get("OVOZLAB_SECRET", "").strip()
    if env:
        return env.encode()
    with _lock:
        row = db().execute("SELECT v FROM meta WHERE k='secret'").fetchone()
        if row:
            return row[0].encode()
        value = secrets.token_hex(32)
        db().execute("INSERT INTO meta(k, v) VALUES('secret', ?)", (value,))
        return value.encode()


# ------------------------------------------------------------------- users
def is_unlimited(user: dict) -> bool:
    return user["role"] in ("vip", "admin")


def public(user: dict) -> dict:
    name = " ".join(x for x in (user.get("first_name"), user.get("last_name")) if x) or user.get("username") or str(user["id"])
    return {
        "id": user["id"], "name": name, "username": user.get("username"), "photo_url": user.get("photo_url"),
        "role": user["role"], "tokens": user["tokens"], "used": user["used"], "unlimited": is_unlimited(user),
        "blocked": bool(user["blocked"]), "created_at": user["created_at"], "last_seen": user.get("last_seen"),
        "note": user.get("note"),
    }


def get(user_id: int) -> dict | None:
    rows = _q("SELECT * FROM users WHERE id=?", (user_id,))
    return rows[0] if rows else None


def ensure(user_id: int, profile: dict | None = None) -> dict:
    """Hisobni qaytaradi; yo'q bo'lsa bepul token bilan yaratadi. ``profile`` — Telegram ma'lumotlari."""
    profile = {k: (str(v)[:200] if v else None) for k, v in (profile or {}).items()
               if k in ("first_name", "last_name", "username", "photo_url")}
    now = int(time.time())
    with _lock:
        user = get(user_id)
        if user is None:
            role = "admin" if user_id in ADMINS else "user"
            _x("INSERT INTO users(id, first_name, last_name, username, photo_url, role, tokens, created_at, last_seen) "
               "VALUES(?,?,?,?,?,?,?,?,?)",
               (user_id, profile.get("first_name"), profile.get("last_name"), profile.get("username"),
                profile.get("photo_url"), role, FREE_TOKENS, now, now))
            if FREE_TOKENS:
                _log(user_id, "grant", FREE_TOKENS, "system", "Bepul tokenlar")
        else:
            sets, args = ["last_seen=?"], [now]
            for k, v in profile.items():
                if v and v != user.get(k):
                    sets.append(f"{k}=?")
                    args.append(v)
            if user_id in ADMINS and user["role"] != "admin":
                sets.append("role='admin'")
            _x(f"UPDATE users SET {', '.join(sets)} WHERE id=?", (*args, user_id))
        return get(user_id)


def _log(user_id: int, kind: str, amount: int, source: str | None, detail: str | None) -> None:
    _x("INSERT INTO usage(user_id, ts, kind, amount, source, detail) VALUES(?,?,?,?,?,?)",
       (user_id, int(time.time()), kind, amount, source, (detail or "")[:200]))


def check(user: dict, amount: int) -> None:
    if user and not is_unlimited(user) and user["tokens"] < amount:
        raise NotEnoughTokens(amount, user["tokens"])


def charge(user: dict, kind: str, amount: int, source: str, detail: str = "") -> int:
    """Muvaffaqiyatli ishdan keyin tokenni yechadi. VIP/admin — faqat yozib qo'yiladi. Qolgan balansni qaytaradi."""
    amount = max(int(amount), 0)
    with _lock:
        if is_unlimited(user):
            _x("UPDATE users SET used=used+? WHERE id=?", (amount, user["id"]))
        else:
            _x("UPDATE users SET tokens=MAX(tokens-?, 0), used=used+? WHERE id=?", (amount, amount, user["id"]))
        _log(user["id"], kind, -amount, source, detail)
        return get(user["id"])["tokens"]


def cost_tts(text: str) -> int:
    return max(1, len(text) * COST_TTS_CHAR)


def cost_stt(seconds: float) -> int:
    return max(1, math.ceil(seconds) * COST_STT_SEC)


def usage(user_id: int, limit: int = 50) -> list[dict]:
    return _q("SELECT ts, kind, amount, source, detail FROM usage WHERE user_id=? ORDER BY id DESC LIMIT ?",
              (user_id, limit))


# ----------------------------------------------------------------- api keys
def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create_key(user_id: int, name: str) -> dict:
    with _lock:
        n = _q("SELECT COUNT(*) AS n FROM api_keys WHERE user_id=? AND revoked=0", (user_id,))[0]["n"]
        if n >= MAX_KEYS:
            raise ValueError(f"Ko'pi bilan {MAX_KEYS} ta faol kalit bo'lishi mumkin. Eskisini o'chiring")
        key = KEY_PREFIX + secrets.token_urlsafe(30)
        hint = f"{key[:8]}…{key[-4:]}"
        cur = _x("INSERT INTO api_keys(user_id, name, key_hash, hint, created_at) VALUES(?,?,?,?,?)",
                 (user_id, (name or "API kalit").strip()[:60], _hash(key), hint, int(time.time())))
        return {"id": cur.lastrowid, "name": name, "hint": hint, "key": key}


def list_keys(user_id: int) -> list[dict]:
    return _q("SELECT id, name, hint, created_at, last_used FROM api_keys WHERE user_id=? AND revoked=0 "
              "ORDER BY id DESC", (user_id,))


def revoke_key(user_id: int, key_id: int) -> bool:
    return _x("UPDATE api_keys SET revoked=1 WHERE id=? AND user_id=? AND revoked=0", (key_id, user_id)).rowcount > 0


def user_by_key(key: str) -> dict | None:
    if not key.startswith(KEY_PREFIX):
        return None
    rows = _q("SELECT id, user_id FROM api_keys WHERE key_hash=? AND revoked=0", (_hash(key),))
    if not rows:
        return None
    _x("UPDATE api_keys SET last_used=? WHERE id=?", (int(time.time()), rows[0]["id"]))
    return get(rows[0]["user_id"])


# ----------------------------------------------------------------- sessions
def make_session(user_id: int) -> str:
    exp = int(time.time()) + SESSION_DAYS * 86400
    body = f"{user_id}.{exp}"
    sig = hmac.new(secret(), body.encode(), hashlib.sha256).hexdigest()[:40]
    return f"{body}.{sig}"


def user_by_session(token: str) -> dict | None:
    try:
        uid, exp, sig = token.split(".")
        body = f"{uid}.{exp}"
        good = hmac.new(secret(), body.encode(), hashlib.sha256).hexdigest()[:40]
        if not hmac.compare_digest(sig, good) or int(exp) < time.time():
            return None
        return get(int(uid))
    except (ValueError, AttributeError):
        return None


def verify_telegram(data: dict, bot_token: str, max_age: int = 86400) -> dict:
    """Telegram Login Widget ma'lumotini tekshiradi: https://core.telegram.org/widgets/login#checking-authorization"""
    data = {k: str(v) for k, v in data.items() if v is not None}
    got = data.pop("hash", "")
    check_string = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    key = hashlib.sha256(bot_token.encode()).digest()
    good = hmac.new(key, check_string.encode(), hashlib.sha256).hexdigest()
    if not got or not hmac.compare_digest(got, good):
        raise ValueError("Telegram imzosi noto'g'ri")
    if time.time() - int(data.get("auth_date", 0)) > max_age:
        raise ValueError("Kirish muddati o'tgan, qaytadan kiring")
    return data


# -------------------------------------------------------------------- admin
def list_users(q: str = "", limit: int = 200, offset: int = 0) -> list[dict]:
    q = (q or "").strip().lstrip("@")
    if q:
        like = f"%{q}%"
        rows = _q("SELECT * FROM users WHERE CAST(id AS TEXT) LIKE ? OR username LIKE ? OR first_name LIKE ? "
                  "OR last_name LIKE ? ORDER BY last_seen DESC LIMIT ? OFFSET ?", (like, like, like, like, limit, offset))
    else:
        rows = _q("SELECT * FROM users ORDER BY last_seen DESC LIMIT ? OFFSET ?", (limit, offset))
    return [public(r) for r in rows]


def admin_update(user_id: int, *, add: int | None = None, set_tokens: int | None = None, role: str | None = None,
                 blocked: bool | None = None, note: str | None = None, by: int | None = None) -> dict:
    with _lock:
        user = get(user_id)
        if user is None:
            raise KeyError(user_id)
        if set_tokens is not None:
            diff = int(set_tokens) - user["tokens"]
            _x("UPDATE users SET tokens=? WHERE id=?", (max(int(set_tokens), 0), user_id))
            _log(user_id, "grant", diff, "admin", f"Balans o'rnatildi: {set_tokens} (admin {by})")
        if add:
            _x("UPDATE users SET tokens=MAX(tokens+?, 0) WHERE id=?", (int(add), user_id))
            _log(user_id, "grant", int(add), "admin", f"Admin {by}")
        if role is not None:
            if role not in ROLES:
                raise ValueError("Noto'g'ri rol")
            if user_id in ADMINS and role != "admin":
                raise ValueError("Asosiy adminning rolini o'zgartirib bo'lmaydi")
            _x("UPDATE users SET role=? WHERE id=?", (role, user_id))
        if blocked is not None:
            if user_id in ADMINS and blocked:
                raise ValueError("Asosiy adminni bloklab bo'lmaydi")
            _x("UPDATE users SET blocked=? WHERE id=?", (1 if blocked else 0, user_id))
        if note is not None:
            _x("UPDATE users SET note=? WHERE id=?", (note.strip()[:200] or None, user_id))
        return public(get(user_id))


def stats() -> dict:
    day = int(time.time()) - 86400
    one = lambda sql, a=(): _q(sql, a)[0]["n"] or 0  # noqa: E731
    return {
        "users": one("SELECT COUNT(*) AS n FROM users"),
        "active_24h": one("SELECT COUNT(*) AS n FROM users WHERE last_seen>?", (day,)),
        "new_24h": one("SELECT COUNT(*) AS n FROM users WHERE created_at>?", (day,)),
        "vip": one("SELECT COUNT(*) AS n FROM users WHERE role IN ('vip','admin')"),
        "blocked": one("SELECT COUNT(*) AS n FROM users WHERE blocked=1"),
        "spent_24h": -one("SELECT SUM(amount) AS n FROM usage WHERE kind IN ('tts','stt','clone') AND ts>?", (day,)),
        "requests_24h": one("SELECT COUNT(*) AS n FROM usage WHERE kind IN ('tts','stt','clone') AND ts>?", (day,)),
        "by_kind_24h": {r["kind"]: r["n"] for r in _q(
            "SELECT kind, COUNT(*) AS n FROM usage WHERE kind IN ('tts','stt','clone') AND ts>? GROUP BY kind", (day,))},
        "prices": prices(),
    }


def prices() -> dict:
    return {"free_tokens": FREE_TOKENS, "tts_per_char": COST_TTS_CHAR, "stt_per_sec": COST_STT_SEC,
            "clone": COST_CLONE, "contact": CONTACT}


def path() -> Path:
    return DB_PATH
