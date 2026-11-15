"""OvozLab ish stoli ilovasi: lokal FastAPI server + WebView2 oynasi (pywebview)."""

from __future__ import annotations

import logging
import logging.handlers
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from ovozlab import config


def _setup_logging() -> Path:
    log_dir = config.HOME / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "ovozlab.log"
    handlers: list[logging.Handler] = [
        logging.handlers.RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    ]
    if sys.stderr is not None:  # pythonw.exe da stderr yo'q
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=handlers, force=True)
    return log_file


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_port(port: int, timeout: float = 30) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.1)
    return False


class Api:
    """JavaScript'dan ``window.pywebview.api.*`` orqali chaqiriladigan funksiyalar."""

    def __init__(self) -> None:
        self._window = None

    def pick_folder(self, initial: str = "") -> str | None:
        import webview

        kind = getattr(getattr(webview, "FileDialog", None), "FOLDER", None) or webview.FOLDER_DIALOG
        result = self._window.create_file_dialog(kind, directory=initial if initial and os.path.isdir(initial) else "")
        return result[0] if result else None

    def save_history(self, item_id: str, fmt: str = "wav") -> str | None:
        import webview

        from ovozlab import history
        from ovozlab.engine import encode_audio

        src = history.audio_path(item_id)
        kind = getattr(getattr(webview, "FileDialog", None), "SAVE", None) or webview.SAVE_DIALOG
        target = self._window.create_file_dialog(kind, save_filename=f"ovozlab-{item_id}.{fmt}")
        if not target:
            return None
        target = target if isinstance(target, str) else target[0]
        if fmt == "wav":
            Path(target).write_bytes(src.read_bytes())
        else:
            import soundfile as sf

            samples, sr = sf.read(str(src), dtype="float32")
            Path(target).write_bytes(encode_audio(samples, sr, "mp3"))
        return target

    def open_url(self, url: str) -> None:
        if url.startswith(("https://", "http://")):
            webbrowser.open(url)

    def restart(self) -> None:
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen([sys.executable, "-m", "ovozlab"], cwd=str(config.ROOT_DIR), creationflags=flags)
        self._window.destroy()


ICON_FILE = Path(__file__).parent / "static" / "ovozlab.ico"
APP_USER_MODEL_ID = "OvozLab.OvozLab"


def _set_app_id() -> None:
    """Vazifalar panelida Python emas, OvozLab sifatida (o'z ikonkasi bilan) guruhlanishi uchun."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except Exception:
            pass


def _set_window_icon(window) -> None:
    if sys.platform != "win32" or not ICON_FILE.is_file():
        return
    try:
        import ctypes

        hwnd = int(window.native.Handle.ToInt64())
        user32 = ctypes.windll.user32
        IMAGE_ICON, LR_LOADFROMFILE, WM_SETICON = 1, 0x10, 0x80
        for kind, size in ((0, 16), (1, 32)):  # ICON_SMALL, ICON_BIG
            h = user32.LoadImageW(None, str(ICON_FILE), IMAGE_ICON, size, size, LR_LOADFROMFILE)
            if h:
                user32.SendMessageW(hwnd, WM_SETICON, kind, h)
    except Exception as exc:
        logging.getLogger("ovozlab.desktop").debug("Ikonka o'rnatilmadi: %s", exc)


def main() -> None:
    _set_app_id()
    log_file = _setup_logging()
    log = logging.getLogger("ovozlab.desktop")
    config.apply_model_env()
    log.info("OvozLab ishga tushmoqda (home=%s, log=%s)", config.HOME, log_file)

    import uvicorn

    from ovozlab.server import app

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, access_log=False))
    threading.Thread(target=server.run, name="uvicorn", daemon=True).start()
    if not _wait_port(port):
        log.error("Server ishga tushmadi")
        sys.exit(1)
    url = f"http://127.0.0.1:{port}/"

    try:
        import webview
    except ImportError:
        log.warning("pywebview topilmadi — brauzerda ochilmoqda: %s", url)
        webbrowser.open(url)
        while True:
            time.sleep(3600)

    api = Api()
    window = webview.create_window(
        "OvozLab", url, js_api=api, width=1320, height=860, min_size=(1000, 660),
        background_color="#FFFFFF", text_select=True,
    )
    api._window = window
    window.events.shown += lambda: _set_window_icon(window)
    storage = config.HOME / "webview"
    storage.mkdir(parents=True, exist_ok=True)
    webview.start(private_mode=False, storage_path=str(storage))
    server.should_exit = True
    log.info("OvozLab yopildi")
