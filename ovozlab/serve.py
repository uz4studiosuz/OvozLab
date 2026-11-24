"""OvozLab'ni serverda (oynasiz, Docker/Linux) API sifatida ishga tushirish.

    OVOZLAB_API_KEY=... python -m ovozlab.serve --host 0.0.0.0 --port 8020

Birinchi ishga tushishda kerakli modellar yuklab olinadi, sozlash ustasi o'tkazib yuboriladi.
"""

from __future__ import annotations

import argparse
import logging
import os

os.environ.setdefault("OVOZLAB_SERVER", "1")

from ovozlab import config, firstrun  # noqa: E402


def prepare() -> None:
    config.apply_model_env()  # huggingface_hub import qilinishidan oldin
    from huggingface_hub import snapshot_download

    mdir = config.models_dir()
    hub = mdir / "hub"
    want_asr = os.environ.get("OVOZLAB_ASR", "1") not in ("0", "false", "no")
    for model in firstrun.MODELS:
        if model["id"] == "asr" and not want_asr:
            continue
        if firstrun.model_present(mdir, model):
            continue
        for repo in model["repos"]:
            logging.info("Model yuklanmoqda: %s -> %s", repo, hub)
            snapshot_download(repo, cache_dir=str(hub))
    backend = firstrun.installed_backend()
    if backend is None:
        raise SystemExit("PyTorch o'rnatilmagan: uv sync --extra cuda (yoki cpu)")
    config.settings.update(setup_complete=True, backend=backend, asr_enabled=want_asr)


def main() -> None:
    parser = argparse.ArgumentParser(description="OvozLab API serveri")
    parser.add_argument("--host", default=os.environ.get("OVOZLAB_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("OVOZLAB_PORT", "8020")))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if not os.environ.get("OVOZLAB_API_KEY", "").strip():
        logging.warning("OVOZLAB_API_KEY berilmagan — API hamma uchun ochiq!")
    prepare()

    import uvicorn

    uvicorn.run("ovozlab.server:app", host=args.host, port=args.port, proxy_headers=True)


if __name__ == "__main__":
    main()
