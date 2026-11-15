"""OmniVoice (TTS) va Whisper (ASR) modellarini yuklash va ishlatish."""

from __future__ import annotations

import gc
import io
import logging
import threading
import time
from typing import Optional

import numpy as np

from ovozlab import config

logger = logging.getLogger("ovozlab.engine")


def _patch_xpu(torch) -> None:
    """Windows'dagi Intel Arc drayverlari ``torch.xpu.mem_get_info()`` ni qo'llamaydi, transformers esa
    model yuklashda uni chaqiradi. ``total - reserved`` bilan almashtiramiz."""
    xpu = getattr(torch, "xpu", None)
    if xpu is None or not hasattr(xpu, "mem_get_info") or getattr(xpu, "_ovozlab_patched", False):
        return
    original = xpu.mem_get_info

    def mem_get_info(device=None):
        try:
            return original(device)
        except RuntimeError:
            idx = torch.xpu.current_device() if device is None else (torch.device(device).index or 0)
            total = int(torch.xpu.get_device_properties(idx).total_memory)
            return max(total - int(torch.xpu.memory_reserved(idx)), 0), total

    xpu.mem_get_info = mem_get_info
    xpu._ovozlab_patched = True


def pick_device(torch) -> str:
    want = config.DEVICE_OVERRIDE or config.settings.get("backend")
    if want == "xpu" and hasattr(torch, "xpu") and torch.xpu.is_available():
        return "xpu"
    if want == "cuda" and torch.cuda.is_available():
        return "cuda"
    if want == "cpu":
        return "cpu"
    # tanlangan qurilma topilmasa — eng yaxshisini avtomatik
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch, "xpu") and torch.xpu.is_available():
        return "xpu"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _empty_cache(torch, device: Optional[str]) -> None:
    gc.collect()
    if device == "xpu":
        torch.xpu.empty_cache()
    elif device == "cuda":
        torch.cuda.empty_cache()


class Engine:
    def __init__(self) -> None:
        self.model = None
        self.device: Optional[str] = None
        self.device_name: Optional[str] = None
        self.dtype: Optional[str] = None
        self.state = "not_loaded"  # not_loaded | loading | ready | error
        self.error: Optional[str] = None
        self.load_seconds: Optional[float] = None
        self._load_lock = threading.Lock()
        self._gen_lock = threading.Lock()  # bitta GPU — bir vaqtda bitta generatsiya
        self._asr = None
        self._asr_lock = threading.Lock()

    # ------------------------------------------------------------------ load
    def load(self) -> None:
        with self._load_lock:
            if self.state == "ready":
                return
            self.state, self.error = "loading", None
            t0 = time.time()
            try:
                config.apply_model_env()
                import torch

                _patch_xpu(torch)
                from omnivoice import OmniVoice
                from omnivoice.utils.dtype import tts_dtype_name

                device = pick_device(torch)
                dtype_name = tts_dtype_name(device)
                logger.info("Model yuklanmoqda: %s (device=%s, dtype=%s)", config.TTS_MODEL, device, dtype_name)
                self.model = OmniVoice.from_pretrained(
                    config.TTS_MODEL, device_map=device, dtype=getattr(torch, dtype_name)
                )
                self.device, self.dtype = device, dtype_name
                self.device_name = _device_name(torch, device)
                self.load_seconds = round(time.time() - t0, 1)
                self.state = "ready"
                logger.info("Model tayyor (%.1fs) — %s", self.load_seconds, self.device_name)
            except Exception as exc:
                logger.exception("Modelni yuklab bo'lmadi")
                self.state, self.error = "error", f"{type(exc).__name__}: {exc}"
                raise

    def ensure_loaded(self):
        if self.state != "ready":
            self.load()
        return self.model

    @property
    def sample_rate(self) -> int:
        return int(self.model.sampling_rate) if self.model is not None else 24000

    # ------------------------------------------------------------------- asr
    def transcribe(self, samples: np.ndarray, sample_rate: int) -> str:
        """Qisqa audioni (≤30 s) o'zbekcha matnga o'giradi (Whisper)."""
        return self.transcribe_segments(samples, sample_rate)["text"]

    def transcribe_segments(self, samples: np.ndarray, sample_rate: int, progress=None) -> dict:
        """Istalgan uzunlikdagi audioni matnga o'giradi.

        Whisper bir vaqtda ≤30 s eshitadi, shuning uchun audio jimlik joylaridan ~25 s lik bo'laklarga
        bo'linadi. Natija: {"text", "segments": [{"start", "end", "text"}]}.
        """
        if not config.settings.get("asr_enabled"):
            raise RuntimeError("Nutqni matnga o'girish o'chirilgan (Sozlamalar)")
        self.ensure_loaded()
        import torch
        from transformers import pipeline

        from ovozlab.audio import cyr_to_lat, split_on_pauses

        with self._asr_lock:
            if self._asr is None:
                dtype = torch.float32 if self.device in ("cpu", "mps") else torch.float16
                logger.info("Whisper yuklanmoqda: %s (%s)", config.ASR_MODEL, self.device)
                self._asr = pipeline(
                    "automatic-speech-recognition", model=config.ASR_MODEL, dtype=dtype, device_map=self.device
                )
            segments = []
            try:
                chunks = split_on_pauses(samples.astype(np.float32), sample_rate)
                for i, (a, b) in enumerate(chunks):
                    with self._gen_lock:
                        out = self._asr(
                            {"array": samples[a:b].astype(np.float32), "sampling_rate": sample_rate},
                            generate_kwargs={"language": "uzbek", "task": "transcribe"},
                        )
                    t = cyr_to_lat(out["text"].strip())
                    if t:
                        segments.append({"start": round(a / sample_rate, 2), "end": round(b / sample_rate, 2),
                                         "text": t[:1].upper() + t[1:]})
                    if progress:
                        progress(i + 1, len(chunks))
            finally:
                if not config.ASR_KEEP_LOADED:
                    self._asr = None
                    _empty_cache(torch, self.device)
        return {"text": " ".join(s["text"] for s in segments), "segments": segments}

    # ----------------------------------------------------------------- clone
    def create_voice_prompt(self, ref_audio_path: str, ref_text: str):
        model = self.ensure_loaded()
        with self._gen_lock:
            return model.create_voice_clone_prompt(ref_audio=ref_audio_path, ref_text=ref_text)

    # ------------------------------------------------------------------- tts
    def synthesize(
        self,
        text: str,
        language: str,
        voice_prompt=None,
        ref_audio_path: Optional[str] = None,
        ref_text: Optional[str] = None,
        speed: Optional[float] = None,
        num_step: Optional[int] = None,
        seed: Optional[int] = None,
        instruct: Optional[str] = None,
    ) -> np.ndarray:
        model = self.ensure_loaded()
        steps = num_step or int(config.settings.get("default_num_step") or 32)
        with self._gen_lock:
            audios = model.generate(
                text=text,
                language=language,
                instruct=instruct or None,
                voice_clone_prompt=voice_prompt,
                ref_audio=ref_audio_path if voice_prompt is None else None,
                ref_text=ref_text if voice_prompt is None else None,
                speed=speed,
                seed=seed,
                num_step=steps,
            )
        arr = audios[0].detach().to("cpu").float().numpy().squeeze()
        return np.clip(arr, -1.0, 1.0)


def _device_name(torch, device: str) -> str:
    try:
        if device == "xpu":
            return torch.xpu.get_device_name(0)
        if device == "cuda":
            return torch.cuda.get_device_name(0)
    except Exception:
        pass
    return {"cpu": "CPU", "mps": "Apple GPU"}.get(device, device)


engine = Engine()


# ---------------------------------------------------------------- encoding
def encode_audio(samples: np.ndarray, sample_rate: int, fmt: str) -> bytes:
    """numpy float32 to'lqinni WAV (PCM16) yoki MP3 baytlarga aylantirish."""
    import soundfile as sf

    buf = io.BytesIO()
    if fmt == "wav":
        sf.write(buf, samples, sample_rate, format="WAV", subtype="PCM_16")
    elif fmt == "mp3":
        sf.write(buf, samples, sample_rate, format="MP3")  # libsndfile >= 1.1
    else:
        raise ValueError("format faqat 'wav' yoki 'mp3' bo'lishi mumkin")
    return buf.getvalue()
