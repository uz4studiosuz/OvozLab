"""OvozLab FastAPI serveri.

Ishga tushirish (ilova oynasisiz):  uv run uvicorn ovozlab.server:app --port 8000
Ilova oynasi bilan:                 uv run python -m ovozlab
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ovozlab import __version__, config, firstrun, history, voices
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
    if config.settings.get("setup_complete") and os.environ.get("OVOZLAB_PRELOAD", "1") != "0":
        start_model_load()
    yield


app = FastAPI(
    title="OvozLab API",
    version=__version__,
    description="O'zbek tili uchun ochiq kodli matndan nutq (TTS) va ovoz klonlash API.",
    lifespan=lifespan,
)


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
    if not config.settings.get("setup_complete"):
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
        "Access-Control-Expose-Headers": "X-Audio-Duration, X-History-Id, X-Mood-Source, X-Voice-Used",
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
        "setup_complete": bool(config.settings.get("setup_complete")),
        "model": config.TTS_MODEL,
        "device": engine.device,
        "device_name": engine.device_name,
        "dtype": engine.dtype,
        "load_seconds": engine.load_seconds,
        "default_language": config.DEFAULT_LANGUAGE,
        "version": __version__,
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
def list_voices():
    return voices.list_all()


@app.get("/voices/{voice_id}")
def get_voice(voice_id: str):
    try:
        return voices.get_meta(voice_id)
    except KeyError:
        raise HTTPException(404, "Ovoz topilmadi")


@app.get("/voices/{voice_id}/reference")
def get_voice_reference(voice_id: str):
    try:
        return FileResponse(voices.reference_path(voice_id), media_type="audio/wav")
    except KeyError:
        raise HTTPException(404, "Ovoz topilmadi")


class VoiceUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)


@app.patch("/voices/{voice_id}")
def update_voice(voice_id: str, body: VoiceUpdate):
    """Ovoz nomini o'zgartirish."""
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Nom bo'sh bo'lmasligi kerak")
    try:
        return voices.rename(voice_id, name)
    except KeyError:
        raise HTTPException(404, "Ovoz topilmadi")


@app.delete("/voices/{voice_id}")
def delete_voice(voice_id: str):
    try:
        voices.delete(voice_id)
    except KeyError:
        raise HTTPException(404, "Ovoz topilmadi")
    return {"deleted": voice_id}


@app.post("/transcribe")
async def transcribe(audio: UploadFile = File(..., description="Audio fayl, 30 soniyagacha")):
    """Audioni Whisper bilan o'zbekcha matnga o'giradi."""
    _require_model()
    samples, duration = await _read_upload(audio, 16000)
    try:
        text = await run_in_threadpool(engine.transcribe, samples, 16000)
    except Exception as exc:
        logger.exception("Whisper xatosi")
        raise HTTPException(500, f"Audioni matnga o'girib bo'lmadi: {exc}") from exc
    return {"text": text, "duration_s": round(duration, 2)}


@app.post("/stt")
async def speech_to_text(audio: UploadFile = File(..., description="Audio yoki video fayl, 60 daqiqagacha")):
    """Nutqdan matn: istalgan uzunlikdagi o'zbekcha audioni matnga o'giradi (vaqt belgilari bilan)."""
    _require_model()
    samples, duration = await _read_upload(audio, 16000, max_seconds=STT_MAX_SECONDS, max_mb=STT_MAX_MB)
    import time as _t

    t0 = _t.time()
    try:
        result = await run_in_threadpool(engine.transcribe_segments, samples, 16000)
    except Exception as exc:
        logger.exception("STT xatosi")
        raise HTTPException(500, f"Matnga o'girib bo'lmadi: {exc}") from exc
    return {**result, "duration_s": round(duration, 2), "elapsed_s": round(_t.time() - t0, 1)}


@app.post("/clone")
async def clone_voice(
    audio: UploadFile = File(..., description="Reference audio (WAV/MP3/FLAC/OGG/M4A/WebM), 3–10 soniya"),
    ref_text: Optional[str] = Form(None, description="Audioda aytilgan matn. Bo'sh bo'lsa Whisper aniqlaydi"),
    name: str = Form("Mening ovozim"),
    language: str = Form("uz"),
    mood: Optional[Literal["neutral", "happy", "sad", "serious", "story"]] = Form(None, description="Yozuv kayfiyati"),
):
    """Reference audio asosida yangi ovoz profilini yaratadi va saqlaydi."""
    _require_model()
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
        meta = voices.save(voice_id, name, ref_text, lang, prompt, ref_wav, duration, mood=mood)
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
    return meta


# ---------------------------------------------------------------------- tts
@app.post("/tts")
async def tts(req: TTSRequest):
    """Matndan audio yaratadi. ``voice_id`` berilsa — klonlangan ovozda."""
    _require_model()
    text = _check_text(req.text)
    lang = _language(req.language)
    prompt, voice_name, voice_used = None, None, req.voice_id
    mood = req.mood if req.mood and req.mood != "neutral" else None
    mood_source = None
    if req.voice_id:
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
    if req.save_history:
        rec = await run_in_threadpool(history.add, samples, engine.sample_rate, {
            "text": text, "voice_id": req.voice_id, "voice_name": voice_name or "Avtomatik",
            "instruct": req.instruct, "speed": req.speed, "num_step": req.num_step, "seed": req.seed,
            "mood": req.mood, "mood_source": mood_source,
        })
        headers["X-History-Id"] = rec["id"]
    return _audio_response(samples, req.format, req.voice_id or "ovozlab", headers)


@app.post("/tts/instant")
async def tts_instant(
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
    return _audio_response(samples, format, "instant")


# ------------------------------------------------------------------ history
@app.get("/history")
def list_history(limit: int = 100):
    return history.list_all(limit=min(max(limit, 1), 500))


@app.get("/history/{item_id}/audio")
def history_audio(item_id: str, format: Literal["wav", "mp3"] = "wav"):
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
def delete_history(item_id: str):
    try:
        history.delete(item_id)
    except KeyError:
        raise HTTPException(404, "Topilmadi")
    return {"deleted": item_id}


@app.delete("/history")
def clear_history():
    return {"deleted": history.clear()}


# ---------------------------------------------------------------------- ui
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
