"""The README's two pieces of the recording: a looping preview and a light video.

Runs in the caios/recorder image, after assemble.py:

    bash demo/recording/run.sh readme-media

Writes (run.sh copies the logo and preview into docs/assets/ afterwards,
because the container sees the rest of the repository read-only)
    out/final/caios-logo-{light,dark}.png   the README header
    out/final/architecture-{light,dark}.png the README's How it works diagram
    out/final/demo-preview.gif        about 20 s, silent, one labelled moment per tier
    out/final/caios-demo-720p.mp4     the narrated walkthrough with captions burned
                                      in, under 10 MB, the most GitHub's editor
                                      takes as an attachment it plays inline

The moments are chosen by clip and time within the clip, so a retake that
shifts a clip moves its moment with it.
"""
import json
import subprocess
import sys
from pathlib import Path

WORK = Path(__file__).resolve().parent
OUT = WORK / "out"
GIF = OUT / "final" / "demo-preview.gif"
LIGHT = OUT / "final" / "caios-demo-720p.mp4"
FONT = "/usr/share/fonts/truetype/ibm-plex/IBMPlexSans-Medium.ttf"
LIMIT = 9.6 * 1024 * 1024

# (clip, from, to, label): seconds within the edited clip.
MOMENTS = [
    ("b1", 18.4, 22.0, "Three ways to work: no code, low code, high code"),
    ("b3b", 8.4, 12.2, "No code: a private language model on the lab's GPU"),
    ("b4c", 5.0, 8.4, "Low code: a serverless model, one request"),
    ("b5b", 5.0, 8.4, "High code: the same model in JupyterLab"),
    ("b6a", 13.5, 18.5, "Federated learning: three hospitals, no data moved"),
    ("b6b", 1.5, 4.8, "Federated 0.853, best single hospital 0.806"),
]


def ff(*args):
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *map(str, args)])
    if r.returncode:
        sys.exit("ffmpeg failed")


def preview():
    timeline = json.loads((OUT / "final" / "timeline.json").read_text())
    offset = {c["clip"]: c["offset"] for c in timeline["clips"]}
    parts = []
    for i, (clip, a, b, label) in enumerate(MOMENTS):
        start = offset[clip] + a
        text = label.replace(":", "\\:").replace("'", "’")
        parts.append(
            f"[0:v]trim=start={start:.2f}:end={start + b - a:.2f},setpts=PTS-STARTPTS,"
            f"scale=960:-1:flags=lanczos,fps=12,"
            f"drawtext=fontfile={FONT}:text='{text}':fontsize=19:fontcolor=white:"
            f"box=1:boxcolor=0x0a2129@0.92:boxborderw=10:x=22:y=h-th-26[m{i}]")
    graph = ";".join(parts) + ";" + "".join(f"[m{i}]" for i in range(len(MOMENTS))) + \
        f"concat=n={len(MOMENTS)}:v=1:a=0,split[a][b];" \
        "[a]palettegen=max_colors=160:stats_mode=diff[p];" \
        "[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle[v]"
    GIF.parent.mkdir(parents=True, exist_ok=True)
    ff("-i", OUT / "picture.mp4", "-filter_complex", graph, "-map", "[v]", "-loop", "0", GIF)
    print(f"  {GIF.relative_to(WORK)}  {GIF.stat().st_size / 1e6:.1f} MB")


def draw(card, name, width):
    """A card from cards/, light and dark, at 2x, on a transparent background."""
    import asyncio
    from playwright.async_api import async_playwright

    async def go():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page(device_scale_factor=2, viewport={"width": width, "height": 400})
            for theme in ("light", "dark"):
                await page.goto(f"file://{WORK}/cards/{card}?theme={theme}")
                await page.evaluate("document.fonts.ready")
                await page.wait_for_timeout(500)
                dst = OUT / "final" / f"{name}-{theme}.png"
                await page.locator("body").screenshot(path=str(dst), omit_background=True)
                print(f"  {dst.relative_to(WORK)}")
            await browser.close()
    asyncio.run(go())


def logo():
    """The README header, drawn with the dashboard's typeface."""
    draw("logo.html", "caios-logo", 900)


def architecture():
    """The README's How it works diagram."""
    draw("architecture.html", "architecture", 1240)


def light():
    src = OUT / "final" / "caios-demo-captioned.mp4"
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", str(src)], capture_output=True, text=True).stdout)
    audio_kbps = 64
    video_kbps = int(LIMIT * 8 / 1000 / dur * 0.96) - audio_kbps
    common = ["-vf", "scale=1280:-2:flags=lanczos", "-c:v", "libx264", "-preset", "slow",
              "-b:v", f"{video_kbps}k", "-tune", "stillimage", "-pix_fmt", "yuv420p"]
    log = OUT / "x264-2pass"
    ff("-i", src, *common, "-pass", "1", "-passlogfile", log, "-an", "-f", "null", "/dev/null")
    ff("-i", src, *common, "-pass", "2", "-passlogfile", log, "-c:a", "aac", "-b:a", f"{audio_kbps}k",
       "-ac", "1", "-movflags", "+faststart", LIGHT)
    size = LIGHT.stat().st_size
    print(f"  {LIGHT.relative_to(WORK)}  {size / 1e6:.1f} MB at {video_kbps} kb/s")
    if size > 10 * 1024 * 1024:
        sys.exit("over GitHub's 10 MB attachment limit for inline video")


if __name__ == "__main__":
    which = sys.argv[1:] or ["logo", "architecture", "preview", "light"]
    if "logo" in which:
        logo()
    if "architecture" in which:
        architecture()
    if "preview" in which:
        preview()
    if "light" in which:
        light()
