"""Yaratilgan audiolar tarixi: ``data/history/<id>.wav`` + ``<id>.json``."""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path

import numpy as np

from ovozlab import config

_ID_RE = re.compile(r"^[0-9a-f]{12}$")


def _paths(item_id: str) -> tuple[Path, Path]:
    if not _ID_RE.match(item_id or ""):
        raise KeyError(item_id)
    return config.HISTORY_DIR / f"{item_id}.wav", config.HISTORY_DIR / f"{item_id}.json"


def add(samples: np.ndarray, sample_rate: int, meta: dict) -> dict:
    import soundfile as sf

    config.HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    item_id = uuid.uuid4().hex[:12]
    wav, js = _paths(item_id)
    sf.write(str(wav), samples, sample_rate, subtype="PCM_16")
    record = {
        "id": item_id,
        "created_at": int(time.time()),
        "duration_s": round(len(samples) / sample_rate, 2),
        **meta,
    }
    js.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    _prune()
    return record


def list_all(limit: int = 100) -> list[dict]:
    if not config.HISTORY_DIR.is_dir():
        return []
    items = []
    for js in config.HISTORY_DIR.glob("*.json"):
        try:
            items.append(json.loads(js.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    items.sort(key=lambda r: r.get("created_at", 0), reverse=True)
    return items[:limit]


def audio_path(item_id: str) -> Path:
    wav, _ = _paths(item_id)
    if not wav.is_file():
        raise KeyError(item_id)
    return wav


def get(item_id: str) -> dict:
    _, js = _paths(item_id)
    if not js.is_file():
        raise KeyError(item_id)
    return json.loads(js.read_text(encoding="utf-8"))


def delete(item_id: str) -> None:
    wav, js = _paths(item_id)
    if not js.is_file():
        raise KeyError(item_id)
    for p in (wav, js):
        p.unlink(missing_ok=True)


def clear() -> int:
    n = 0
    for item in list_all(limit=10_000):
        delete(item["id"])
        n += 1
    return n


def _prune() -> None:
    items = list_all(limit=10_000)
    for item in items[config.HISTORY_LIMIT:]:
        try:
            delete(item["id"])
        except KeyError:
            pass
