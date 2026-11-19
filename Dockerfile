# syntax=docker/dockerfile:1
#
# Two targets, deliberately. See docs/decisions/0009.
#
#   base  - CPU only, ~150MB. Runs phases 1, 3 and 4 (extract, verify,
#           calibrate, report). Extraction is network- and disk-bound and uses
#           no GPU at all, so it must not be forced to carry a CUDA runtime.
#   gpu   - adds the CUDA runtime and torch for phase 2 (estimate), which is
#           the only GPU-bound stage. Several GB larger.
#
# Build the one you need:
#   docker build --target base -t immich-apparent-age:cpu .
#   docker build --target gpu  -t immich-apparent-age:gpu .

ARG PYTHON_VERSION=3.12

# ---------------------------------------------------------------- base (CPU)
FROM python:${PYTHON_VERSION}-slim AS base

LABEL org.opencontainers.image.title="immich-apparent-age" \
      org.opencontainers.image.description="Measures how old faces in an Immich library look, versus how old they actually were" \
      org.opencontainers.image.source="https://github.com/rhamblen/immich-apparent-age" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    IAA_DATA=/data

WORKDIR /app

# Pillow needs libjpeg/zlib at runtime; the slim image ships neither.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libjpeg62-turbo zlib1g \
 && rm -rf /var/lib/apt/lists/*

# Dependencies first, so source edits do not invalidate the wheel layer.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY immich_apparent_age/ ./immich_apparent_age/
COPY extract.py verify.py ./
COPY tests/ ./tests/

# All writes go to the mounted volume, so the image itself needs no writable
# paths and the container can run as an unprivileged user. On Unraid, pass
# user: "99:100" (nobody:users) to match appdata ownership.
RUN mkdir -p /data && chmod 0777 /data
VOLUME ["/data"]

# config.yaml, out/, crops/, reports/ and models/ all live under /data, so a
# single bind mount carries the whole working state between runs and hosts.
ENV IAA_CONFIG=/data/config.yaml

ENTRYPOINT ["python"]
CMD ["extract.py", "--config", "/data/config.yaml", "--probe"]

# ---------------------------------------------------------------- gpu (phase 2)
# Phase 2 is not written yet; this target exists so the deployment story is
# settled and the image can be built the moment estimate.py lands.
#
# CUDA 12.8 is chosen for Blackwell (sm_120) support, so the same image runs on
# the RTX PRO 4000 Blackwell as on the 4000 Ada (sm_89) and the 3060 (sm_86).
FROM nvidia/cuda:12.8.1-runtime-ubuntu24.04 AS gpu

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive \
    IAA_DATA=/data \
    IAA_CONFIG=/data/config.yaml

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-venv libjpeg-turbo8 zlib1g \
 && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt requirements-gpu.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cu128 \
      torch torchvision \
 && pip install --no-cache-dir -r requirements-gpu.txt

COPY immich_apparent_age/ ./immich_apparent_age/
COPY extract.py verify.py ./
COPY tests/ ./tests/

RUN mkdir -p /data && chmod 0777 /data
VOLUME ["/data"]

ENTRYPOINT ["python"]
CMD ["extract.py", "--config", "/data/config.yaml", "--probe"]
