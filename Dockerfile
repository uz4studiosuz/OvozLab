# OvozLab API serveri (Linux + NVIDIA GPU).
#   docker compose up -d --build
# PyTorch cu128 g'ildiraklari CUDA kutubxonalarini o'zi bilan olib keladi, hostda faqat NVIDIA drayveri
# va nvidia-container-toolkit kerak.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_HTTP_TIMEOUT=60 \
    UV_HTTP_RETRIES=10 \
    UV_CONCURRENT_DOWNLOADS=8 \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    OVOZLAB_HOME=/data \
    OVOZLAB_SERVER=1 \
    OVOZLAB_DEVICE=cuda

WORKDIR /app

# Avval faqat bog'liqliklar — kod o'zgarganda og'ir PyTorch qatlami qayta yuklanmaydi.
# Internet uzilib-ulanib tursa: qayta urinadi, yuklangan fayllar uv keshida qoladi.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    for i in 1 2 3 4 5 6; do \
      uv sync --frozen --no-dev --extra cuda --no-install-project && exit 0; \
      echo "uv sync urinish $i muvaffaqiyatsiz, qayta..."; sleep 10; \
    done; exit 1

COPY ovozlab ./ovozlab
COPY omnivoice ./omnivoice
COPY website ./website
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra cuda

VOLUME ["/data"]
EXPOSE 8020
CMD ["python", "-m", "ovozlab.serve", "--host", "0.0.0.0", "--port", "8020"]
