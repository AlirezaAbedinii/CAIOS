"""Cut the clips together, lay the narration on them, and write the captions.

Runs in the caios/recorder image, after record.py:

    bash demo/recording/run.sh assemble

Each clip's JSON says where its narration lines start and which stretches are
waiting (cut, with a short dissolve) or slow (sped up). This edits every clip,
joins them with crossfades, places every line at the time its cue mapped to,
and writes, in out/final:

    caios-demo.mp4             1080p30, H.264 + AAC, captions as a soft track
    caios-demo-captioned.mp4   the same, with the captions burned in
    caios-demo.srt, .vtt       the captions on their own
    timeline.json              where every clip and line landed

and demo/recording/transcript.md, the narration with its timecodes.
"""
import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import yaml

WORK = Path(__file__).resolve().parent
OUT = WORK / "out"
CLIPS, EDIT, FINAL, AUDIO = OUT / "clips", OUT / "edit", OUT / "final", OUT / "audio"
FPS = 30
XF = 0.5           # dissolve between clips
CUT_XF = 0.3       # dissolve where a wait was cut out of a clip
HEAD = 0.25        # the first frames of a capture, while the page settles
LINE_GAP = 0.3     # least silence between two lines, after the edit
ORDER = ["intro", "b1", "b2a", "b2b", "b2c", "b3a", "b3b", "b4a", "b4b", "b4c",
         "b5a", "b5b", "b6a", "b6b", "b7", "outro"]

NARRATION = yaml.safe_load((WORK / "narration.yaml").read_text())
LINES = {l["id"]: l for b in NARRATION["beats"] for l in b["lines"]}
BEAT_OF = {l["id"]: b for b in NARRATION["beats"] for l in b["lines"]}
# Empty until tts.py has run, so the caption code can be imported and tested
# from a clean checkout (tests/test_recording.py).
TIMING = json.loads((AUDIO / "timing.json").read_text()) if (AUDIO / "timing.json").exists() else {}


def ff(*args):
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-stats", *map(str, args)]
    r = subprocess.run(cmd)
    if r.returncode:
        sys.exit(f"ffmpeg failed: {' '.join(cmd)[:600]}")


def probe_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return float(out.stdout.strip())


# ---------------------------------------------------------------------------
def pieces_of(doc):
    """The stretches of a clip that stay, each with its speed and its join."""
    dur = doc["duration"]
    cuts = sorted((e["from"], e["to"]) for e in doc["events"]
                  if e["type"] == "cut" and e["to"] - e["from"] > 0.4)
    speeds = [(e["from"], e["to"], e["x"]) for e in doc["events"] if e["type"] == "speed"]
    keep, t = [], HEAD
    for a, b in cuts:
        if a > t + 0.05:
            keep.append((t, a))
        t = max(t, b)
    keep.append((t, dur))
    pieces = []
    for k, (a, b) in enumerate(keep):
        marks = sorted({a, b} | {x for s in speeds for x in s[:2] if a < x < b})
        for j, (p, q) in enumerate(zip(marks, marks[1:])):
            x = next((s[2] for s in speeds if s[0] <= p + 1e-6 and q <= s[1] + 1e-6), 1.0)
            join = "cross" if (k > 0 and j == 0) else "hard"
            pieces.append({"a": p, "b": q, "x": x, "join": join})
    cur = 0.0
    for i, p in enumerate(pieces):
        start = 0.0 if i == 0 else (cur - CUT_XF if p["join"] == "cross" else cur)
        p["out"] = start
        cur = start + (p["b"] - p["a"]) / p["x"]
    return pieces, cur


def mapper(pieces, total):
    def f(t):
        for p in pieces:
            if p["a"] <= t < p["b"]:
                return p["out"] + (t - p["a"]) / p["x"]
        for p in pieces:
            if p["a"] >= t:
                return p["out"]
        return total
    return f


def edit_clip(name):
    doc = json.loads((CLIPS / f"{name}.json").read_text())
    if not doc.get("ok", True):
        print(f"  warning: {name} was recorded with an error; retake it")
    pieces, total = pieces_of(doc)
    at = mapper(pieces, total)

    lines, prev_end = [], -1.0
    for e in sorted((e for e in doc["events"] if e["type"] == "say"), key=lambda e: e["t"]):
        t = at(e["t"])
        if t < prev_end + LINE_GAP:
            print(f"  {name}: {e['id']} moved {prev_end + LINE_GAP - t:.2f} s later so it does not overlap")
            t = prev_end + LINE_GAP
        lines.append({"id": e["id"], "t": round(t, 3)})
        prev_end = t + TIMING[e["id"]]["duration"]
    pad = max(0.0, prev_end + 0.5 - total)

    g, labels = [], []
    # The browser window is a pixel short of the display on the right and at
    # the bottom (1440 x 4/3 rounds down); smear the edge rather than show it.
    g.append("[0:v]fillborders=right=1:bottom=1:mode=smear,"
             f"split={len(pieces)}" + "".join(f"[s{i}]" for i in range(len(pieces))))
    for i, p in enumerate(pieces):
        g.append(f"[s{i}]trim=start={p['a']:.3f}:end={p['b']:.3f},"
                 f"setpts=(PTS-STARTPTS)/{p['x']},fps={FPS}[p{i}]")
    cur, cur_dur = "p0", (pieces[0]["b"] - pieces[0]["a"]) / pieces[0]["x"]
    for i, p in enumerate(pieces[1:], 1):
        d = (p["b"] - p["a"]) / p["x"]
        if p["join"] == "cross":
            g.append(f"[{cur}][p{i}]xfade=transition=fade:duration={CUT_XF}:offset={cur_dur - CUT_XF:.3f}[c{i}]")
            cur_dur += d - CUT_XF
        else:
            g.append(f"[{cur}][p{i}]concat=n=2:v=1:a=0[c{i}]")
            cur_dur += d
        cur = f"c{i}"
    tail = f",tpad=stop_mode=clone:stop_duration={pad:.3f}" if pad > 0 else ""
    g.append(f"[{cur}]format=yuv420p{tail}[v]")
    EDIT.mkdir(parents=True, exist_ok=True)
    dst = EDIT / f"{name}.mp4"
    ff("-i", CLIPS / f"{name}.mkv", "-filter_complex", ";".join(g), "-map", "[v]",
       "-c:v", "libx264", "-preset", "medium", "-crf", "14", "-r", FPS, dst)
    return {"clip": name, "duration": probe_duration(dst), "lines": lines}


# ---------------------------------------------------------------------------
def rows(text, width=42):
    """One caption block as at most two rows of similar length, or None."""
    if len(text) <= width:
        return text
    best, score = None, None
    for i, ch in enumerate(text):
        if ch == " " and len(text[:i]) <= width and len(text[i + 1:]) <= width:
            sc = abs(i - len(text) / 2) - (8 if text[i - 1] == "," else 0)
            if best is None or sc < score:
                best, score = i, sc
    return None if best is None else text[:best] + "\n" + text[best + 1:]


def split(text, width):
    """Split a sentence that will not fit two rows, at a comma if one is near the middle."""
    if rows(text, width):
        return [text]
    n = len(text)
    commas = [m.end() for m in re.finditer(r",\s", text) if 0.25 * n < m.end() < 0.78 * n]
    spaces = [m.start() for m in re.finditer(r"\s", text)]
    cut = min(commas or spaces, key=lambda i: abs(i - n / 2))
    return split(text[:cut].strip(), width) + split(text[cut:].strip(), width)


def chunks(text, width=42):
    """Caption blocks for one narration line: sentences, split to fit, tiny ones folded in."""
    text = " ".join(text.split())
    parts = []
    for s in re.split(r"(?<=[.:?!])\s+", text):
        parts += split(s, width)
    out, i = [], 0
    while i < len(parts):
        p = parts[i]
        if len(p) < 18 and i + 1 < len(parts):
            out += split(p + " " + parts[i + 1], width)
            i += 2
        elif len(p) < 18 and out:
            out += split(out.pop() + " " + p, width)
            i += 1
        else:
            out.append(p)
            i += 1
    return [rows(p, width) for p in out]


def srt_time(t, sep=","):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02}{sep}{ms:03}"


def captions(placed):
    cues = []
    for ln in placed:
        words = TIMING[ln["id"]]["words"]
        span0 = words[0]["start"] if words else 0.0
        span1 = words[-1]["end"] if words else TIMING[ln["id"]]["duration"]
        blocks = chunks(LINES[ln["id"]]["text"])
        total = sum(len(b) for b in blocks)
        t = ln["abs"] + span0
        for b in blocks:
            d = (span1 - span0) * len(b) / total
            cues.append([t, t + d + 0.2, b])
            t += d
    for i in range(len(cues) - 1):
        cues[i][1] = min(cues[i][1], cues[i + 1][0] - 0.04)
        if cues[i][1] - cues[i][0] < 1.0:
            cues[i][1] = min(cues[i][0] + 1.0, cues[i + 1][0] - 0.04)
    return cues


def write_captions(cues):
    srt = "\n".join(f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{txt}\n" for i, (a, b, txt) in enumerate(cues, 1))
    (FINAL / "caios-demo.srt").write_text(srt)
    vtt = "WEBVTT\n\n" + "\n".join(f"{srt_time(a, '.')} --> {srt_time(b, '.')}\n{txt}\n" for a, b, txt in cues)
    (FINAL / "caios-demo.vtt").write_text(vtt)


def write_transcript(placed, total):
    def tc(t):
        return f"{int(t // 60)}:{int(t % 60):02}"
    out = ["# CAIOS walkthrough: transcript", "",
           "The narration of the recorded walkthrough, as spoken, with the time each",
           "line starts. Generated by `demo/recording/assemble.py` from",
           "`demo/recording/narration.yaml`; edit that file, not this one.", "",
           f"Running time {tc(total)}. Voice: Kokoro-82M (`{NARRATION['voice']}`), synthesised on",
           "caios_server.", ""]
    beat = None
    for ln in placed:
        b = BEAT_OF[ln["id"]]
        if b is not beat:
            beat = b
            out += ["", f"## {tc(ln['abs'])} · {b['title']}", ""]
        text = " ".join(LINES[ln["id"]]["text"].split())
        out.append(f"**{tc(ln['abs'])}** {text}  ")
    out += ["", "## The narration as one text", ""]
    for b in NARRATION["beats"]:
        out += [" ".join(" ".join(l["text"].split()) for l in b["lines"]), ""]
    (WORK / "transcript.md").write_text("\n".join(out).rstrip() + "\n")


# ---------------------------------------------------------------------------
def main():
    FINAL.mkdir(parents=True, exist_ok=True)
    clips = []
    for name in ORDER:
        if not (CLIPS / f"{name}.json").exists():
            sys.exit(f"missing clip {name}: bash demo/recording/run.sh record {name}")
        print(f"== {name}", flush=True)
        clips.append(edit_clip(name))

    offset, placed = 0.0, []
    for i, c in enumerate(clips):
        c["offset"] = round(offset, 3)
        for ln in c["lines"]:
            placed.append({"id": ln["id"], "abs": round(offset + ln["t"], 3), "clip": c["clip"]})
        offset += c["duration"] - (XF if i < len(clips) - 1 else 0)
    total = offset
    prev_end = -1.0
    for ln in placed:
        if ln["abs"] < prev_end + LINE_GAP:
            print(f"  {ln['id']} moved {prev_end + LINE_GAP - ln['abs']:.2f} s later across a join")
            ln["abs"] = round(prev_end + LINE_GAP, 3)
        prev_end = ln["abs"] + TIMING[ln["id"]]["duration"]
    if prev_end + 0.8 > total:
        sys.exit(f"the last line ends at {prev_end:.1f} s, after the picture ({total:.1f} s)")

    # The picture: every edited clip, dissolving into the next.
    print("== picture", flush=True)
    args, g = [], []
    for c in clips:
        args += ["-i", EDIT / f"{c['clip']}.mp4"]
    cur, cur_dur = "0:v", clips[0]["duration"]
    for i, c in enumerate(clips[1:], 1):
        g.append(f"[{cur}][{i}:v]xfade=transition=fade:duration={XF}:offset={cur_dur - XF:.3f}[x{i}]")
        cur, cur_dur = f"x{i}", cur_dur + c["duration"] - XF
    g.append(f"[{cur}]fade=t=in:st=0:d=0.6,fade=t=out:st={total - 1.0:.3f}:d=1.0,format=yuv420p[v]")
    picture = OUT / "picture.mp4"
    ff(*args, "-filter_complex", ";".join(g), "-map", "[v]", "-c:v", "libx264", "-preset", "slow",
       "-crf", "17", "-r", FPS, "-movflags", "+faststart", picture)

    # The voice: every line where its cue landed.
    print("== voice", flush=True)
    args, g = [], []
    for i, ln in enumerate(placed):
        args += ["-i", AUDIO / f"{ln['id']}.wav"]
        g.append(f"[{i}:a]adelay=delays={int(ln['abs'] * 1000)}:all=1[a{i}]")
    g.append("".join(f"[a{i}]" for i in range(len(placed))) +
             f"amix=inputs={len(placed)}:normalize=0,highpass=f=70,apad=whole_dur={total:.3f},"
             "aresample=48000,loudnorm=I=-16:TP=-1.5:LRA=11,pan=stereo|c0=c0|c1=c0[a]")
    voice = OUT / "voice.wav"
    ff(*args, "-filter_complex", ";".join(g), "-map", "[a]", "-t", f"{total:.3f}", "-ar", 48000, voice)

    cues = captions(placed)
    write_captions(cues)
    write_transcript(placed, total)

    print("== final", flush=True)
    final = FINAL / "caios-demo.mp4"
    ff("-i", picture, "-i", voice, "-i", FINAL / "caios-demo.srt", "-map", "0:v", "-map", "1:a", "-map", "2:s",
       "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-c:s", "mov_text", "-metadata:s:s:0", "language=eng",
       "-metadata", "title=CAIOS platform walkthrough", "-movflags", "+faststart", final)
    style = ("FontName=IBM Plex Sans,FontSize=12,PrimaryColour=&H00FFFFFF,BackColour=&H3029210A,"
             "BorderStyle=3,Outline=5,Shadow=0,MarginV=22,Alignment=2")
    ff("-i", picture, "-i", voice, "-vf", f"subtitles={FINAL / 'caios-demo.srt'}:force_style='{style}'",
       "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "slow", "-crf", "17",
       "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", FINAL / "caios-demo-captioned.mp4")

    (FINAL / "timeline.json").write_text(json.dumps({"duration": round(total, 3), "clips": clips,
                                                     "lines": placed}, indent=1))
    print(f"  {final}  {int(total // 60)}:{int(total % 60):02}, {len(placed)} lines, {len(cues)} captions")


if __name__ == "__main__":
    main()
