"""Speak narration.yaml, one WAV per line, with word timings.

Runs in the caios/tts image (docker/tts), on CPU:

    bash demo/recording/run.sh tts

Writes out/audio/<line-id>.wav at 24 kHz and out/audio/timing.json, which
record.py reads to pace each take and assemble.py reads to place each line.
The model and voices are fetched from Hugging Face once, into out/hf-cache.
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import yaml
from kokoro import KPipeline

HERE = Path(__file__).resolve().parent
OUT = HERE / "out" / "audio"
RATE = 24000


def spoken(line, lexicon):
    text = " ".join(line.get("speak", line["text"]).split())
    for word, repl in lexicon.items():
        text = re.sub(rf"\b{re.escape(word)}\b", repl, text)
    return text


def main(only=None):
    doc = yaml.safe_load((HERE / "narration.yaml").read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    timing_path = OUT / "timing.json"
    timing = json.loads(timing_path.read_text()) if timing_path.exists() else {}
    pipe = KPipeline(lang_code=doc["lang"], repo_id="hexgrad/Kokoro-82M")

    for beat in doc["beats"]:
        for line in beat["lines"]:
            if only and line["id"] not in only:
                continue
            text = spoken(line, doc.get("lexicon", {}))
            chunks, words, phonemes, offset = [], [], [], 0.0
            for r in pipe(text, voice=doc["voice"], speed=doc["speed"]):
                audio = r.audio.numpy()
                for t in r.tokens or []:
                    if t.start_ts is not None:
                        words.append({"w": t.text, "start": round(offset + t.start_ts, 3),
                                      "end": round(offset + t.end_ts, 3)})
                phonemes.append(r.phonemes)
                chunks.append(audio)
                offset += len(audio) / RATE
            audio = np.concatenate(chunks)
            sf.write(OUT / f"{line['id']}.wav", audio, RATE, subtype="PCM_16")
            timing[line["id"]] = {"duration": round(len(audio) / RATE, 3), "words": words,
                                  "phonemes": " ".join(phonemes), "spoken": text}
            print(f"{line['id']}  {len(audio) / RATE:5.2f}s  {line['text'][:60]}")

    timing_path.write_text(json.dumps(timing, indent=1, ensure_ascii=False))
    total = sum(v["duration"] for v in timing.values())
    print(f"{len(timing)} lines, {total:.1f} s of speech")


if __name__ == "__main__":
    main(set(sys.argv[1:]) or None)
