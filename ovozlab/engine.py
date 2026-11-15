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


def _prefetch_weights(stop: threading.Event) -> None:
    """Model fayllarini OS keshiga oldindan o'qiydi (torch import bo'layotgan paytda disk bo'sh turmasin)."""
    hub = config.models_dir() / "hub"
    files = []
    for repo in (config.TTS_MODEL, config.AUDIO_TOKENIZER_MODEL):
        snaps = hub / f"models--{repo.replace('/', '--')}" / "snapshots"
        if snaps.is_dir():
            files += sorted(snaps.rglob("*.safetensors"))
    for f in files:
        try:
            with open(f, "rb") as fh:
                while not stop.is_set() and fh.read(16 * 1024 * 1024):
                    pass
        except OSError:
            pass


# Ovoz uslubi uchun "ko'prik" jumla. OmniVoice ovoz dizaynini (keksa, bola, shivir...) asosan ingliz/xitoy
# tilida o'rgangan: o'zbekcha matnda bu buyruqlar deyarli sezilmaydi (o'lchovda keksa ayol F0 = 250 Hz,
# yosh ayol bilan bir xil). Shuning uchun uslub avval inglizcha jumlada yaratiladi (keksa ayol: ~175 Hz),
# keyin o'sha ovoz klon sifatida o'zbekcha matnga qo'llanadi. Natija keshlanadi — uslub har safar bir xil.
STYLE_BRIDGE_TEXT = ("My dear friends, today I would like to tell you a short story "
                     "about a quiet little village by the river.")
# Seed'lar solishtirilganda 11 eng aniq farq berdi: keksa ayol 175 Hz / yosh ayol 211 Hz, keksa erkak 104 Hz.
STYLE_DEFAULT_SEED = 11
STYLE_SPEED = {"elderly": 0.93}  # keksalar sekinroq gapiradi

# Taxminiy kayfiyat: (tezlik koeffitsienti, ohang siljishi yarim tonlarda, ovoz balandligi).
# Haqiqiy kayfiyat faqat kayfiyatli reference yozuvdan keladi (voices.find_mood_sibling).
MOODS = {
    "neutral": (1.00, 0.0, 1.00),
    "happy": (1.08, 1.5, 1.06),
    "sad": (0.88, -1.5, 0.88),
    "serious": (0.95, -0.7, 1.00),
    "story": (0.94, 0.4, 1.00),
}


class Engine:
    def __init__(self) -> None:
        self.model = None
        self.device: Optional[str] = None
        self.device_name: Optional[str] = None
        self.dtype: Optional[str] = None
        self.state = "not_loaded"  # not_loaded | loading | ready | error
        self.error: Optional[str] = None
        self.load_seconds: Optional[float] = None
        self.load_stage: Optional[str] = None
        self.load_started: Optional[float] = None
        self._load_lock = threading.Lock()
        self._gen_lock = threading.RLock()  # bitta GPU — bir vaqtda bitta generatsiya
        self._asr = None
        self._asr_lock = threading.Lock()
        self._styles: dict = {}
        self._style_lock = threading.Lock()

    # ------------------------------------------------------------------ load
    def load_progress(self) -> Optional[dict]:
        """Yuklanish holati: bosqich, foiz (oldingi yuklanish vaqtiga qarab taxminiy) va qolgan vaqt."""
        if self.state != "loading" or not self.load_started:
            return None
        expected = float(config.settings.get("last_load_s") or 40.0)
        elapsed = time.time() - self.load_started
        pct = min(97.0, 100.0 * elapsed / max(expected, 1.0))
        return {"stage": self.load_stage, "percent": round(pct, 1),
                "elapsed_s": round(elapsed, 1), "eta_s": round(max(expected - elapsed, 0), 0)}

    def load(self) -> None:
        with self._load_lock:
            if self.state == "ready":
                return
            self.state, self.error = "loading", None
            self.load_started = t0 = time.time()
            stop = threading.Event()
            try:
                config.apply_model_env()
                threading.Thread(target=_prefetch_weights, args=(stop,), daemon=True).start()
                self.load_stage = "Dvigatel ishga tushmoqda"
                import torch

                _patch_xpu(torch)
                from omnivoice import OmniVoice
                from omnivoice.utils.dtype import tts_dtype_name

                device = pick_device(torch)
                dtype_name = tts_dtype_name(device)
                self.load_stage = "Model xotiraga yuklanmoqda"
                logger.info("Model yuklanmoqda: %s (device=%s, dtype=%s)", config.TTS_MODEL, device, dtype_name)
                self.model = OmniVoice.from_pretrained(
                    config.TTS_MODEL, device_map=device, dtype=getattr(torch, dtype_name)
                )
                self.device, self.dtype = device, dtype_name
                self.device_name = _device_name(torch, device)
                # Birinchi generatsiya GPU yadrolarini kompilyatsiya qiladi (~10 s). Uni hozir qilib qo'ysak,
                # foydalanuvchining birinchi so'rovi ham tez bo'ladi.
                self.load_stage = "Birinchi ishga tayyorlanmoqda"
                try:
                    with self._gen_lock:
                        self.model.generate(text="Salom, OvozLab.", language="uz", num_step=8)
                except Exception as exc:
                    logger.warning("Isitish o'tkazib yuborildi: %s", exc)
                self.load_seconds = round(time.time() - t0, 1)
                config.settings.update(last_load_s=self.load_seconds)
                self.state, self.load_stage = "ready", None
                logger.info("Model tayyor (%.1fs) — %s", self.load_seconds, self.device_name)
            except Exception as exc:
                logger.exception("Modelni yuklab bo'lmadi")
                self.state, self.error = "error", f"{type(exc).__name__}: {exc}"
                raise
            finally:
                stop.set()

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
        mood: Optional[str] = None,
    ) -> np.ndarray:
        """Matndan audio. ``instruct`` (ovoz uslubi) faqat voice_prompt/ref_audio bo'lmaganda ishlatiladi;
        ``mood`` — taxminiy kayfiyat (tezlik + ohang); haqiqiy kayfiyatli profilni server o'zi tanlaydi."""
        model = self.ensure_loaded()
        steps = num_step or int(config.settings.get("default_num_step") or 32)
        if instruct and voice_prompt is None and ref_audio_path is None:
            voice_prompt = self.style_prompt(instruct, seed if seed is not None else STYLE_DEFAULT_SEED)
            for item, k in STYLE_SPEED.items():
                if item in instruct.lower():
                    speed = (speed or 1.0) * k
        speed_k, semitones, gain = MOODS.get(mood or "neutral", MOODS["neutral"])
        if speed_k != 1.0:
            speed = (speed or 1.0) * speed_k
        with self._gen_lock:
            audios = model.generate(
                text=text,
                language=language,
                voice_clone_prompt=voice_prompt,
                ref_audio=ref_audio_path if voice_prompt is None else None,
                ref_text=ref_text if voice_prompt is None else None,
                speed=speed,
                seed=seed,
                num_step=steps,
            )
        wav = audios[0].detach().to("cpu").float()
        if semitones:
            import torchaudio.functional as AF

            wav = AF.pitch_shift(wav.reshape(1, -1), self.sample_rate, semitones)
        arr = wav.numpy().squeeze() * gain
        return np.clip(arr, -1.0, 1.0)

    # ---------------------------------------------------------------- styles
    def style_prompt(self, instruct: str, seed: int):
        """Ovoz uslubi uchun klon prompt: inglizcha ko'prik jumlada yaratiladi va keshlanadi (xotira + disk)."""
        import hashlib

        from omnivoice.models.omnivoice import VoiceClonePrompt, _resolve_instruct

        norm = _resolve_instruct(instruct) or ""
        key = hashlib.sha1(f"{config.TTS_MODEL}|{norm}|{seed}|v1".encode()).hexdigest()[:16]
        with self._style_lock:
            if key in self._styles:
                return self._styles[key]
            path = config.DATA_DIR / "styles" / f"{key}.pt"
            if path.is_file():
                try:
                    p = VoiceClonePrompt.load(str(path))
                    self._styles[key] = p
                    return p
                except Exception:
                    path.unlink(missing_ok=True)
            logger.info("Ovoz uslubi yaratilmoqda: %s (seed=%s)", norm, seed)
            with self._gen_lock:
                ref = self.model.generate(text=STYLE_BRIDGE_TEXT, language="en", instruct=norm, seed=seed, num_step=32)
                p = self.model.create_voice_clone_prompt(
                    ref_audio=(ref[0].detach().float().cpu(), self.sample_rate), ref_text=STYLE_BRIDGE_TEXT)
            path.parent.mkdir(parents=True, exist_ok=True)
            p.save(str(path))
            self._styles[key] = p
            return p


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
