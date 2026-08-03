# syntax=docker/dockerfile:1

# ---- Builder stage --------------------------------------------------------
# Installs dependencies into an isolated prefix so the runtime stage never
# needs a compiler toolchain or pip's build cache.
FROM python:3.11-slim AS builder

WORKDIR /build

RUN pip install --no-cache-dir --upgrade pip

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- Runtime stage ----------------------------------------------------
FROM python:3.11-slim AS runtime

# Non-root user the process runs as. No shell/home needed beyond defaults.
RUN groupadd --system --gid 1000 middleware \
    && useradd --system --uid 1000 --gid middleware --no-create-home middleware

WORKDIR /app

COPY --from=builder /install /usr/local

# Only what the running service needs: the application package and the
# system prompt it loads at startup and refuses to boot without.
COPY app/ ./app/
COPY SYSTEM_PROMPT.md ./SYSTEM_PROMPT.md

RUN chown -R middleware:middleware /app
USER middleware

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
