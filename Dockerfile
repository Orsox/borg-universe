FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV APP_HOST=0.0.0.0
ENV APP_PORT=8000
ENV DEBIAN_FRONTEND=noninteractive
ARG INSTALL_ARM_GCC=true
ARG INSTALL_EMBEDDED_PY_TOOLS=true
ARG INSTALL_PLATFORMIO=false

WORKDIR /app
RUN mkdir -p /app/BORG /app/artifacts /app/.claude

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        ccache \
        cmake \
        curl \
        device-tree-compiler \
        dfu-util \
        file \
        git \
        git-lfs \
        gperf \
        ninja-build \
        nodejs \
        npm \
        pkg-config \
        xz-utils \
    && if [ "$INSTALL_ARM_GCC" = "true" ]; then apt-get install -y --no-install-recommends gcc-arm-none-eabi; fi \
    && npm install -g @anthropic-ai/claude-code \
    && claude --version \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-embedded.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN if [ "$INSTALL_EMBEDDED_PY_TOOLS" = "true" ]; then pip install --no-cache-dir -r requirements-embedded.txt; fi \
    && if [ "$INSTALL_PLATFORMIO" = "true" ]; then pip install --no-cache-dir platformio==6.1.19; fi

COPY app ./app
COPY mcp_server ./mcp_server
COPY agents ./agents
COPY skills ./skills
COPY BORG ./BORG
COPY main.py .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"APP_PORT\", \"8000\")}/health', timeout=2).read()"

CMD ["sh", "-c", "uvicorn app.main:app --host ${APP_HOST:-0.0.0.0} --port ${APP_PORT:-8000}"]
