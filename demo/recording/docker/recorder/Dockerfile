# The recorder: a real Chromium on a virtual display, captured by ffmpeg.
# Playwright drives the browser; x11grab records what it draws.
FROM mcr.microsoft.com/playwright/python:v1.59.0-noble

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ffmpeg xvfb libnss3-tools fonts-dejavu-core fonts-liberation fonts-noto-core fonts-ibm-plex \
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir --break-system-packages playwright==1.59.0 pyyaml==6.0.2

WORKDIR /work
