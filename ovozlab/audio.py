"""Audio dekodlash (ffmpeg orqali) va o'zbek kirill -> lotin transliteratsiyasi."""

from __future__ import annotations

import os
import subprocess
import tempfile

import numpy as np


def ffmpeg_exe() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def decode(data: bytes, sample_rate: int) -> np.ndarray:
    """Istalgan audio formatni (WAV/MP3/M4A/OGG/WebM/FLAC...) mono float32 ga dekodlaydi.

    ffprobe kerak emas: imageio-ffmpeg bilan keladigan ffmpeg binarini to'g'ridan-to'g'ri chaqiramiz.
    Vaqtinchalik fayl ishlatiladi, chunki M4A/MP4 kabi formatlar pipe orqali o'qilmaydi (seek kerak).
    """
    fd, path = tempfile.mkstemp(suffix=".audio")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        proc = subprocess.run(
            [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-nostdin",
             "-i", path, "-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "f32le", "pipe:1"],
            capture_output=True,
            timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    if proc.returncode != 0 or not proc.stdout:
        msg = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise ValueError(msg[-1] if msg else "noma'lum audio format")
    return np.frombuffer(proc.stdout, dtype="<f4").copy()


def split_on_pauses(samples: np.ndarray, sr: int, target_s: float = 25.0, search_s: float = 5.0,
                    min_rms: float = 1e-4) -> list[tuple[int, int]]:
    """Audioni ~``target_s`` soniyalik bo'laklarga, eng jim joydan kesib ajratadi.

    Har bir kesim ``target_s - search_s`` … ``target_s`` oralig'idagi eng past energiyali 0.3 s oynaga
    tushadi, shunda so'z o'rtasidan kesilmaydi. Butunlay jim bo'laklar tashlab yuboriladi.
    """
    n, step = len(samples), int(sr * 0.05)
    win = int(sr * 0.3)
    out, start = [], 0
    while start < n:
        end = min(start + int(target_s * sr), n)
        if end < n:
            lo = max(start + int((target_s - search_s) * sr), start + win)
            best, best_e = end, None
            for pos in range(lo, end - win, step):
                e = float(np.mean(samples[pos:pos + win] ** 2))
                if best_e is None or e < best_e:
                    best, best_e = pos + win // 2, e
            end = best
        seg = samples[start:end]
        if len(seg) > sr * 0.3 and float(np.sqrt(np.mean(seg ** 2))) > min_rms:
            out.append((start, end))
        start = end
    return out or [(0, n)]


# --- O'zbek kirill -> lotin --------------------------------------------------
_CYR2LAT = {
    "ў": "o'", "ғ": "g'", "ш": "sh", "ч": "ch", "ё": "yo", "ю": "yu", "я": "ya",
    "ж": "j", "ц": "ts", "щ": "sh", "қ": "q", "ҳ": "h", "ъ": "'", "ь": "",
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "з": "z", "и": "i",
    "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x", "ы": "i", "э": "e",
}


def cyr_to_lat(text: str) -> str:
    """Whisper o'zbekchani ba'zan kirillda yozadi; TTS matni lotinda bo'lgani uchun lotinga o'giramiz."""
    out = []
    prev_alpha = False
    for ch in text:
        low = ch.lower()
        if low == "е":  # so'z boshida "ye", ichida "e"
            lat = "e" if prev_alpha else "ye"
        elif low in _CYR2LAT:
            lat = _CYR2LAT[low]
        else:
            out.append(ch)
            prev_alpha = ch.isalpha()
            continue
        if ch.isupper() and lat:
            lat = lat[0].upper() + lat[1:]
        out.append(lat)
        prev_alpha = True
    return "".join(out)
