# The narrator: Kokoro-82M (Apache-2.0), run locally on CPU. The script's
# text never leaves this machine.
FROM python:3.11-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends espeak-ng ffmpeg \
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir kokoro==0.9.4 soundfile==0.12.1 pyyaml==6.0.2 \
 && python -m spacy download en_core_web_sm

WORKDIR /work
