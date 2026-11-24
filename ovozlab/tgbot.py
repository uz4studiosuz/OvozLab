"""OvozLab Telegram boti: matn -> ovoz, ovoz/video -> matn va SRT subtitr, ovoz klonlash.

Faqat standart kutubxona (urllib) — qo'shimcha paket kerak emas. OvozLab API'ga HTTP orqali ulanadi.

    TELEGRAM_BOT_TOKEN=... OVOZLAB_API_URL=http://ovozlab:8020 OVOZLAB_API_KEY=... python -m ovozlab.tgbot
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

log = logging.getLogger("ovozlab.bot")

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
API_URL = os.environ.get("OVOZLAB_API_URL", "http://ovozlab:8020").rstrip("/")
API_KEY = os.environ.get("OVOZLAB_API_KEY", "").strip()
STATE_FILE = Path(os.environ.get("BOT_STATE", "/data/bot/state.json"))
RATE_PER_HOUR = int(os.environ.get("BOT_RATE_PER_HOUR", "60"))
WEB_URL = os.environ.get("OVOZLAB_WEB_URL", "").rstrip("/")  # sayt manzili (dashboard: WEB_URL/app)
CONTACT = os.environ.get("OVOZLAB_CONTACT", "usmoxan").lstrip("@")
TG_FILE_LIMIT = 20 * 1024 * 1024  # Bot API getFile chegarasi
TG = f"https://api.telegram.org/bot{TOKEN}"
TG_FILE = f"https://api.telegram.org/file/bot{TOKEN}"

PRESETS = {  # tugma nomi -> instruct
    "auto": ("🤖 Avtomatik", None),
    "male": ("👨 Erkak", "male, middle-aged"),
    "female": ("👩 Ayol", "female, young adult"),
    "boy": ("🧒 Bola", "child"),
    "old": ("👴 Keksa", "male, elderly"),
    "deep": ("🎙 Past ovoz", "male, very low pitch"),
    "whisper": ("🤫 Shivirlash", "female, whisper"),
}
MOODS = {"neutral": "😐 Oddiy", "happy": "😄 Quvnoq", "sad": "😢 G'amgin", "serious": "🧐 Jiddiy", "story": "📖 Hikoyachi"}
SPEEDS = ["0.8", "1.0", "1.2", "1.5"]

HELP = (
    "<b>OvozLab</b> — o'zbekcha ovoz boti 🇺🇿\n\n"
    "✍️ <b>Matn yuboring</b> — ovozli xabar qilib qaytaraman.\n"
    "🎤 <b>Ovozli xabar yuboring</b> — matnga o'giraman.\n"
    "🎬 <b>Video yoki audio yuboring</b> — matn va <b>SRT subtitr</b> fayl (CapCut, Premiere uchun).\n\n"
    "<b>Sozlamalar:</b>\n"
    "/ovoz — ovozni tanlash\n"
    "/kayfiyat — ohang: quvnoq, jiddiy, hikoyachi…\n"
    "/tezlik — o'qish tezligi\n"
    "/klon — o'z ovozingizni yaratish (5–15 soniyalik yozuvdan)\n"
    "/ochir — klonlangan ovozni o'chirish\n"
    "/qator — subtitrda 1 yoki 2 qator (Reels uchun 1)\n"
    "/sozlamalar — joriy sozlamalar\n"
    "/hisob — token balansi va sayt orqali kirish\n\n"
    "ℹ️ Fayl hajmi 20 MB gacha (Telegram cheklovi)."
)


# ---------------------------------------------------------------- state
class State:
    def __init__(self, path: Path) -> None:
        self.path, self.lock = path, threading.Lock()
        try:
            self.data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {"users": {}, "offset": 0}

    def user(self, uid: int) -> dict:
        with self.lock:
            u = self.data["users"].setdefault(str(uid), {})
            for k, v in {"voice": "auto", "mood": "neutral", "speed": "1.0", "lines": 2, "voices": [],
                         "awaiting": None, "hits": []}.items():
                u.setdefault(k, v)
            return u

    def save(self) -> None:
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)


state = State(STATE_FILE)


# ----------------------------------------------------------------- http
def _multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    out = bytearray()
    for k, v in fields.items():
        if v is None:
            continue
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    for k, (name, data, ctype) in files.items():
        safe = name.replace('"', "")
        out += (f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{safe}"\r\n'
                f"Content-Type: {ctype}\r\n\r\n").encode() + data + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def _request(url: str, data: bytes | None = None, headers: dict | None = None, method: str | None = None,
             timeout: float = 120) -> bytes:
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


class ApiError(Exception):
    pass


def api(method: str, path: str, *, json_body=None, fields=None, files=None, timeout: float = 600,
        who: dict | None = None) -> bytes:
    """``who`` — Telegram ``from`` obyekti: so'rov shu foydalanuvchi hisobidan (tokenidan) bajariladi."""
    headers = {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}
    if who and who.get("id"):
        headers["X-OvozLab-User"] = str(who["id"])
        for key, h in (("first_name", "First-Name"), ("last_name", "Last-Name"), ("username", "Username")):
            if who.get(key):
                headers[f"X-OvozLab-{h}"] = urllib.parse.quote(str(who[key]))
    data = None
    if json_body is not None:
        data, headers["Content-Type"] = json.dumps(json_body).encode(), "application/json"
    elif files is not None:
        data, headers["Content-Type"] = _multipart(fields or {}, files)
    try:
        return _request(API_URL + path, data, headers, method, timeout)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get("detail")
        except Exception:
            detail = None
        raise ApiError(detail if isinstance(detail, str) else f"Server xatosi ({exc.code})") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ApiError("OvozLab serveriga ulanib bo'lmadi, birozdan keyin urinib ko'ring") from exc


def tg(method: str, http_timeout: float = 60, **params) -> dict:
    data = json.dumps(params).encode()
    raw = _request(f"{TG}/{method}", data, {"Content-Type": "application/json"}, timeout=http_timeout)
    return json.loads(raw)


def tg_upload(method: str, fields: dict, files: dict) -> dict:
    data, ctype = _multipart(fields, files)
    try:
        return json.loads(_request(f"{TG}/{method}", data, {"Content-Type": ctype}, timeout=300))
    except urllib.error.HTTPError as exc:
        log.error("%s: %s", method, exc.read()[:300])
        raise


def send(chat_id: int, text: str, **kw) -> None:
    for i in range(0, max(len(text), 1), 4000):
        tg("sendMessage", chat_id=chat_id, text=text[i:i + 4000], parse_mode="HTML",
           disable_web_page_preview=True, **kw)


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def action(chat_id: int, kind: str) -> None:
    try:
        tg("sendChatAction", chat_id=chat_id, action=kind)
    except Exception:
        pass


def keep_action(chat_id: int, kind: str) -> threading.Event:
    """Uzoq ish paytida "ovoz yozmoqda…" ko'rsatkichini ushlab turadi."""
    stop = threading.Event()

    def run():
        while not stop.is_set():
            action(chat_id, kind)
            stop.wait(4.5)

    threading.Thread(target=run, daemon=True).start()
    return stop


def download(file_id: str) -> bytes:
    info = tg("getFile", file_id=file_id)["result"]
    return _request(f"{TG_FILE}/{info['file_path']}", timeout=300)


def to_ogg(mp3: bytes) -> bytes | None:
    """Telegram ovozli xabari uchun OGG/Opus."""
    try:
        import imageio_ffmpeg

        ff = imageio_ffmpeg.get_ffmpeg_exe()
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "in.mp3", Path(tmp) / "out.ogg"
            src.write_bytes(mp3)
            subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(src), "-c:a", "libopus", "-b:a", "48k",
                            "-ar", "48000", "-ac", "1", str(dst)], check=True, timeout=120)
            return dst.read_bytes()
    except Exception:
        log.exception("OGG ga o'girib bo'lmadi")
        return None


# ------------------------------------------------------------- features
def rate_ok(u: dict) -> bool:
    now = time.time()
    u["hits"] = [t for t in u["hits"] if now - t < 3600]
    if len(u["hits"]) >= RATE_PER_HOUR:
        return False
    u["hits"].append(now)
    return True


def my_voices(who: dict) -> list[dict]:
    """Foydalanuvchining klon ovozlari — saytda yaratilganlari ham shu yerda."""
    try:
        return [{"id": v["id"], "name": v.get("name", "Ovoz")} for v in json.loads(api("GET", "/voices", who=who))]
    except (ApiError, ValueError):
        return []


def voice_label(u: dict, who: dict | None = None) -> str:
    v = u["voice"]
    if v.startswith("id:"):
        meta = next((x for x in (my_voices(who) if who else u["voices"]) if x["id"] == v[3:]), None)
        return f"🧬 {meta['name']}" if meta else PRESETS["auto"][0]
    return PRESETS.get(v, PRESETS["auto"])[0]


def fmt_n(n) -> str:
    return f"{int(n):,}".replace(",", " ")


def account(who: dict) -> dict:
    return json.loads(api("GET", "/account/me", who=who))


def account_text(me: dict) -> str:
    role = {"admin": "👑 Admin", "vip": "💎 VIP", "user": "Oddiy"}.get(me["role"], me["role"])
    bal = "♾ Cheksiz" if me["unlimited"] else f"<b>{fmt_n(me['tokens'])}</b> token"
    pr = me["prices"]
    lines = [
        f"👤 <b>{esc(me['name'])}</b> · ID <code>{me['id']}</code>",
        f"🏷 Tarif: {role}",
        f"💰 Balans: {bal}",
        f"📊 Jami sarflangan: {fmt_n(me['used'])} token",
        "",
        "<b>Narxlar:</b>",
        f"• Matndan nutq — {pr['tts_per_char']} token / belgi",
        f"• Nutqdan matn — {pr['stt_per_sec']} token / soniya",
        f"• Ovoz klonlash — {pr['clone']} token",
        "",
        f"Token olish uchun: @{CONTACT}",
    ]
    if WEB_URL:
        lines.append(f"🌐 Sayt va API kalit: {WEB_URL}/app")
    return "\n".join(lines)


def do_tts(chat_id: int, u: dict, text: str, who: dict) -> None:
    if len(text) > 5000:
        return send(chat_id, "Matn juda uzun: 5000 belgigacha yuboring.")
    body = {"text": text, "format": "mp3", "save_history": False, "speed": float(u["speed"])}
    if u["mood"] != "neutral":
        body["mood"] = u["mood"]
    v = u["voice"]
    if v.startswith("id:"):
        body["voice_id"] = v[3:]
    elif PRESETS.get(v, (None, None))[1]:
        body["instruct"] = PRESETS[v][1]
    stop = keep_action(chat_id, "record_voice")
    try:
        mp3 = api("POST", "/tts", json_body=body, who=who)
    finally:
        stop.set()
    ogg = to_ogg(mp3)
    if ogg:
        tg_upload("sendVoice", {"chat_id": chat_id}, {"voice": ("ovozlab.ogg", ogg, "audio/ogg")})
    else:
        tg_upload("sendAudio", {"chat_id": chat_id, "title": "OvozLab"}, {"audio": ("ovozlab.mp3", mp3, "audio/mpeg")})


def media_of(msg: dict) -> tuple[dict, str, str] | None:
    """(file obyekti, fayl nomi, turi) — voice | audio | video | video_note | document."""
    for kind, default in (("voice", "voice.ogg"), ("audio", "audio.mp3"), ("video", "video.mp4"),
                          ("video_note", "video.mp4")):
        if msg.get(kind):
            f = msg[kind]
            return f, f.get("file_name") or default, kind
    doc = msg.get("document")
    if doc and (doc.get("mime_type") or "").split("/")[0] in ("audio", "video"):
        return doc, doc.get("file_name") or "fayl", "document"
    return None


def do_stt(chat_id: int, u: dict, msg: dict, media: tuple) -> None:
    who = msg.get("from") or {}
    f, name, kind = media
    if (f.get("file_size") or 0) > TG_FILE_LIMIT:
        return send(chat_id, "Fayl 20 MB dan katta — Telegram botlarga bundan kattasini bermaydi.\n"
                             "Videoni siqib yoki faqat audiosini yuboring.")
    send(chat_id, "⏳ Matnga o'girilmoqda…", reply_to_message_id=msg["message_id"])
    stop = keep_action(chat_id, "typing")
    try:
        data = download(f["file_id"])
        res = json.loads(api("POST", f"/stt?max_lines={u['lines']}", files={"audio": (name, data, "application/octet-stream")},
                             timeout=3600, who=who))
    finally:
        stop.set()
    text = res.get("text") or ""
    if not text:
        return send(chat_id, "Nutq topilmadi 🤷")
    if kind == "voice" and len(text) < 3500:
        return send(chat_id, esc(text))
    stem = Path(name).stem or "subtitr"
    srt = _srt(res["cues"])
    caption = f"✅ {len(res['cues'])} ta subtitr · {res.get('duration_s', 0):.0f} s audio"
    if len(text) <= 3500:
        send(chat_id, esc(text))
    else:
        tg_upload("sendDocument", {"chat_id": chat_id}, {"document": (f"{stem}.txt", text.encode(), "text/plain")})
    tg_upload("sendDocument", {"chat_id": chat_id, "caption": caption},
              {"document": (f"{stem}.srt", srt.encode("utf-8"), "application/x-subrip")})


def _srt(cues: list[dict]) -> str:
    from ovozlab.subtitles import to_srt

    return to_srt(cues)


def do_clone(chat_id: int, u: dict, msg: dict, media: tuple) -> None:
    f, name, _ = media
    if (f.get("duration") or 0) > 30:
        return send(chat_id, "Yozuv 30 soniyadan oshmasin (5–15 soniya eng yaxshi). Qaytadan yuboring.")
    send(chat_id, "⏳ Ovozingiz o'rganilmoqda…")
    stop = keep_action(chat_id, "typing")
    try:
        data = download(f["file_id"])
        frm = msg.get("from") or {}
        base = frm.get("first_name") or "Mening ovozim"
        meta = json.loads(api("POST", "/clone", fields={"name": f"{base} {len(my_voices(frm)) + 1}"},
                              files={"audio": (name, data, "application/octet-stream")}, who=frm))
    finally:
        stop.set()
    u["voice"], u["awaiting"] = f"id:{meta['id']}", None
    send(chat_id, f"✅ Ovoz tayyor: <b>{esc(meta.get('name', ''))}</b>\n"
                  f"Aniqlangan matn: <i>{esc(meta.get('ref_text', ''))}</i>\n\nEndi matn yuboring — shu ovozda o'qiyman.")


# ------------------------------------------------------------- keyboards
def kb(rows: list[list[tuple[str, str]]]) -> dict:
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in rows]}


def voices_kb(u: dict, who: dict) -> dict:
    mark = lambda key, label: ("✅ " if u["voice"] == key else "") + label  # noqa: E731
    items = [(mark(k, lbl), f"v:{k}") for k, (lbl, _) in PRESETS.items()]
    items += [(mark(f"id:{x['id']}", "🧬 " + x["name"]), f"v:id:{x['id']}") for x in my_voices(who)]
    return kb([items[i:i + 2] for i in range(0, len(items), 2)])


def on_command(chat_id: int, u: dict, cmd: str, args: list[str], who: dict) -> None:
    if cmd == "/start" and args and args[0].startswith("login_"):
        return send(chat_id, "🔐 <b>Saytga kirish</b>\n\nOvozLab saytiga shu Telegram hisobingiz bilan kirmoqchisiz. "
                             "Agar buni o'zingiz so'ramagan bo'lsangiz, tugmani bosmang.",
                    reply_markup=kb([[("✅ Ha, kirish", f"login:{args[0][6:46]}")]]))
    if cmd in ("/start", "/help", "/yordam"):
        send(chat_id, HELP)
        if cmd == "/start":
            try:
                me = account(who)
                if not me["unlimited"]:
                    send(chat_id, f"🎁 Hisobingizda <b>{fmt_n(me['tokens'])}</b> bepul token bor. Balans: /hisob")
            except ApiError:
                pass
    elif cmd in ("/hisob", "/balans", "/balance"):
        send(chat_id, account_text(account(who)),
             reply_markup={"inline_keyboard": [[{"text": "💬 Token olish", "url": f"https://t.me/{CONTACT}"}]]
                           + ([[{"text": "🌐 Saytga kirish", "url": f"{WEB_URL}/app"}]] if WEB_URL.startswith("https://") else [])})
    elif cmd in ADMIN_COMMANDS:
        admin_command(chat_id, cmd, args, who)
    elif cmd == "/ovoz":
        send(chat_id, "Qaysi ovozda o'qiy?", reply_markup=voices_kb(u, who))
    elif cmd == "/kayfiyat":
        rows = [[(("✅ " if u["mood"] == k else "") + v, f"m:{k}")] for k, v in MOODS.items()]
        send(chat_id, "Ohangni tanlang:", reply_markup=kb(rows))
    elif cmd == "/tezlik":
        send(chat_id, "O'qish tezligi:", reply_markup=kb([[(("✅ " if u["speed"] == s else "") + f"{s}×", f"s:{s}")
                                                           for s in SPEEDS]]))
    elif cmd == "/qator":
        send(chat_id, "Subtitrda nechta qator?", reply_markup=kb([[
            (("✅ " if u["lines"] == 1 else "") + "1 qator (Reels)", "l:1"),
            (("✅ " if u["lines"] == 2 else "") + "2 qator", "l:2")]]))
    elif cmd == "/klon":
        u["awaiting"] = "clone"
        send(chat_id, "🎙 <b>Ovozingizni yozib yuboring</b> (5–15 soniya, ovozli xabar).\n\n"
                      "Shovqinsiz joyda, oddiy ohangda gapiring. Masalan, shu matnni o'qing:\n"
                      "<i>Assalomu alaykum! Bugun havo juda yaxshi, do'stlarim bilan bog'da sayr qilishga "
                      "boryapman.</i>\n\nBekor qilish: /bekor")
    elif cmd == "/bekor":
        u["awaiting"] = None
        send(chat_id, "Bekor qilindi.")
    elif cmd == "/ochir":
        mine = my_voices(who)
        if not mine:
            return send(chat_id, "Sizda klonlangan ovoz yo'q. Yaratish: /klon")
        send(chat_id, "Qaysi ovozni o'chiray?", reply_markup=kb([[("🗑 " + x["name"], f"d:{x['id']}")]
                                                                 for x in mine]))
    elif cmd == "/sozlamalar":
        send(chat_id, f"🎙 Ovoz: {voice_label(u, who)}\n🎭 Kayfiyat: {MOODS[u['mood']]}\n"
                      f"⏩ Tezlik: {u['speed']}×\n📝 Subtitr: {u['lines']} qator")
    else:
        send(chat_id, "Bunday buyruq yo'q. /help")


def on_callback(cb: dict) -> None:
    who = cb["from"]
    uid, data = who["id"], cb.get("data") or ""
    msg = cb.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id", uid)
    u = state.user(uid)
    note = "Saqlandi"
    kind, _, val = data.partition(":")
    if kind == "login":
        try:
            api("POST", f"/auth/code/{urllib.parse.quote(val)}/confirm", json_body={}, who=who)
            note = "Saytga kirdingiz — brauzerga qayting"
        except ApiError as exc:
            note = str(exc)[:190]
    elif kind == "v" and (val in PRESETS or any(f"id:{x['id']}" == val for x in my_voices(who))):
        u["voice"] = val
        note = f"Ovoz: {voice_label(u, who)}"
    elif kind == "m" and val in MOODS:
        u["mood"], note = val, f"Kayfiyat: {MOODS[val]}"
    elif kind == "s" and val in SPEEDS:
        u["speed"], note = val, f"Tezlik: {val}×"
    elif kind == "l" and val in ("1", "2"):
        u["lines"], note = int(val), f"Subtitr: {val} qator"
    elif kind == "d":
        try:
            api("DELETE", f"/voices/{urllib.parse.quote(val)}", who=who)
        except ApiError:
            pass
        u["voices"] = [x for x in u["voices"] if x["id"] != val]
        if u["voice"] == f"id:{val}":
            u["voice"] = "auto"
        note = "O'chirildi"
    state.save()
    tg("answerCallbackQuery", callback_query_id=cb["id"], text=note)
    if msg.get("message_id"):
        try:
            tg("editMessageText", chat_id=chat_id, message_id=msg["message_id"], text=f"✅ {note}")
        except Exception:
            pass


def on_message(msg: dict) -> None:
    chat_id = msg["chat"]["id"]
    who = msg.get("from") or {"id": chat_id}
    uid = who.get("id", chat_id)
    u = state.user(uid)
    text = (msg.get("text") or "").strip()
    try:
        if text.startswith("/"):
            parts = text.split()
            return on_command(chat_id, u, parts[0].split("@")[0].lower(), parts[1:], who)
        media = media_of(msg)
        if not text and not media:
            return send(chat_id, "Matn, ovozli xabar, audio yoki video yuboring. /help")
        if not rate_ok(u):
            return send(chat_id, "Bir soatlik limitga yetdingiz, birozdan keyin urinib ko'ring.")
        if media and u["awaiting"] == "clone":
            return do_clone(chat_id, u, msg, media)
        if media:
            return do_stt(chat_id, u, msg, media)
        do_tts(chat_id, u, text, who)
    except ApiError as exc:
        if "Token" in str(exc) or "token" in str(exc):
            return send(chat_id, f"⚠️ {esc(str(exc))}",
                        reply_markup={"inline_keyboard": [[{"text": f"💬 @{CONTACT} ga yozish",
                                                            "url": f"https://t.me/{CONTACT}"}]]})
        send(chat_id, f"⚠️ {esc(str(exc))}")
    except Exception:
        log.exception("Xabarni qayta ishlashda xato")
        send(chat_id, "⚠️ Kutilmagan xato. Birozdan keyin qayta urinib ko'ring.")
    finally:
        state.save()


# ----------------------------------------------------------------- admin
ADMIN_COMMANDS = {"/add", "/settoken", "/vip", "/oddiy", "/block", "/unblock", "/user", "/stat", "/admin"}
ADMIN_HELP = (
    "<b>Admin buyruqlari</b>\n"
    "/add &lt;id&gt; &lt;soni&gt; — token qo'shish (manfiy — ayirish)\n"
    "/settoken &lt;id&gt; &lt;soni&gt; — balansni o'rnatish\n"
    "/vip &lt;id&gt; — cheksiz (VIP)\n"
    "/oddiy &lt;id&gt; — oddiy tarifga qaytarish\n"
    "/block &lt;id&gt;, /unblock &lt;id&gt;\n"
    "/user &lt;id yoki @username&gt; — ma'lumot\n"
    "/stat — statistika\n\n"
    "To'liq boshqaruv saytdagi Admin panelida."
)


def _target(args: list[str], who: dict) -> int | None:
    if not args:
        return None
    a = args[0].lstrip("@")
    if a.lstrip("-").isdigit():
        return int(a)
    found = json.loads(api("GET", f"/admin/users?q={urllib.parse.quote(a)}&limit=5", who=who))
    exact = [x for x in found if (x.get("username") or "").lower() == a.lower()]
    return (exact or found or [{}])[0].get("id")


def admin_command(chat_id: int, cmd: str, args: list[str], who: dict) -> None:
    try:
        if cmd == "/admin":
            return send(chat_id, ADMIN_HELP + (f"\n{WEB_URL}/app" if WEB_URL else ""))
        if cmd == "/stat":
            s = json.loads(api("GET", "/admin/stats", who=who))
            k = s.get("by_kind_24h", {})
            return send(chat_id, f"📊 <b>Statistika</b>\nFoydalanuvchilar: {s['users']} (VIP {s['vip']}, blok {s['blocked']})\n"
                                 f"24 soatda faol: {s['active_24h']}, yangi: {s['new_24h']}\n"
                                 f"24 soatda so'rovlar: {s['requests_24h']} (TTS {k.get('tts', 0)}, STT {k.get('stt', 0)}, "
                                 f"klon {k.get('clone', 0)})\nSarflangan token (24 s): {fmt_n(s['spent_24h'])}")
        uid = _target(args, who)
        if uid is None:
            return send(chat_id, "Foydalanuvchi topilmadi.\n\n" + ADMIN_HELP)
        body = None
        if cmd in ("/add", "/settoken"):
            if len(args) < 2 or not args[1].lstrip("-").isdigit():
                return send(chat_id, f"Masalan: {cmd} {uid} 5000")
            body = {"add": int(args[1])} if cmd == "/add" else {"tokens": int(args[1])}
        elif cmd == "/vip":
            body = {"role": "vip"}
        elif cmd == "/oddiy":
            body = {"role": "user"}
        elif cmd in ("/block", "/unblock"):
            body = {"blocked": cmd == "/block"}
        if body is not None:
            u = json.loads(api("PATCH", f"/admin/users/{uid}", json_body=body, who=who))
        else:
            u = json.loads(api("GET", f"/admin/users/{uid}", who=who))
        bal = "♾" if u["unlimited"] else fmt_n(u["tokens"])
        uname = f" @{esc(u['username'])}" if u.get("username") else ""
        send(chat_id, f"✅ <b>{esc(u['name'])}</b>{uname} · <code>{u['id']}</code>\n"
                      f"Tarif: {u['role']} · Balans: {bal} · Sarflangan: {fmt_n(u['used'])}"
                      + (" · 🚫 bloklangan" if u["blocked"] else ""))
    except ApiError as exc:
        send(chat_id, f"⚠️ {esc(str(exc))}")


def migrate_voice_owners() -> None:
    """Oldin botda yaratilgan klonlarni egasiga biriktirish (sayt bilan umumiy bo'lishi uchun)."""
    n = 0
    for uid, u in list(state.data.get("users", {}).items()):
        for v in u.get("voices") or []:
            try:
                api("POST", "/internal/voice-owner", json_body={"voice_id": v["id"], "owner": int(uid)}, timeout=30)
                n += 1
            except ApiError:
                pass
        u["voices"] = []
    if n:
        log.info("%d ta eski ovoz egasiga biriktirildi", n)
        state.save()


# ------------------------------------------------------------------ loop
COMMANDS = [
    ("ovoz", "Ovozni tanlash"), ("kayfiyat", "Ohang: quvnoq, jiddiy…"), ("tezlik", "O'qish tezligi"),
    ("klon", "O'z ovozingizni yaratish"), ("qator", "Subtitr: 1 yoki 2 qator"), ("ochir", "Klon ovozni o'chirish"),
    ("sozlamalar", "Joriy sozlamalar"), ("hisob", "Token balansi va sayt"), ("help", "Yordam"),
]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN berilmagan")
    me = tg("getMe")["result"]
    log.info("Bot ishga tushdi: @%s, API: %s", me["username"], API_URL)
    try:
        tg("setMyCommands", commands=[{"command": c, "description": d} for c, d in COMMANDS])
        tg("setMyDescription", description="O'zbekcha matndan ovoz, ovozdan matn va video uchun SRT subtitr. "
                                           "Ovozingizni klonlash ham mumkin.")
    except Exception:
        log.warning("Buyruqlar ro'yxatini o'rnatib bo'lmadi")

    threading.Thread(target=_safe, args=(migrate_voice_owners,), daemon=True).start()
    pool = ThreadPoolExecutor(max_workers=6)
    offset = state.data.get("offset", 0)
    backoff = 1
    while True:
        try:
            res = tg("getUpdates", http_timeout=90, timeout=60, offset=offset, allowed_updates=["message", "callback_query"])
            backoff = 1
        except Exception as exc:
            log.warning("getUpdates xatosi: %s", exc)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
            continue
        for upd in res.get("result", []):
            offset = upd["update_id"] + 1
            if "message" in upd:
                pool.submit(on_message, upd["message"])
            elif "callback_query" in upd:
                pool.submit(_safe, on_callback, upd["callback_query"])
        state.data["offset"] = offset
        state.save()


def _safe(fn, *args) -> None:
    try:
        fn(*args)
    except Exception:
        log.exception("Callback xatosi")


if __name__ == "__main__":
    main()
