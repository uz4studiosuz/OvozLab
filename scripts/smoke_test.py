"""Server ishlayotganini tekshirish: TTS -> shu audiodan klon -> klon ovozda TTS.

Ishlatish (server ishga tushirilgan bo'lishi kerak):
    uv run python scripts/smoke_test.py [--api http://127.0.0.1:8000]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "outputs"


def _req(url: str, data: bytes | None = None, headers: dict | None = None, method: str | None = None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=1800) as r:
            return r.read(), {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} {url}: {e.read().decode('utf-8', 'replace')}")


def _multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for k, (name, content, ctype) in files.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n".encode() + content + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    api = ap.parse_args().api.rstrip("/")
    OUT.mkdir(exist_ok=True)

    print("1) Model tayyor bo'lishini kutish...")
    while True:
        h = json.loads(_req(f"{api}/health")[0])
        if h["status"] == "ready":
            print(f"   tayyor: device={h['device']} dtype={h['dtype']} ({h['load_seconds']}s)")
            break
        if h["status"] == "error":
            sys.exit(f"   model xatosi: {h['error']}")
        time.sleep(3)

    ref_text = "Assalomu alaykum! Bugun havo juda yaxshi, keling, birga sayrga chiqamiz."
    print("2) /tts (avtomatik ovoz)...")
    t0 = time.time()
    wav, hdr = _req(f"{api}/tts", json.dumps({"text": ref_text, "seed": 7}).encode(), {"Content-Type": "application/json"})
    (OUT / "1_auto.wav").write_bytes(wav)
    print(f"   {hdr.get('x-audio-duration')}s audio, {time.time() - t0:.1f}s da -> outputs/1_auto.wav")

    print("3) /clone (1-qadamdagi audiodan)...")
    body, ctype = _multipart({"ref_text": ref_text, "name": "Smoke test"}, {"audio": ("ref.wav", wav, "audio/wav")})
    t0 = time.time()
    voice = json.loads(_req(f"{api}/clone", body, {"Content-Type": ctype})[0])
    print(f"   ovoz: {voice['id']} ({time.time() - t0:.1f}s)")

    print("4) /tts (klon ovozda, mp3)...")
    t0 = time.time()
    text = "O'zbekiston — go'zal yurt. Toshkent, Samarqand va Buxoro qadimiy shaharlardir."
    mp3, hdr = _req(
        f"{api}/tts",
        json.dumps({"text": text, "voice_id": voice["id"], "format": "mp3"}).encode(),
        {"Content-Type": "application/json"},
    )
    (OUT / "2_clone.mp3").write_bytes(mp3)
    print(f"   {hdr.get('x-audio-duration')}s audio, {time.time() - t0:.1f}s da -> outputs/2_clone.mp3")

    print("5) Tozalash...")
    _req(f"{api}/voices/{voice['id']}", method="DELETE")
    print("Hammasi ishladi: OK")


if __name__ == "__main__":
    main()
