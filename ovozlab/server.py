"""OvozLab FastAPI serveri.

Ishga tushirish (ilova oynasisiz):  uv run uvicorn ovozlab.server:app --port 8000
Ilova oynasi bilan:                 uv run python -m ovozlab
"""

from __future__ import annotations

import logging
import os
import secrets
import sys
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import quote, unquote

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Security, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ovozlab import __version__, accounts, config, firstrun, history, subtitles, voices
from ovozlab.audio import decode
from ovozlab.engine import encode_audio, engine

logger = logging.getLogger("ovozlab")

STATIC_DIR = Path(__file__).parent / "static"
MIN_REF_SECONDS = 1.5
# OmniVoice reference'ni kontekst sifatida ishlatadi (o'qitmaydi): 5–15 s eng yaxshi, >20 s sifatni pasaytiradi.
MAX_REF_SECONDS = 30.0
STT_MAX_SECONDS = 60 * 60
STT_MAX_MB = 500
MEDIA = {"wav": "audio/wav", "mp3": "audio/mpeg"}


def start_model_load() -> None:
    """Model bir necha GB — serverni bloklamaslik uchun fonda yuklaymiz."""
    if engine.state in ("loading", "ready"):
        return

    def _run():
        try:
            engine.load()
        except Exception:
            pass  # xato engine.error da saqlanadi

    threading.Thread(target=_run, name="model-load", daemon=True).start()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    config.apply_model_env()
    config.VOICES_DIR.mkdir(parents=True, exist_ok=True)
    if firstrun.is_ready_installed() and os.environ.get("OVOZLAB_PRELOAD", "1") != "0":
        start_model_load()
    yield


# ------------------------------------------------------------- auth
# OVOZLAB_API_KEY — "master" kalit (Telegram bot va ichki xizmatlar uchun).
# OVOZLAB_SERVER=1 — server rejimi: ish stoli ilovasiga xos /api/* yopiladi va hisoblar yoqiladi:
#   - saytdan Telegram orqali kirish (cookie sessiya),
#   - foydalanuvchining shaxsiy API kaliti ("olk_..."),
#   - bot: master kalit + "X-OvozLab-User: <telegram id>" — shu foydalanuvchi nomidan.
# Har bir so'rov foydalanuvchi balansidagi tokendan yechiladi (VIP/admin — cheksiz).
API_KEY = os.environ.get("OVOZLAB_API_KEY", "").strip() or None
SERVER_MODE = os.environ.get("OVOZLAB_SERVER", "0") not in ("0", "", "false", "no")
ACCOUNTS = SERVER_MODE or os.environ.get("OVOZLAB_ACCOUNTS", "0") not in ("0", "", "false", "no")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
SESSION_COOKIE = "ovozlab_session"
_PUBLIC_PATHS = {"/", "/app", "/health", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}

_bearer = HTTPBearer(auto_error=False, description="OvozLab API key")
_header_key = APIKeyHeader(name="X-API-Key", auto_error=False, description="OvozLab API key")


def _same(a: str, b: str) -> bool:
    return secrets.compare_digest(a.encode(), b.encode())


def require_api_key(
    request: Request,
    bearer: Optional[HTTPAuthorizationCredentials] = Security(_bearer),
    header_key: Optional[str] = Security(_header_key),
) -> None:
    path = request.url.path
    request.state.user, request.state.source = None, "local"
    if SERVER_MODE and path.startswith("/api/"):
        raise HTTPException(404, "Server rejimida mavjud emas")
    public = path in _PUBLIC_PATHS or path.startswith("/auth/")
    given = header_key or (bearer.credentials if bearer else None)
    if not ACCOUNTS:  # ish stoli ilovasi: bitta (ixtiyoriy) kalit
        if API_KEY is None or public:
            return
        if not given or not _same(given, API_KEY):
            raise HTTPException(401, "API key noto'g'ri yoki berilmagan", headers={"WWW-Authenticate": "Bearer"})
        return

    user, source = None, None
    if given:
        if API_KEY and _same(given, API_KEY):
            uid = (request.headers.get("X-OvozLab-User") or "").strip()
            if not uid.isdigit():
                request.state.source = "service"  # ichki xizmat — cheklovsiz
                return
            profile = {k: unquote(request.headers.get(f"X-OvozLab-{h}", "")) for k, h in (
                ("first_name", "First-Name"), ("last_name", "Last-Name"), ("username", "Username"))}
            user, source = accounts.ensure(int(uid), profile), "bot"
        else:
            user, source = accounts.user_by_key(given), "api"
            if user is None:
                raise HTTPException(401, "API kalit noto'g'ri yoki o'chirilgan", headers={"WWW-Authenticate": "Bearer"})
    elif request.cookies.get(SESSION_COOKIE):
        user, source = accounts.user_by_session(request.cookies[SESSION_COOKIE]), "web"
    if user is None:
        if public:
            return
        raise HTTPException(401, "Kirish kerak: saytda Telegram orqali kiring yoki API kalit bering",
                            headers={"WWW-Authenticate": "Bearer"})
    if user["blocked"]:
        raise HTTPException(403, f"Hisobingiz bloklangan. Savollar uchun: @{accounts.CONTACT}")
    request.state.user, request.state.source = user, source


app = FastAPI(
    title="OvozLab API",
    version=__version__,
    description="O'zbek tili uchun ochiq kodli matndan nutq (TTS) va ovoz klonlash API.\n\n"
    "Server rejimida: saytdagi hisobingizdan API kalit oling va `Authorization: Bearer olk_...` "
    "sarlavhasi bilan yuboring. Har bir so'rov hisobingizdagi tokendan yechiladi.",
    lifespan=lifespan,
    dependencies=[Depends(require_api_key)],
)


# --------------------------------------------------------------- accounting
def _user(request: Request) -> Optional[dict]:
    return getattr(request.state, "user", None)


def _owner(request: Request) -> Optional[int]:
    u = _user(request)
    return u["id"] if u else None


def _visible(request: Request, meta: dict) -> bool:
    """Ovoz/tarix yozuvi shu foydalanuvchiga tegishlimi."""
    if not ACCOUNTS or getattr(request.state, "source", "") == "service":
        return True
    u = _user(request)
    if u is None:
        return False
    owner = meta.get("owner")
    return owner == u["id"] or (owner is None and u["role"] == "admin")


def _need(request: Request, amount: int) -> None:
    u = _user(request)
    if u is None:
        return
    try:
        accounts.check(accounts.get(u["id"]), amount)
    except accounts.NotEnoughTokens as exc:
        raise HTTPException(402, exc.message()) from exc


def _charge(request: Request, kind: str, amount: int, detail: str = "") -> dict:
    """Tokenni yechib, javobga qo'shiladigan sarlavhalarni qaytaradi."""
    u = _user(request)
    if u is None:
        return {}
    left = accounts.charge(accounts.get(u["id"]) or u, kind, amount, request.state.source, detail)
    return {"X-Tokens-Used": str(amount), "X-Tokens-Left": "unlimited" if accounts.is_unlimited(u) else str(left)}


def _voice_meta(request: Request, voice_id: str) -> dict:
    try:
        meta = voices.get_meta(voice_id)
    except KeyError:
        raise HTTPException(404, "Ovoz topilmadi")
    if not _visible(request, meta):
        raise HTTPException(404, "Ovoz topilmadi")
    return meta


# ------------------------------------------------------------------ helpers
def _language(value: Optional[str]) -> str:
    try:
        return config.resolve_language(value)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _check_text(text: str) -> str:
    text = (text or "").strip()
    if not text:
        raise HTTPException(400, "Matn bo'sh bo'lmasligi kerak")
    if len(text) > config.MAX_TEXT_CHARS:
        raise HTTPException(400, f"Matn juda uzun (maksimum {config.MAX_TEXT_CHARS} belgi)")
    return text


def _require_model() -> None:
    if not firstrun.is_ready_installed():
        raise HTTPException(409, "OvozLab hali sozlanmagan. Avval o'rnatish ustasini yakunlang")
    if engine.state == "error":
        raise HTTPException(503, f"Model yuklanmagan: {engine.error}")


async def _read_upload(upload: UploadFile, sample_rate: int, max_seconds: float = MAX_REF_SECONDS,
                       max_mb: int = config.MAX_UPLOAD_MB):
    data = await upload.read()
    if not data:
        raise HTTPException(400, "Audio fayl bo'sh")
    if len(data) > max_mb * 1024 * 1024:
        raise HTTPException(413, f"Audio fayl juda katta (maksimum {max_mb} MB)")
    try:
        samples = await run_in_threadpool(decode, data, sample_rate)
    except Exception as exc:
        raise HTTPException(400, f"Audio faylni o'qib bo'lmadi: {exc}") from exc
    duration = len(samples) / sample_rate
    if duration < MIN_REF_SECONDS:
        raise HTTPException(400, f"Audio juda qisqa ({duration:.1f}s). Kamida 3 soniya kerak")
    if duration > max_seconds:
        hint = "5–15 soniya tavsiya etiladi" if max_seconds <= MAX_REF_SECONDS else f"maksimum {max_seconds / 60:.0f} daqiqa"
        raise HTTPException(400, f"Audio juda uzun ({duration:.1f}s). {hint}")
    return samples, float(duration)


async def _save_reference(upload: UploadFile, dest: Path):
    import soundfile as sf

    samples, duration = await _read_upload(upload, engine.sample_rate)
    sf.write(str(dest), samples, engine.sample_rate, subtype="PCM_16")
    return samples, duration


async def _auto_ref_text(ref_text: Optional[str], samples) -> tuple[str, bool]:
    ref_text = (ref_text or "").strip()
    if ref_text:
        return ref_text, False
    try:
        text = await run_in_threadpool(engine.transcribe, samples, engine.sample_rate)
    except Exception as exc:
        logger.exception("Whisper xatosi")
        raise HTTPException(500, f"Audioni matnga o'girib bo'lmadi: {exc}. Matnni qo'lda yozing") from exc
    if not text:
        raise HTTPException(400, "Audioda nutq topilmadi. Matnni qo'lda yozing yoki boshqa yozuv yuklang")
    return text, True


def _audio_response(samples, fmt: str, filename: str, extra_headers: Optional[dict] = None) -> Response:
    body = encode_audio(samples, engine.sample_rate, fmt)
    headers = {
        "Content-Disposition": f'inline; filename="{filename}.{fmt}"',
        "X-Audio-Duration": f"{len(samples) / engine.sample_rate:.2f}",
        "Access-Control-Expose-Headers": "X-Audio-Duration, X-History-Id, X-Mood-Source, X-Voice-Used, X-Tokens-Used, X-Tokens-Left",
    }
    headers.update(extra_headers or {})
    return Response(content=body, media_type=MEDIA[fmt], headers=headers)


# ------------------------------------------------------------------- schemas
class TTSRequest(BaseModel):
    text: str = Field(..., description="O'qiladigan matn (o'zbek tilida)")
    voice_id: Optional[str] = Field(None, description="/clone orqali yaratilgan ovoz ID si. Bo'sh — model o'zi tanlaydi")
    language: Optional[str] = Field("uz", description="uz | uzb | uzn")
    format: Literal["wav", "mp3"] = "wav"
    speed: Optional[float] = Field(None, ge=0.5, le=2.0, description="Tezlik: 1.0 = oddiy")
    num_step: Optional[int] = Field(None, ge=4, le=64, description="Sifat/tezlik: 16 tez, 32 standart")
    seed: Optional[int] = Field(None, description="Bir xil natija olish uchun")
    instruct: Optional[str] = Field(
        None,
        description="Ovoz uslubi (vergul bilan): male/female, child/teenager/young adult/middle-aged/elderly, "
        "very low pitch ... very high pitch, whisper. Asosan voice_id siz rejimda ishlaydi",
    )
    mood: Optional[Literal["neutral", "happy", "sad", "serious", "story"]] = Field(
        None, description="Kayfiyat. Ovozning shu kayfiyatdagi profili bo'lsa o'sha ishlatiladi, aks holda taxminiy "
        "(tezlik + ohang)")
    save_history: bool = Field(True, description="Natijani tarixga saqlash")


class SetupConfig(BaseModel):
    backend: Optional[Literal["xpu", "cuda", "cpu"]] = None
    models_dir: Optional[str] = None
    asr_enabled: Optional[bool] = None


class SettingsUpdate(BaseModel):
    asr_enabled: Optional[bool] = None
    default_num_step: Optional[int] = Field(None, ge=4, le=64)


# ------------------------------------------------------------------- health
@app.get("/health")
def health():
    return {
        "status": engine.state,
        "loading": engine.load_progress(),
        "error": engine.error,
        "setup_complete": firstrun.is_ready_installed(),
        "model": config.TTS_MODEL,
        "device": engine.device,
        "device_name": engine.device_name,
        "dtype": engine.dtype,
        "load_seconds": engine.load_seconds,
        "default_language": config.DEFAULT_LANGUAGE,
        "version": __version__,
        "server_mode": SERVER_MODE,
        "accounts": ACCOUNTS,
    }


# -------------------------------------------------------------------- setup
@app.get("/api/setup/status")
def setup_status():
    return firstrun.status()


@app.post("/api/setup/config")
def setup_config(body: SetupConfig):
    try:
        return firstrun.configure(body.backend, body.models_dir, body.asr_enabled)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class SetupStart(BaseModel):
    only: Optional[list[Literal["runtime", "tts", "asr"]]] = None


@app.post("/api/setup/start")
def setup_start(body: Optional[SetupStart] = None):
    try:
        firstrun.job.start(only=body.only if body else None)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return firstrun.job.progress()


@app.get("/api/setup/progress")
def setup_progress():
    p = firstrun.job.progress()
    if p["state"] == "done" and not p["restart_required"]:
        start_model_load()
    return p


@app.post("/api/setup/cancel")
def setup_cancel():
    firstrun.job.cancel()
    return firstrun.job.progress()


# ------------------------------------------------------------------- system
@app.get("/api/system")
def system_info():
    mdir = config.models_dir()
    return {
        "version": __version__,
        "home": str(config.HOME),
        "app_dir": str(config.ROOT_DIR),
        "models_dir": str(mdir),
        "data_dir": str(config.DATA_DIR),
        "backend": config.settings.get("backend"),
        "installed_backend": firstrun.installed_backend(),
        "device": engine.device,
        "device_name": engine.device_name,
        "engine_state": engine.state,
        "models": [{**m, "present": firstrun.model_present(mdir, m)} for m in firstrun.MODELS],
        "free_bytes": firstrun.free_bytes(mdir),
        "settings": config.settings.as_dict(),
        "python": sys.version.split()[0],
    }


@app.get("/api/system/sizes")
def system_sizes():
    return {
        "models_bytes": firstrun.dir_size(config.models_dir()),
        "data_bytes": firstrun.dir_size(config.DATA_DIR),
        "history_bytes": firstrun.dir_size(config.HISTORY_DIR),
    }


@app.post("/api/settings")
def update_settings(body: SettingsUpdate):
    values = {k: v for k, v in body.model_dump().items() if v is not None}
    return config.settings.update(**values)


@app.post("/api/system/open/{target}")
def open_folder(target: Literal["models", "data", "home", "app"]):
    path = {"models": config.models_dir(), "data": config.DATA_DIR, "home": config.HOME, "app": config.ROOT_DIR}[target]
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 — faqat lokal ilova uchun
    return {"opened": str(path)}


# ------------------------------------------------------------------- voices
@app.get("/voices")
def list_voices(request: Request):
    return [v for v in voices.list_all() if _visible(request, v)]


@app.get("/voices/{voice_id}")
def get_voice(request: Request, voice_id: str):
    return _voice_meta(request, voice_id)


@app.get("/voices/{voice_id}/reference")
def get_voice_reference(request: Request, voice_id: str):
    _voice_meta(request, voice_id)
    try:
        return FileResponse(voices.reference_path(voice_id), media_type="audio/wav")
    except KeyError:
        raise HTTPException(404, "Ovoz topilmadi")


class VoiceUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)


@app.patch("/voices/{voice_id}")
def update_voice(request: Request, voice_id: str, body: VoiceUpdate):
    """Ovoz nomini o'zgartirish."""
    _voice_meta(request, voice_id)
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Nom bo'sh bo'lmasligi kerak")
    try:
        return voices.rename(voice_id, name)
    except KeyError:
        raise HTTPException(404, "Ovoz topilmadi")


@app.delete("/voices/{voice_id}")
def delete_voice(request: Request, voice_id: str):
    _voice_meta(request, voice_id)
    try:
        voices.delete(voice_id)
    except KeyError:
        raise HTTPException(404, "Ovoz topilmadi")
    return {"deleted": voice_id}


@app.post("/transcribe")
async def transcribe(request: Request, audio: UploadFile = File(..., description="Audio fayl, 30 soniyagacha")):
    """Audioni Whisper bilan o'zbekcha matnga o'giradi."""
    _require_model()
    samples, duration = await _read_upload(audio, 16000)
    cost = accounts.cost_stt(duration)
    await run_in_threadpool(_need, request, cost)
    try:
        text = await run_in_threadpool(engine.transcribe, samples, 16000)
    except Exception as exc:
        logger.exception("Whisper xatosi")
        raise HTTPException(500, f"Audioni matnga o'girib bo'lmadi: {exc}") from exc
    tokens = await run_in_threadpool(_charge, request, "stt", cost, f"{duration:.0f} s")
    return JSONResponse({"text": text, "duration_s": round(duration, 2)}, headers=tokens)


@app.post("/stt")
async def speech_to_text(
    request: Request,
    audio: UploadFile = File(..., description="Audio yoki video fayl, 60 daqiqagacha"),
    format: Literal["json", "srt", "vtt", "txt"] = Query(
        "json", description="json — matn, so'zlar va subtitr qatorlari; srt/vtt — tayyor subtitr fayli; txt — matn"),
    max_chars: int = Query(42, ge=16, le=80, description="Subtitrda bir qatordagi maksimal belgi"),
    max_lines: int = Query(2, ge=1, le=3, description="Bitta subtitrdagi qatorlar soni"),
):
    """Nutqdan matn: istalgan uzunlikdagi o'zbekcha audioni matnga o'giradi.

    Natija vaqt belgilari bilan; ``format=srt`` yoki ``vtt`` bo'lsa CapCut, Premiere, YouTube uchun tayyor subtitr.
    Narx: har soniya audio uchun token.
    """
    _require_model()
    samples, duration = await _read_upload(audio, 16000, max_seconds=STT_MAX_SECONDS, max_mb=STT_MAX_MB)
    cost = accounts.cost_stt(duration)
    await run_in_threadpool(_need, request, cost)
    t0 = time.time()
    try:
        result = await run_in_threadpool(engine.transcribe_segments, samples, 16000)
    except Exception as exc:
        logger.exception("STT xatosi")
        raise HTTPException(500, f"Matnga o'girib bo'lmadi: {exc}") from exc
    tokens = await run_in_threadpool(_charge, request, "stt", cost, f"{audio.filename or 'audio'} · {duration:.0f} s")
    rules = subtitles.CueRules(max_chars=max_chars, max_lines=max_lines)
    if (max_chars, max_lines) != (42, 2):
        result["cues"] = subtitles.build_cues(result["words"], rules)
    stem = Path(audio.filename or "ovozlab").stem or "ovozlab"
    if format in ("srt", "vtt", "txt"):
        body = {"srt": subtitles.to_srt, "vtt": subtitles.to_vtt}.get(format, lambda _c: result["text"])(result["cues"])
        media = {"srt": "application/x-subrip", "vtt": "text/vtt", "txt": "text/plain"}[format]
        disposition = f"attachment; filename*=UTF-8''{quote(stem)}.{format}"
        return Response(body, media_type=f"{media}; charset=utf-8",
                        headers={"Content-Disposition": disposition, **tokens})
    return JSONResponse({**result, "duration_s": round(duration, 2), "elapsed_s": round(time.time() - t0, 1)},
                        headers=tokens)


@app.post("/clone")
async def clone_voice(
    request: Request,
    audio: UploadFile = File(..., description="Reference audio (WAV/MP3/FLAC/OGG/M4A/WebM), 3–10 soniya"),
    ref_text: Optional[str] = Form(None, description="Audioda aytilgan matn. Bo'sh bo'lsa Whisper aniqlaydi"),
    name: str = Form("Mening ovozim"),
    language: str = Form("uz"),
    mood: Optional[Literal["neutral", "happy", "sad", "serious", "story"]] = Form(None, description="Yozuv kayfiyati"),
):
    """Reference audio asosida yangi ovoz profilini yaratadi va saqlaydi."""
    _require_model()
    await run_in_threadpool(_need, request, accounts.COST_CLONE)
    lang = _language(language)
    name = (name or "").strip()[:80] or "Mening ovozim"

    voice_id = voices.new_id(name)
    vdir = config.VOICES_DIR / voice_id
    vdir.mkdir(parents=True, exist_ok=True)
    ref_wav = vdir / "reference.wav"
    try:
        samples, duration = await _save_reference(audio, ref_wav)
        ref_text, auto = await _auto_ref_text(ref_text, samples)
        prompt = await run_in_threadpool(engine.create_voice_prompt, str(ref_wav), ref_text)
        meta = voices.save(voice_id, name, ref_text, lang, prompt, ref_wav, duration, mood=mood,
                           owner=_owner(request))
        meta["ref_text_auto"] = auto
    except HTTPException:
        voices.delete(voice_id)
        raise
    except ValueError as exc:
        voices.delete(voice_id)
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        voices.delete(voice_id)
        logger.exception("Klonlashda xato")
        raise HTTPException(500, f"Klonlashda xato: {exc}") from exc
    tokens = await run_in_threadpool(_charge, request, "clone", accounts.COST_CLONE, name)
    return JSONResponse(meta, headers=tokens)


# ---------------------------------------------------------------------- tts
@app.post("/tts")
async def tts(request: Request, req: TTSRequest):
    """Matndan audio yaratadi. ``voice_id`` berilsa — klonlangan ovozda. Narx: har belgi uchun token."""
    _require_model()
    text = _check_text(req.text)
    lang = _language(req.language)
    cost = accounts.cost_tts(text)
    await run_in_threadpool(_need, request, cost)
    prompt, voice_name, voice_used = None, None, req.voice_id
    mood = req.mood if req.mood and req.mood != "neutral" else None
    mood_source = None
    if req.voice_id:
        _voice_meta(request, req.voice_id)
        try:
            if mood:
                sib = await run_in_threadpool(voices.find_mood_sibling, req.voice_id, mood)
                if sib:
                    voice_used, mood_source, mood = sib["id"], "profile", None  # haqiqiy kayfiyat
            prompt = await run_in_threadpool(voices.load_prompt, voice_used)
            voice_name = voices.get_meta(voice_used).get("name")
        except KeyError:
            raise HTTPException(404, "Ovoz topilmadi")
    if mood:
        mood_source = "approx"
    try:
        samples = await run_in_threadpool(
            engine.synthesize, text, lang, prompt, None, None, req.speed, req.num_step, req.seed, req.instruct, mood
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("TTS xatosi")
        raise HTTPException(500, f"TTS xatosi: {exc}") from exc
    headers = {"X-Mood-Source": mood_source or "none", "X-Voice-Used": voice_used or ""}
    headers.update(await run_in_threadpool(_charge, request, "tts", cost, text[:80]))
    if req.save_history:
        rec = await run_in_threadpool(history.add, samples, engine.sample_rate, {
            "text": text, "voice_id": req.voice_id, "voice_name": voice_name or "Avtomatik",
            "instruct": req.instruct, "speed": req.speed, "num_step": req.num_step, "seed": req.seed,
            "mood": req.mood, "mood_source": mood_source, "owner": _owner(request),
        })
        headers["X-History-Id"] = rec["id"]
    return _audio_response(samples, req.format, req.voice_id or "ovozlab", headers)


@app.post("/tts/instant")
async def tts_instant(
    request: Request,
    text: str = Form(...),
    audio: UploadFile = File(..., description="Reference audio, 3–10 soniya"),
    ref_text: Optional[str] = Form(None, description="Bo'sh bo'lsa Whisper aniqlaydi"),
    language: str = Form("uz"),
    format: Literal["wav", "mp3"] = Form("wav"),
    speed: Optional[float] = Form(None),
    num_step: Optional[int] = Form(None),
    seed: Optional[int] = Form(None),
):
    """Profil saqlamasdan, bir martalik: reference audio + matn -> audio."""
    _require_model()
    text = _check_text(text)
    lang = _language(language)
    cost = accounts.cost_tts(text)
    await run_in_threadpool(_need, request, cost)
    with tempfile.TemporaryDirectory() as tmp:
        ref_wav = Path(tmp) / "ref.wav"
        ref_samples, _ = await _save_reference(audio, ref_wav)
        ref_text, _ = await _auto_ref_text(ref_text, ref_samples)
        try:
            samples = await run_in_threadpool(
                engine.synthesize, text, lang, None, str(ref_wav), ref_text, speed, num_step, seed
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            logger.exception("TTS xatosi")
            raise HTTPException(500, f"TTS xatosi: {exc}") from exc
    tokens = await run_in_threadpool(_charge, request, "tts", cost, text[:80])
    return _audio_response(samples, format, "instant", tokens)


# ------------------------------------------------------------------ history
def _history_item(request: Request, item_id: str) -> dict:
    try:
        rec = history.get(item_id)
    except KeyError:
        raise HTTPException(404, "Topilmadi")
    if not _visible(request, rec):
        raise HTTPException(404, "Topilmadi")
    return rec


@app.get("/history")
def list_history(request: Request, limit: int = 100):
    limit = min(max(limit, 1), 500)
    return [h for h in history.list_all(limit=10_000) if _visible(request, h)][:limit]


@app.get("/history/{item_id}/audio")
def history_audio(request: Request, item_id: str, format: Literal["wav", "mp3"] = "wav"):
    _history_item(request, item_id)
    try:
        path = history.audio_path(item_id)
    except KeyError:
        raise HTTPException(404, "Topilmadi")
    if format == "wav":
        return FileResponse(path, media_type="audio/wav", filename=f"ovozlab-{item_id}.wav")
    import soundfile as sf

    samples, sr = sf.read(str(path), dtype="float32")
    return Response(encode_audio(samples, sr, "mp3"), media_type="audio/mpeg",
                    headers={"Content-Disposition": f'attachment; filename="ovozlab-{item_id}.mp3"'})


@app.delete("/history/{item_id}")
def delete_history(request: Request, item_id: str):
    _history_item(request, item_id)
    try:
        history.delete(item_id)
    except KeyError:
        raise HTTPException(404, "Topilmadi")
    return {"deleted": item_id}


@app.delete("/history")
def clear_history(request: Request):
    if not ACCOUNTS:
        return {"deleted": history.clear()}
    n = 0
    for h in history.list_all(limit=10_000):
        if h.get("owner") is not None and h.get("owner") == _owner(request):
            history.delete(h["id"])
            n += 1
    return {"deleted": n}


# ---------------------------------------------------------- telegram login
_bot_username: Optional[str] = os.environ.get("TELEGRAM_BOT_USERNAME", "").strip().lstrip("@") or None
_login_codes: dict[str, dict] = {}
_codes_lock = threading.Lock()
LOGIN_CODE_TTL = 600


def bot_username() -> Optional[str]:
    global _bot_username
    if _bot_username or not BOT_TOKEN:
        return _bot_username
    import json as _json
    import urllib.request

    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=10) as r:
            _bot_username = _json.loads(r.read())["result"]["username"]
    except Exception as exc:
        logger.warning("Bot nomini olib bo'lmadi: %s", exc)
    return _bot_username


def _me(user: dict) -> dict:
    return {**accounts.public(accounts.get(user["id"]) or user), "prices": accounts.prices()}


def _session_response(request: Request, user: dict) -> JSONResponse:
    resp = JSONResponse(_me(user))
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    resp.set_cookie(SESSION_COOKIE, accounts.make_session(user["id"]), max_age=accounts.SESSION_DAYS * 86400,
                    httponly=True, samesite="lax", secure=secure, path="/")
    return resp


@app.get("/auth/config", tags=["account"])
async def auth_config():
    """Kirish sahifasi uchun: bot nomi, narxlar, aloqa."""
    name = await run_in_threadpool(bot_username) if ACCOUNTS else None
    return {"accounts": ACCOUNTS, "bot_username": name, "widget": bool(BOT_TOKEN and name),
            "prices": accounts.prices() if ACCOUNTS else None}


@app.post("/auth/telegram", tags=["account"])
def auth_telegram(request: Request, data: dict):
    """Telegram Login Widget ma'lumoti bilan kirish (https://core.telegram.org/widgets/login)."""
    if not (ACCOUNTS and BOT_TOKEN):
        raise HTTPException(404, "Telegram orqali kirish sozlanmagan")
    try:
        d = accounts.verify_telegram(data, BOT_TOKEN)
    except ValueError as exc:
        raise HTTPException(401, str(exc)) from exc
    user = accounts.ensure(int(d["id"]), d)
    if user["blocked"]:
        raise HTTPException(403, f"Hisobingiz bloklangan. Savollar uchun: @{accounts.CONTACT}")
    return _session_response(request, user)


@app.post("/auth/code", tags=["account"])
async def auth_code_new():
    """Bot orqali kirish: sayt kod oladi, foydalanuvchi botda tasdiqlaydi, sayt so'rab turadi."""
    if not ACCOUNTS:
        raise HTTPException(404, "Hisoblar yoqilmagan")
    name = await run_in_threadpool(bot_username)
    if not name:
        raise HTTPException(503, "Telegram bot sozlanmagan")
    code = secrets.token_hex(12)
    now = time.time()
    with _codes_lock:
        for k in [k for k, v in _login_codes.items() if now - v["t"] > LOGIN_CODE_TTL]:
            _login_codes.pop(k, None)
        _login_codes[code] = {"t": now, "user": None}
    return {"code": code, "url": f"https://t.me/{name}?start=login_{code}", "ttl": LOGIN_CODE_TTL}


@app.get("/auth/code/{code}", tags=["account"])
def auth_code_poll(request: Request, code: str):
    with _codes_lock:
        item = _login_codes.get(code)
        if not item or time.time() - item["t"] > LOGIN_CODE_TTL:
            _login_codes.pop(code, None)
            raise HTTPException(410, "Kod eskirgan, qaytadan urinib ko'ring")
        if item["user"] is None:
            return {"status": "pending"}
        _login_codes.pop(code, None)
    user = accounts.get(item["user"])
    if not user or user["blocked"]:
        raise HTTPException(403, "Hisob bloklangan")
    return _session_response(request, user)


@app.post("/auth/code/{code}/confirm", tags=["account"], include_in_schema=False)
def auth_code_confirm(request: Request, code: str):
    """Faqat bot uchun (master kalit + X-OvozLab-User)."""
    if request.state.source != "bot":
        raise HTTPException(403, "Faqat Telegram bot tasdiqlay oladi")
    with _codes_lock:
        item = _login_codes.get(code)
        if not item or time.time() - item["t"] > LOGIN_CODE_TTL or item["user"] is not None:
            raise HTTPException(410, "Kod eskirgan yoki ishlatilgan. Saytda qaytadan bosing")
        item["user"] = request.state.user["id"]
    return {"ok": True}


@app.post("/auth/logout", tags=["account"])
def auth_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


# ------------------------------------------------------------------ account
def _require_user(request: Request) -> dict:
    u = _user(request)
    if u is None:
        raise HTTPException(401, "Kirish kerak")
    return u


@app.get("/account/me", tags=["account"])
def account_me(request: Request):
    """Hisob: balans, rol, narxlar."""
    return _me(_require_user(request))


@app.get("/account/usage", tags=["account"])
def account_usage(request: Request, limit: int = 50):
    return accounts.usage(_require_user(request)["id"], min(max(limit, 1), 500))


class KeyCreate(BaseModel):
    name: str = Field("API kalit", max_length=60)


@app.get("/account/keys", tags=["account"])
def account_keys(request: Request):
    return accounts.list_keys(_require_user(request)["id"])


@app.post("/account/keys", tags=["account"])
def account_key_create(request: Request, body: KeyCreate):
    """Yangi API kalit. To'liq kalit faqat bir marta ko'rsatiladi."""
    if request.state.source == "api":
        raise HTTPException(403, "API kalit bilan yangi kalit yaratib bo'lmaydi")
    try:
        return accounts.create_key(_require_user(request)["id"], body.name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/account/keys/{key_id}", tags=["account"])
def account_key_delete(request: Request, key_id: int):
    if not accounts.revoke_key(_require_user(request)["id"], key_id):
        raise HTTPException(404, "Kalit topilmadi")
    return {"deleted": key_id}


# -------------------------------------------------------------------- admin
def _require_admin(request: Request) -> Optional[int]:
    if request.state.source == "service":
        return None
    u = _require_user(request)
    if u["role"] != "admin":
        raise HTTPException(403, "Faqat admin uchun")
    return u["id"]


class AdminUserUpdate(BaseModel):
    add: Optional[int] = Field(None, description="Balansga qo'shish (manfiy — ayirish)")
    tokens: Optional[int] = Field(None, ge=0, description="Balansni shu qiymatga o'rnatish")
    role: Optional[Literal["user", "vip", "admin"]] = None
    blocked: Optional[bool] = None
    note: Optional[str] = Field(None, max_length=200)


@app.get("/admin/stats", tags=["admin"])
def admin_stats(request: Request):
    _require_admin(request)
    return accounts.stats()


@app.get("/admin/users", tags=["admin"])
def admin_users(request: Request, q: str = "", limit: int = 100, offset: int = 0):
    _require_admin(request)
    return accounts.list_users(q, min(max(limit, 1), 500), max(offset, 0))


@app.get("/admin/users/{user_id}", tags=["admin"])
def admin_user(request: Request, user_id: int):
    _require_admin(request)
    u = accounts.get(user_id)
    if not u:
        raise HTTPException(404, "Foydalanuvchi topilmadi")
    return {**accounts.public(u), "usage": accounts.usage(user_id, 100), "keys": accounts.list_keys(user_id),
            "voices": len([v for v in voices.list_all() if v.get("owner") == user_id])}


@app.patch("/admin/users/{user_id}", tags=["admin"])
def admin_user_update(request: Request, user_id: int, body: AdminUserUpdate):
    by = _require_admin(request)
    if accounts.get(user_id) is None:
        accounts.ensure(user_id)  # botga hali yozmagan odamga oldindan token berish mumkin
    try:
        return accounts.admin_update(user_id, add=body.add, set_tokens=body.tokens, role=body.role,
                                     blocked=body.blocked, note=body.note, by=by)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class VoiceOwner(BaseModel):
    voice_id: str
    owner: int


@app.post("/internal/voice-owner", include_in_schema=False)
def internal_voice_owner(request: Request, body: VoiceOwner):
    """Bot eski (egasiz) klon ovozlarni foydalanuvchiga biriktiradi."""
    if request.state.source != "service":
        raise HTTPException(403, "Faqat ichki xizmat uchun")
    try:
        meta = voices.get_meta(body.voice_id)
    except KeyError:
        raise HTTPException(404, "Ovoz topilmadi")
    if meta.get("owner") is None:
        meta = voices.update_meta(body.voice_id, owner=body.owner)
    return meta


# ---------------------------------------------------------------------- ui
WEBSITE_DIR = Path(os.environ.get("OVOZLAB_WEBSITE_DIR", config.ROOT_DIR / "website"))


def _app_page() -> HTMLResponse:
    # CSS/JS havolasiga fayl vaqtini qo'shamiz: Cloudflare/brauzer keshi har yangilanishda o'zi almashadi.
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    for name in ("app.css", "app.js"):
        f = STATIC_DIR / name
        if f.is_file():
            html = html.replace(f'"static/{name}"', f'"static/{name}?v={int(f.stat().st_mtime)}"')
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.get("/", include_in_schema=False)
def index():
    # Server rejimida bosh sahifa — landing, ilova /app da. Ish stolida — darhol ilova.
    if SERVER_MODE and (WEBSITE_DIR / "index.html").is_file():
        return FileResponse(WEBSITE_DIR / "index.html", headers={"Cache-Control": "no-cache"})
    return _app_page()


@app.get("/app", include_in_schema=False)
def app_page():
    return _app_page()


@app.get("/app/", include_in_schema=False)
def app_page_slash():
    return RedirectResponse("/app")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
if SERVER_MODE and (WEBSITE_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=WEBSITE_DIR / "assets"), name="website-assets")
