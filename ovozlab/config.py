"""OvozLab sozlamalari va fayl yo'llari.

Hamma foydalanuvchi ma'lumotlari bitta "uy" papkasida turadi:
    %LOCALAPPDATA%\\OvozLab\\            (Windows)
    ~/.local/share/OvozLab/             (Linux / macOS)
      settings.json   — tanlangan qurilma, modellar papkasi, sozlash tugaganmi
      data/voices/    — klonlangan ovoz profillari
      data/history/   — yaratilgan audio tarixi
      models/         — standart modellar papkasi (o'rnatish ustasida o'zgartiriladi)

``OVOZLAB_HOME`` muhit o'zgaruvchisi bilan uy papkasini boshqa joyga ko'chirish mumkin.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

APP_NAME = "OvozLab"
ROOT_DIR = Path(__file__).resolve().parent.parent  # pyproject.toml / uv.lock turgan joy


def _default_home() -> Path:
    if os.environ.get("OVOZLAB_HOME"):
        return Path(os.environ["OVOZLAB_HOME"])
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_NAME
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME


HOME = _default_home().resolve()
SETTINGS_FILE = HOME / "settings.json"

_DEFAULTS = {
    "models_dir": str(HOME / "models"),
    "backend": None,          # "xpu" | "cuda" | "cpu" | None (hali tanlanmagan)
    "setup_complete": False,
    "asr_enabled": True,      # o'zbekcha Whisper (matnni avtomatik aniqlash)
    "default_num_step": 32,
}


class Settings:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data = dict(_DEFAULTS)
        if SETTINGS_FILE.is_file():
            try:
                self._data.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass

    def get(self, key: str):
        with self._lock:
            return self._data.get(key, _DEFAULTS.get(key))

    def update(self, **values) -> dict:
        with self._lock:
            self._data.update({k: v for k, v in values.items() if k in _DEFAULTS})
            HOME.mkdir(parents=True, exist_ok=True)
            tmp = SETTINGS_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, SETTINGS_FILE)
            return dict(self._data)

    def as_dict(self) -> dict:
        with self._lock:
            return dict(self._data)


settings = Settings()

DATA_DIR = HOME / "data"
VOICES_DIR = DATA_DIR / "voices"
HISTORY_DIR = DATA_DIR / "history"
HISTORY_LIMIT = 300


def models_dir() -> Path:
    return Path(settings.get("models_dir")).expanduser().resolve()


def apply_model_env() -> None:
    """HuggingFace kesh papkasini tanlangan modellar papkasiga yo'naltiradi.

    ``huggingface_hub`` import qilinishidan OLDIN chaqirilishi kerak (u yo'lni import paytida o'qiydi).
    """
    os.environ["HF_HOME"] = str(models_dir())
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")


# --- Model ------------------------------------------------------------------
TTS_MODEL = os.environ.get("OVOZLAB_MODEL", "k2-fsa/OmniVoice")
# OmniVoice reposida audio_tokenizer yo'q — transformers shu repodan oladi.
AUDIO_TOKENIZER_MODEL = "eustlb/higgs-audio-v2-tokenizer"
# O'zbek tiliga fine-tune qilingan Whisper (Apache-2.0, WER ~8–14%).
ASR_MODEL = os.environ.get("OVOZLAB_ASR_MODEL", "navai-uz/whisper-medium-uzbek")
ASR_KEEP_LOADED = os.environ.get("OVOZLAB_ASR_KEEP", "1") not in ("0", "false", "no")

DEVICE_OVERRIDE = os.environ.get("OVOZLAB_DEVICE", "").strip().lower() or None

MAX_TEXT_CHARS = int(os.environ.get("OVOZLAB_MAX_TEXT_CHARS", "5000"))
MAX_UPLOAD_MB = int(os.environ.get("OVOZLAB_MAX_UPLOAD_MB", "25"))

# --- Til -------------------------------------------------------------------
# OmniVoice'da o'zbek tili: "uz" (ISO uzb, ~115 soat) — asosiy; "uzn" (Northern Uzbek, ~15 soat).
DEFAULT_LANGUAGE = "uz"

_LANGUAGE_ALIASES = {
    "uz": "uz", "uzb": "uz", "uzbek": "uz", "o'zbek": "uz", "o‘zbek": "uz", "o`zbek": "uz",
    "ozbek": "uz", "uz-latn": "uz", "uz_latn": "uz", "uz-uz": "uz",
    "uzn": "uzn", "northern uzbek": "uzn",
}


def resolve_language(value: str | None) -> str:
    """Faqat o'zbek tili qabul qilinadi; boshqa til berilsa ValueError."""
    if value is None or not str(value).strip():
        return DEFAULT_LANGUAGE
    key = str(value).strip().lower()
    if key in _LANGUAGE_ALIASES:
        return _LANGUAGE_ALIASES[key]
    raise ValueError(f"Faqat o'zbek tili qo'llab-quvvatlanadi ('uz', 'uzb' yoki 'uzn'). Berilgan: {value!r}")
