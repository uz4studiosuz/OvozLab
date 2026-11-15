"""Birinchi ishga tushish: qurilmani aniqlash, PyTorch va modellarni yuklab olish.

O'rnatuvchi (setup.exe) faqat kichik asosiy muhitni (~250 MB) o'rnatadi. Og'ir qismlar — tanlangan
qurilmaga mos PyTorch va AI modellar — shu modul orqali, foydalanuvchiga hajmi va joyi ko'rsatilgan holda
yuklanadi. Jarayon fon oqimida ishlaydi; UI ``progress()`` ni so'rab turadi.
"""

from __future__ import annotations

import importlib
import importlib.metadata as md
import logging
import os
import shutil
import subprocess
import tempfile
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from ovozlab import config

logger = logging.getLogger("ovozlab.firstrun")

GB = 1024**3

# Diskdagi hajmlar haqiqiy o'rnatishdan o'lchangan (Windows, Python 3.12).
BACKENDS = {
    "xpu": {
        "label": "Intel Arc / Iris Xe",
        "detail": "Intel GPU uchun PyTorch (XPU)",
        "disk": 3.9 * GB,
        "download": 1.9 * GB,
    },
    "cuda": {
        "label": "NVIDIA GeForce / RTX",
        "detail": "NVIDIA GPU uchun PyTorch (CUDA 12.8)",
        "disk": 4.6 * GB,
        "download": 2.6 * GB,
    },
    "cpu": {
        "label": "Faqat protsessor (CPU)",
        "detail": "Videokartasiz ishlaydi, lekin 5–10 baravar sekin",
        "disk": 0.9 * GB,
        "download": 0.3 * GB,
    },
}

MODELS = [
    {
        "id": "tts",
        "label": "OmniVoice — nutq sintezi modeli",
        "detail": "Matndan nutq va ovoz klonlash (k2-fsa/OmniVoice)",
        "repos": [config.TTS_MODEL, config.AUDIO_TOKENIZER_MODEL],
        "size": 3.3 * GB,
        "required": True,
    },
    {
        "id": "asr",
        "label": "O'zbekcha Whisper — nutqni matnga o'girish",
        "detail": "Klonlashda audiodagi matnni avtomatik yozadi (navai-uz/whisper-medium-uzbek)",
        "repos": [config.ASR_MODEL],
        "size": 3.1 * GB,
        "required": False,
    },
]


# ---------------------------------------------------------------- detection
def detect_gpus() -> list[str]:
    if sys.platform != "win32":
        return []
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }"],
            capture_output=True, text=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return [l.strip() for l in out.stdout.splitlines() if l.strip()]
    except Exception:
        return []


def recommend_backend(gpus: list[str]) -> str:
    names = " ".join(gpus).lower()
    if "nvidia" in names:
        return "cuda"
    if "intel" in names and ("arc" in names or "iris" in names):
        return "xpu"
    return "cpu"


def installed_backend() -> Optional[str]:
    """O'rnatilgan PyTorch qaysi qurilma uchun ekanini versiya qo'shimchasidan aniqlaydi."""
    try:
        v = md.version("torch")
    except md.PackageNotFoundError:
        return None
    if "+xpu" in v:
        return "xpu"
    if "+cu" in v:
        return "cuda"
    return "cpu"


def _repo_cached(models_dir: Path, repo: str) -> bool:
    snap = models_dir / "hub" / f"models--{repo.replace('/', '--')}" / "snapshots"
    if not snap.is_dir():
        return False
    for d in snap.iterdir():
        if (d / "config.json").exists() and any(d.glob("*.safetensors")):
            return True
    return False


def model_present(models_dir: Path, model: dict) -> bool:
    return all(_repo_cached(models_dir, r) for r in model["repos"])


def _existing_model_dir() -> Optional[str]:
    """Modellar avval boshqa dastur orqali yuklangan bo'lsa (standart HF kesh), o'shani taklif qilamiz."""
    candidates = []
    if os.environ.get("HF_HOME"):
        candidates.append(Path(os.environ["HF_HOME"]))
    candidates.append(Path.home() / ".cache" / "huggingface")
    for c in candidates:
        if c.resolve() != config.models_dir() and model_present(c, MODELS[0]):
            return str(c.resolve())
    return None


def free_bytes(path: Path) -> Optional[int]:
    p = path
    while not p.exists() and p.parent != p:
        p = p.parent
    try:
        return shutil.disk_usage(p).free
    except OSError:
        return None


def dir_size(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def status() -> dict:
    gpus = detect_gpus()
    mdir = config.models_dir()
    backend = installed_backend()
    return {
        "setup_complete": bool(config.settings.get("setup_complete")),
        "gpus": gpus,
        "recommended": recommend_backend(gpus),
        "selected_backend": config.settings.get("backend"),
        "installed_backend": backend,
        "backends": [{"id": k, **v, "installed": backend == k} for k, v in BACKENDS.items()],
        "models": [{**m, "present": model_present(mdir, m)} for m in MODELS],
        "models_dir": str(mdir),
        "default_models_dir": str(config.HOME / "models"),
        "existing_models_dir": _existing_model_dir(),
        "free_bytes": free_bytes(mdir),
        "home": str(config.HOME),
        "app_dir": str(config.ROOT_DIR),
        "asr_enabled": bool(config.settings.get("asr_enabled")),
        "restart_required": job.restart_required,
    }


def configure(backend: Optional[str], models_dir: Optional[str], asr_enabled: Optional[bool]) -> dict:
    values = {}
    if backend is not None:
        if backend not in BACKENDS:
            raise ValueError("Noma'lum qurilma turi")
        values["backend"] = backend
    if models_dir is not None:
        p = Path(models_dir).expanduser()
        if not p.is_absolute():
            raise ValueError("To'liq yo'l kiriting (masalan, D:\\OvozLab\\models)")
        try:
            p.mkdir(parents=True, exist_ok=True)
            probe = p / ".ovozlab-write-test"
            probe.write_text("ok")
            probe.unlink()
        except OSError as exc:
            raise ValueError(f"Bu papkaga yozib bo'lmaydi: {exc}") from exc
        values["models_dir"] = str(p.resolve())
    if asr_enabled is not None:
        values["asr_enabled"] = bool(asr_enabled)
    config.settings.update(**values)
    if "models_dir" in values:
        if "huggingface_hub" in sys.modules and os.environ.get("HF_HOME") != values["models_dir"]:
            # HF yo'lni import paytida o'qiydi — yangi joy ilova qayta ishga tushganda kuchga kiradi.
            job.restart_required = True
        config.apply_model_env()
    return status()


# ---------------------------------------------------------------- the job
class SetupJob:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.thread: Optional[threading.Thread] = None
        self.steps: list[dict] = []
        self.log: list[str] = []
        self.state = "idle"  # idle | running | done | error | cancelled
        self.error: Optional[str] = None
        self.cancel_event = threading.Event()
        self.proc: Optional[subprocess.Popen] = None
        self.restart_required = False
        self.started_at: Optional[float] = None

    # -- public
    def start(self, only: Optional[list[str]] = None) -> None:
        with self.lock:
            if self.state == "running":
                return
            backend = config.settings.get("backend")
            if backend not in BACKENDS:
                raise ValueError("Avval qurilma turini tanlang")
            if only and "asr" in only:
                config.settings.update(asr_enabled=True)
            self.steps = [s for s in self._plan(backend) if not only or s["id"] in only]
            self.log, self.error = [], None
            self.cancel_event.clear()
            self.state = "running"
            self.started_at = time.time()
            self.thread = threading.Thread(target=self._run, name="ovozlab-setup", daemon=True)
            self.thread.start()

    def cancel(self) -> None:
        self.cancel_event.set()
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()

    def progress(self) -> dict:
        with self.lock:
            done = sum(min(s["bytes_done"], s["bytes_total"]) for s in self.steps)
            total = sum(s["bytes_total"] for s in self.steps) or 1
            return {
                "state": self.state,
                "error": self.error,
                "steps": [dict(s) for s in self.steps],
                "log": self.log[-80:],
                "percent": round(100 * done / total, 1) if self.steps else 0,
                "elapsed_s": round(time.time() - self.started_at, 0) if self.started_at else 0,
                "restart_required": self.restart_required,
            }

    # -- internals
    def _plan(self, backend: str) -> list[dict]:
        mdir = config.models_dir()
        b = BACKENDS[backend]
        steps = [{
            "id": "runtime",
            "label": f"PyTorch — {b['label']}",
            "where": sys.prefix,
            "bytes_total": int(b["download"] + b["disk"]),
            "bytes_done": 0,
            "status": "skipped" if installed_backend() == backend else "pending",
            "detail": "",
        }]
        for m in MODELS:
            if not m["required"] and not config.settings.get("asr_enabled"):
                continue
            present = model_present(mdir, m)
            steps.append({
                "id": m["id"],
                "label": m["label"],
                "where": str(mdir),
                "bytes_total": int(m["size"]),
                "bytes_done": int(m["size"]) if present else 0,
                "status": "skipped" if present else "pending",
                "detail": "",
                "repos": m["repos"],
            })
        for s in steps:
            if s["status"] == "skipped":
                s["bytes_done"] = s["bytes_total"]
        return steps

    def _log(self, line: str) -> None:
        line = line.rstrip()
        if line:
            logger.info("[setup] %s", line)
            with self.lock:
                self.log.append(line)

    def _set(self, step: dict, **kw) -> None:
        with self.lock:
            step.update(kw)

    def _run(self) -> None:
        try:
            for step in self.steps:
                if step["status"] == "skipped":
                    continue
                if self.cancel_event.is_set():
                    raise InterruptedError
                self._set(step, status="running")
                if step["id"] == "runtime":
                    self._install_runtime(step)
                else:
                    self._download_models(step)
                self._set(step, status="done", bytes_done=step["bytes_total"], detail="Tayyor")
            config.settings.update(setup_complete=True)
            importlib.invalidate_caches()
            with self.lock:
                self.state = "done"
            self._log("Hammasi tayyor.")
        except InterruptedError:
            with self.lock:
                self.state = "cancelled"
                for s in self.steps:
                    if s["status"] == "running":
                        s["status"] = "pending"
            self._log("Bekor qilindi.")
        except Exception as exc:
            logger.exception("Sozlashda xato")
            with self.lock:
                self.state, self.error = "error", str(exc)
                for s in self.steps:
                    if s["status"] == "running":
                        s["status"] = "error"
            self._log(f"Xato: {exc}")

    # -- step: PyTorch via uv
    def _install_runtime(self, step: dict) -> None:
        uv = _find_uv()
        backend = config.settings.get("backend")
        cache = Path(tempfile.gettempdir()) / "ovozlab-uv"  # qisqa yo'l: Windows 260 belgi chegarasi
        cache.mkdir(parents=True, exist_ok=True)
        site = Path(sys.prefix)
        base_size = dir_size(site)
        env = dict(os.environ, UV_PROJECT_ENVIRONMENT=sys.prefix, UV_CACHE_DIR=str(cache),
                   UV_NO_PROGRESS="1", UV_LINK_MODE="copy")
        if (config.ROOT_DIR / "python").is_dir():  # o'rnatuvchi qo'ygan Python
            env.update(UV_PYTHON_INSTALL_DIR=str(config.ROOT_DIR / "python"), UV_PYTHON_PREFERENCE="only-managed")
        cmd = [uv, "sync", "--frozen", "--no-dev", "--inexact", "--no-install-project",
               "--extra", backend, "--directory", str(config.ROOT_DIR)]
        self._log("$ uv " + " ".join(cmd[1:]))
        stop = threading.Event()

        def monitor():
            while not stop.wait(1.0):
                done = dir_size(cache) + max(dir_size(site) - base_size, 0)
                self._set(step, bytes_done=min(int(done), int(step["bytes_total"] * 0.99)))

        threading.Thread(target=monitor, daemon=True).start()
        try:
            self.proc = subprocess.Popen(
                cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            for line in self.proc.stdout:
                self._log(line)
                if line.strip().startswith(("Downloading", "Downloaded", "Prepared", "Installed")):
                    self._set(step, detail=line.strip())
            code = self.proc.wait()
        finally:
            stop.set()
            self.proc = None
        if self.cancel_event.is_set():
            raise InterruptedError
        if code != 0:
            raise RuntimeError(f"PyTorch o'rnatilmadi (uv kodi {code}). Internet aloqasini tekshiring")
        shutil.rmtree(cache, ignore_errors=True)  # ~2 GB vaqtinchalik fayllarni tozalash

    # -- step: HuggingFace models
    def _download_models(self, step: dict) -> None:
        config.apply_model_env()
        from huggingface_hub import snapshot_download

        mdir = config.models_dir()
        hub = mdir / "hub"
        base = dir_size(mdir)
        stop = threading.Event()

        def monitor():
            while not stop.wait(1.0):
                done = max(dir_size(mdir) - base, 0)
                self._set(step, bytes_done=min(int(done), int(step["bytes_total"] * 0.99)))

        threading.Thread(target=monitor, daemon=True).start()
        try:
            for repo in step["repos"]:
                if self.cancel_event.is_set():
                    raise InterruptedError
                self._set(step, detail=f"Yuklanmoqda: {repo}")
                self._log(f"Yuklanmoqda: {repo} -> {hub}")
                snapshot_download(repo, cache_dir=str(hub))
        finally:
            stop.set()


def _find_uv() -> str:
    exe = "uv.exe" if sys.platform == "win32" else "uv"
    for p in (config.ROOT_DIR / "bin" / exe, Path(sys.prefix) / "Scripts" / exe, Path(sys.prefix) / "bin" / exe):
        if p.is_file():
            return str(p)
    found = shutil.which("uv")
    if found:
        return found
    raise RuntimeError("uv topilmadi. OvozLab'ni qayta o'rnating")


job = SetupJob()
