FROM python:3.15-alpine AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /uvx /bin/

RUN apk add --no-cache build-base

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

COPY app ./app

FROM python:3.15-alpine AS runtime

# sqlite-libs solo existe por el stdlib sqlite3, que el servicio no usa (MongoDB).
# .python-rundeps es el metapaquete virtual que la protege; al quitarlo, apk
# purga ademas otras libs de runtime sin uso (ncurses, readline...). El unico
# efecto es que `import sqlite3` deja de funcionar. Revertir si se necesitara.
RUN apk upgrade --no-cache && apk del .python-rundeps sqlite-libs

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN addgroup -S app && adduser -S -G app -H app

COPY --from=builder --chown=app:app /app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"]

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
