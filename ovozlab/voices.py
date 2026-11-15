"""Ovoz profillarini diskda saqlash.

Har bir profil: ``data/voices/<id>/``
  - ``meta.json``      — nom, reference matni, til, yaratilgan vaqt
  - ``reference.wav``  — yuklangan reference audio (24 kHz mono)
  - ``prompt.pt``      — OmniVoice VoiceClonePrompt (qayta ishlatish uchun tayyor tokenlar)
"""

from __future__ import annotations

import json
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

from ovozlab import config

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_cache: dict = {}
_cache_lock = threading.Lock()


def _dir(voice_id: str) -> Path:
    if not _ID_RE.match(voice_id or ""):
        raise KeyError(voice_id)
    return config.VOICES_DIR / voice_id


def new_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32] or "voice"
    return f"{slug}-{uuid.uuid4().hex[:6]}"


def save(voice_id: str, name: str, ref_text: str, language: str, prompt, ref_wav: Path, duration_s: float) -> dict:
    d = _dir(voice_id)
    d.mkdir(parents=True, exist_ok=True)
    prompt.save(str(d / "prompt.pt"))
    if ref_wav.resolve() != (d / "reference.wav").resolve():
        shutil.move(str(ref_wav), d / "reference.wav")
    meta = {
        "id": voice_id,
        "name": name,
        "ref_text": ref_text,
        "language": language,
        "duration_s": round(duration_s, 2),
        "created_at": int(time.time()),
    }
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    with _cache_lock:
        _cache[voice_id] = prompt
    return meta


def get_meta(voice_id: str) -> dict:
    p = _dir(voice_id) / "meta.json"
    if not p.is_file():
        raise KeyError(voice_id)
    return json.loads(p.read_text(encoding="utf-8"))


def list_all() -> list[dict]:
    if not config.VOICES_DIR.is_dir():
        return []
    out = []
    for d in config.VOICES_DIR.iterdir():
        try:
            out.append(get_meta(d.name))
        except (KeyError, ValueError, OSError):
            continue
    return sorted(out, key=lambda m: m.get("created_at", 0), reverse=True)


def load_prompt(voice_id: str):
    with _cache_lock:
        if voice_id in _cache:
            return _cache[voice_id]
    p = _dir(voice_id) / "prompt.pt"
    if not p.is_file():
        raise KeyError(voice_id)
    from omnivoice.models.omnivoice import VoiceClonePrompt

    prompt = VoiceClonePrompt.load(str(p))
    with _cache_lock:
        _cache[voice_id] = prompt
    return prompt


def rename(voice_id: str, name: str) -> dict:
    meta = get_meta(voice_id)
    meta["name"] = name
    (_dir(voice_id) / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def reference_path(voice_id: str) -> Path:
    p = _dir(voice_id) / "reference.wav"
    if not p.is_file():
        raise KeyError(voice_id)
    return p


def delete(voice_id: str) -> None:
    d = _dir(voice_id)
    if not d.is_dir():
        raise KeyError(voice_id)
    shutil.rmtree(d)
    with _cache_lock:
        _cache.pop(voice_id, None)
