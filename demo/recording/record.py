"""Record the CAIOS walkthrough, one clip at a time.

Runs in the caios/recorder image, through run.sh, which starts a virtual
display and mounts the repository:

    bash demo/recording/run.sh setup            # sign the three profiles in, off camera
    bash demo/recording/run.sh record           # every clip, in order
    bash demo/recording/run.sh record b3b b4c   # just those, to retake them

A real Chromium draws on the virtual display and ffmpeg records it. Playwright
drives the browser; the pointer you see is drawn by the page itself, because
Playwright's pointer is synthetic and the display has none.

Each clip is paced by the narration. `take.say(line)` notes when a line starts
and holds the next one until it has finished, so the voice never runs over
itself and every action lands on its words. Each clip leaves
out/clips/<clip>.mkv and out/clips/<clip>.json: the line cues, and the
stretches to cut or speed up. assemble.py does the rest.

The browser profiles, one per person on screen, live in out/profiles:

    anon  nobody, for beat 1; recreated at every take
    a   the colleague who signs up in beat 2
    b   Platform Administrator, who approves them
    c   researcher (Dana Okafor), for beats 3 to 7
"""
import asyncio
import json
import math
import os
import random
import re
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.async_api import Locator, async_playwright

WORK = Path(__file__).resolve().parent
OUT = WORK / "out"
CLIPS = OUT / "clips"
PROFILES = OUT / "profiles"
CARDS = f"file://{WORK}/cards"
DISPLAY = os.environ.get("DISPLAY", ":99")
W, H, SCALE = 1920, 1080, 4 / 3          # 1440 x 810 CSS pixels, drawn at 1080p
FPS = 30
GAP = 0.5                                # silence between two narration lines

TIMING = json.loads((OUT / "audio" / "timing.json").read_text())


def load_env(path):
    env = {}
    for line in Path(path).read_text().splitlines():
        m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line.strip())
        if m:
            v = m.group(2).strip().strip("'\"")
            env[m.group(1)] = re.sub(r"\$\{(\w+)\}", lambda x: env.get(x.group(1), ""), v)
    return env


E = load_env("/caios.env")
BASE = f"https://{E['CAIOS_DASHBOARD_HOST']}"
PANES = json.loads((OUT / "term" / "panes.json").read_text()) if (OUT / "term" / "panes.json").exists() else []

# The colleague who signs up on camera. Fictional, at a reserved domain.
NEWCOMER = {"first": "Maya", "last": "Tremblay", "user": "mtremblay",
            "email": "maya.tremblay@example.org"}
NEWCOMER_PW = OUT / "newcomer.pw"      # read back by b2c; deleted with the account
NOTE = ("Summarise this radiology note in one sentence: T2 hyperintense lesion, left "
        "periventricular white matter, 8mm, stable versus prior study.")
CURL = ('curl -s -H "Authorization: Bearer $TOKEN" --data @portrait.json "$ENDPOINT"'
        ' | python3 -m json.tool')


# ---------------------------------------------------------------------------
# What the page draws for the recording: the pointer, a ring on each click,
# and the chapter card. Plus three screen-only corrections, each for a
# reason a viewer should not have to think about:
#   - the module page's build badge is upstream's CI, not ours, and reads
#     "aborted" (jenkins.cloud.ai4eosc.eu);
#   - the admin page's decided list names real people, so it is blurred;
#   - Open WebUI's "a new version is available" toast.
OVERLAY = r"""
(() => {
  if (window.top !== window || window.__rec) return;
  window.__rec = true;
  const host = location.host;
  let css = `
    #__cursor{position:fixed;left:0;top:0;width:30px;height:30px;z-index:2147483647;pointer-events:none;
      transform:translate(-200px,-200px);transition:opacity .25s}
    #__cursor svg{filter:drop-shadow(0 2px 3px rgba(0,0,0,.28));transition:transform .08s}
    #__cursor.down svg{transform:scale(.88)}
    #__cursor.hidden{opacity:0}
    .__ring{position:fixed;z-index:2147483646;pointer-events:none;width:44px;height:44px;margin:-22px 0 0 -22px;
      border-radius:50%;border:2px solid rgba(55,207,228,.95);background:rgba(55,207,228,.16);
      animation:__ring .55s ease-out forwards}
    @keyframes __ring{from{transform:scale(.25);opacity:1}to{transform:scale(1.25);opacity:0}}
    #__chapter{position:fixed;left:44px;bottom:40px;z-index:2147483600;pointer-events:none;
      font-family:'IBM Plex Sans',sans-serif;color:#e4edef;background:rgba(10,33,41,.95);
      padding:15px 28px 17px 22px;border-left:4px solid #37cfe4;border-radius:2px;
      box-shadow:0 12px 34px rgba(0,0,0,.26);opacity:0;transform:translateY(14px);
      transition:opacity .5s ease,transform .5s cubic-bezier(.2,0,.2,1)}
    #__chapter.show{opacity:1;transform:none}
    #__chapter .k{font-family:'IBM Plex Mono',monospace;font-size:12px;letter-spacing:.2em;
      text-transform:uppercase;color:#80d2dc;margin-bottom:5px}
    #__chapter .t{font-size:23px;font-weight:500;letter-spacing:.005em}
    *{scrollbar-width:none!important}
    ::-webkit-scrollbar{width:0!important;height:0!important;display:none!important}
  `;
  if (host.startsWith('dashboard.')) css += `
    img[src*="jenkins"]{visibility:hidden!important}
    section.admin-section ~ section.admin-section .admin-rows{filter:blur(7px)}
  `;
  if (host.startsWith('ui-')) {
    css += `li[data-sonner-toast]{display:none!important}`;
    // Open WebUI checks GitHub for releases and says so in a corner banner.
    const hideUpdate = () => document.querySelectorAll('div, span, p').forEach(el => {
      if (el.childElementCount > 3 || !/^A new version \(v[\d.]+\) is now available/.test(el.textContent.trim())) return;
      let box = el;
      for (let i = 0; i < 6 && box.parentElement; i++) {
        const pos = getComputedStyle(box).position;
        if (pos === 'fixed' || pos === 'absolute') break;
        box = box.parentElement;
      }
      box.style.setProperty('display', 'none', 'important');
    });
    new MutationObserver(hideUpdate).observe(document, {childList: true, subtree: true});
  }
  if (host.startsWith('ide-')) {
    css += `.jp-RenderedImage img{max-height:520px!important;width:auto!important}`;
    // ultralytics imports tqdm.auto, which warns that ipywidgets is missing.
    // Harmless, and red on screen; hidden in the recording only.
    const quiet = () => document.querySelectorAll('.jp-OutputArea-child').forEach(c => {
      if (c.style.display !== 'none' && /TqdmWarning: IProgress not found/.test(c.textContent)) c.style.display = 'none';
    });
    new MutationObserver(quiet).observe(document, {childList: true, subtree: true});
  }
  const ARROW = '<svg width="30" height="30" viewBox="0 0 30 30"><path d="M6 3.5 L6 23.5 L11.2 18.8 L14.8 26.6 L18.6 25 L15.1 17.4 L22 17.4 Z" fill="#fff" stroke="#0b2027" stroke-width="1.7" stroke-linejoin="round"/></svg>';
  const place = (x, y) => {
    window.__recPos = [x, y];
    const c = document.getElementById('__cursor');
    if (c) c.style.transform = `translate(${x - 6}px, ${y - 3.5}px)`;
  };
  const mount = () => {
    const root = document.documentElement;
    if (!root) return;
    if (!document.getElementById('__rec_style')) {
      const s = document.createElement('style'); s.id = '__rec_style'; s.textContent = css; root.appendChild(s);
    }
    if (!document.getElementById('__cursor')) {
      const c = document.createElement('div'); c.id = '__cursor'; c.innerHTML = ARROW; root.appendChild(c);
      if (window.__recPos) place(...window.__recPos);
      if (window.__recHidden) c.classList.add('hidden');
    }
  };
  addEventListener('mousemove', e => place(e.clientX, e.clientY), true);
  addEventListener('mousedown', e => {
    const r = document.createElement('div'); r.className = '__ring';
    r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px';
    document.documentElement.appendChild(r); setTimeout(() => r.remove(), 700);
    document.getElementById('__cursor')?.classList.add('down');
  }, true);
  addEventListener('mouseup', () => document.getElementById('__cursor')?.classList.remove('down'), true);
  window.__recCursor = (show) => {
    window.__recHidden = !show;
    document.getElementById('__cursor')?.classList.toggle('hidden', !show);
  };
  window.__recChapter = (kicker, title, ms) => {
    mount();
    let el = document.getElementById('__chapter');
    if (!el) { el = document.createElement('div'); el.id = '__chapter'; document.documentElement.appendChild(el); }
    el.innerHTML = '<div class="k"></div><div class="t"></div>';
    el.querySelector('.k').textContent = kicker; el.querySelector('.t').textContent = title;
    requestAnimationFrame(() => el.classList.add('show'));
    setTimeout(() => el.classList.remove('show'), ms || 4200);
  };
  document.addEventListener('DOMContentLoaded', mount);
  mount();
  setInterval(mount, 400);
})();
"""


# ---------------------------------------------------------------------------
class Capture:
    """ffmpeg recording the virtual display, with its first frame's time."""

    def __init__(self, path):
        self.path = path
        self.proc = None
        self.t0 = None

    async def start(self):
        self.proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-framerate", str(FPS),
            "-video_size", f"{W}x{H}", "-draw_mouse", "0", "-i", f"{DISPLAY}.0+0,0",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "10", "-pix_fmt", "yuv444p",
            "-g", str(FPS * 2), "-progress", "pipe:1", "-nostats", str(self.path),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
        while True:
            line = (await self.proc.stdout.readline()).decode()
            if not line:
                raise RuntimeError("ffmpeg stopped before recording a frame")
            if line.startswith("frame="):
                n = int(line.split("=")[1])
                if n > 0:
                    self.t0 = time.monotonic() - n / FPS
                    break
        asyncio.create_task(self._drain())

    async def _drain(self):
        while self.proc and await self.proc.stdout.readline():
            pass

    async def stop(self):
        self.proc.stdin.write(b"q")
        await self.proc.stdin.drain()
        self.proc.stdin.close()
        await self.proc.wait()


class Take:
    """One clip: the capture, and the narration cues that pace it."""

    def __init__(self, rec, name):
        self.rec, self.name = rec, name
        self.events = []
        self.speech_end = 0.0
        self.cap = Capture(CLIPS / f"{name}.mkv")

    async def __aenter__(self):
        CLIPS.mkdir(parents=True, exist_ok=True)
        await self.cap.start()
        await self.hold(0.6)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.until(self.speech_end + 0.2)
        end = self.now()
        await self.cap.stop()
        doc = {"clip": self.name, "duration": round(end, 3), "events": self.events,
               "ok": exc_type is None}
        (CLIPS / f"{self.name}.json").write_text(json.dumps(doc, indent=1))
        state = "ok" if exc_type is None else f"FAILED: {exc!r}"[:300]
        print(f"  {self.name:<8} {end:6.1f} s  {state}", flush=True)
        return False

    def now(self):
        return time.monotonic() - self.cap.t0

    async def until(self, t):
        d = t - self.now()
        if d > 0:
            await asyncio.sleep(d)

    async def hold(self, s):
        await asyncio.sleep(s)

    async def say(self, line, gap=GAP):
        """Start a line once the previous one has finished."""
        if self.events and any(e["type"] == "say" for e in self.events):
            await self.until(self.speech_end + gap)
        t = self.now()
        self.events.append({"type": "say", "id": line, "t": round(t, 3)})
        self.speech_end = t + TIMING[line]["duration"]

    def _last_say(self, line):
        for e in reversed(self.events):
            if e["type"] == "say" and e["id"] == line:
                return e["t"]
        raise KeyError(line)

    async def word(self, line, word, nth=1, lead=0.12):
        """Wait until `word` of `line` is being spoken (less a small lead)."""
        start = self._last_say(line)
        seen = 0
        for w in TIMING[line]["words"]:
            if w["w"].lower().strip(".,:;") == word.lower():
                seen += 1
                if seen == nth:
                    await self.until(start + w["start"] - lead)
                    return
        raise KeyError(f"{word!r} not in {line}")

    async def spoken(self, extra=0.0):
        await self.until(self.speech_end + extra)

    def cut(self, a, b):
        self.events.append({"type": "cut", "from": round(a, 3), "to": round(b, 3)})

    def speed(self, a, b, x):
        self.events.append({"type": "speed", "from": round(a, 3), "to": round(b, 3), "x": x})


# ---------------------------------------------------------------------------
class Recorder:
    def __init__(self, pw):
        self.pw = pw
        self.ctx = None
        self.profile = None
        self.page = None
        self.pos = (720.0, 470.0)

    async def use(self, profile, fresh=False):
        if self.profile == profile and not fresh:
            return self.page
        if self.ctx:
            await self.ctx.close()
        path = PROFILES / profile
        if fresh and path.exists():
            shutil.rmtree(path)
        (path / "Default").mkdir(parents=True, exist_ok=True)
        prefs = path / "Default" / "Preferences"
        p = json.loads(prefs.read_text()) if prefs.exists() else {}
        p.setdefault("profile", {})["password_manager_enabled"] = False
        p["credentials_enable_service"] = False
        p.setdefault("profile", {})["exit_type"] = "Normal"
        p.setdefault("translate", {})["enabled"] = False
        prefs.write_text(json.dumps(p))
        self.ctx = await self.pw.chromium.launch_persistent_context(
            str(path), headless=False, no_viewport=True, ignore_https_errors=True,
            ignore_default_args=["--enable-automation"],
            args=["--kiosk", f"--window-size={round(W / SCALE) + 1},{round(H / SCALE) + 1}", "--window-position=0,0",
                  f"--force-device-scale-factor={SCALE}", "--no-first-run",
                  "--disable-features=Translate,PasswordLeakDetection,MediaRouter",
                  "--disable-session-crashed-bubble", "--hide-crash-restore-bubble",
                  "--password-store=basic", "--hide-scrollbars"])
        await self.ctx.add_init_script(OVERLAY)
        pages = self.ctx.pages
        self.page = pages[0] if pages else await self.ctx.new_page()
        for extra in pages[1:]:
            await extra.close()
        self.profile = profile
        return self.page

    # --- navigation -------------------------------------------------------
    async def goto(self, url, settle=1.5):
        await self.page.goto(url, wait_until="networkidle", timeout=60000)
        await asyncio.sleep(settle)
        await self.page.mouse.move(*self.pos)

    async def js(self, code, arg=None):
        return await self.page.evaluate(code, arg)

    async def chapter(self, kicker, title, ms=4200):
        await self.js("([k, t, ms]) => window.__recChapter && window.__recChapter(k, t, ms)",
                      [kicker, title, ms])

    async def cursor(self, show):
        await self.js("(s) => window.__recCursor && window.__recCursor(s)", show)

    # --- the pointer ------------------------------------------------------
    async def glide(self, x, y, dur=None):
        x0, y0 = self.pos
        dist = math.hypot(x - x0, y - y0)
        if dist < 1:
            return
        dur = dur or min(1.0, 0.28 + dist / 1800)
        steps = max(8, int(dur * 60))
        # A slight arc, the way a hand moves a mouse.
        bend = min(40.0, dist * 0.08) * random.choice((-1, 1))
        nx, ny = -(y - y0) / dist, (x - x0) / dist
        t0 = time.monotonic()
        for i in range(1, steps + 1):
            s = i / steps
            e = 4 * s ** 3 if s < 0.5 else 1 - (-2 * s + 2) ** 3 / 2
            arc = math.sin(math.pi * e) * bend
            await self.page.mouse.move(x0 + (x - x0) * e + nx * arc, y0 + (y - y0) * e + ny * arc)
            lag = t0 + dur * s - time.monotonic()
            if lag > 0:
                await asyncio.sleep(lag)
        self.pos = (x, y)

    async def centre(self, target):
        loc = target if isinstance(target, Locator) else self.page.locator(target)
        loc = loc.first
        await loc.scroll_into_view_if_needed(timeout=15000)
        box = await loc.bounding_box()
        return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2

    async def hover(self, target, dur=None):
        await self.glide(*(await self.centre(target)), dur)

    async def click(self, target, pause=0.16, dur=None):
        await self.hover(target, dur)
        await asyncio.sleep(pause)
        await self.page.mouse.down()
        await asyncio.sleep(0.08)
        await self.page.mouse.up()
        await asyncio.sleep(0.1)

    async def type(self, text, cps=16.0):
        """Type at a human pace: about `cps` characters a second, uneven."""
        for ch in text:
            await self.page.keyboard.type(ch)
            await asyncio.sleep(random.uniform(0.55, 1.45) / cps)

    async def scroll_to(self, selector, block="center"):
        await self.js("([s, b]) => document.querySelector(s)?.scrollIntoView({behavior: 'smooth', block: b})",
                      [selector, block])

    def take(self, name):
        return Take(self, name)


# ---------------------------------------------------------------------------
# Off camera: sign each profile in, and put every page where a take expects it.
async def setup(rec):
    page = await rec.use("b")
    await rec.goto(BASE + "/")
    if await page.get_by_text("Login - Register").count():
        await page.get_by_text("Login - Register").click()
        await page.wait_for_load_state("networkidle")
        await page.fill("#username", "platform-admin")
        await page.fill("#password", E["CAIOS_PW_PLATFORM_ADMIN"])
        await page.click("#kc-login")
        await page.wait_for_load_state("networkidle")
    print("  b  signed in as Platform Administrator")

    page = await rec.use("c")
    await rec.goto(BASE + "/")
    if await page.get_by_text("Login - Register").count():
        await page.get_by_text("Login - Register").click()
        await page.wait_for_load_state("networkidle")
        await page.fill("#username", "researcher")
        await page.fill("#password", E["CAIOS_PW_RESEARCHER"])
        await page.click("#kc-login")
        await page.wait_for_load_state("networkidle")
    links = await quick_access(rec)
    print("  c  signed in as researcher")

    await rec.goto(links["Private language model"])
    if "/auth" in page.url:
        await page.fill("input[type=email]", E["CAIOS_DEMO_UI_EMAIL"])
        await page.fill("input[type=password]", E["CAIOS_DEMO_UI_PASSWORD"])
        await page.get_by_role("button", name="Sign in").click()
        await asyncio.sleep(4)
    await tidy_chat(rec)
    print("  c  signed in to the chat")

    await rec.goto(links["YOLO notebook"])
    if "/login" in page.url:
        await page.fill("input[type=password]", E["CAIOS_FL_IDE_PASSWORD"])
        await page.click("button[type=submit], #login_submit")
        await asyncio.sleep(5)
    print("  c  signed in to JupyterLab")
    await rec.use("a", fresh=True)
    print("  a  fresh, signed out")


async def quick_access(rec):
    await rec.goto(BASE + "/tasks/deployments", settle=2.5)
    rows = await rec.js("""() => Object.fromEntries([...document.querySelectorAll('mat-row')].map(r =>
        [r.querySelector('mat-cell').innerText.trim(), (r.querySelector('#quickAccessButton') || {}).href]))""")
    return rows


async def tidy_chat(rec):
    """Close Open WebUI's release notes and update toast, if showing."""
    page = rec.page
    for label in ("Okay, Let's Go!",):
        b = page.get_by_text(label)
        if await b.count():
            await b.first.click()
            await asyncio.sleep(0.5)
    toast = page.locator("li[data-sonner-toast]", has_text="new version")
    if await toast.count():
        await toast.locator("button").last.click()
        await asyncio.sleep(0.5)


class Retake(Exception):
    """The take ran, but what it shows is not what the script says."""


async def chat_answer(page, timeout=60):
    """The assistant's reply, once it has stopped growing."""
    js = """() => { const c = [...document.querySelectorAll('#response-content-container')];
                   return c.length ? c[c.length - 1].innerText.trim() : ''; }"""
    last, stable, end = "", 0, time.monotonic() + timeout
    while time.monotonic() < end:
        now = await page.evaluate(js)
        stable = stable + 1 if now and now == last else 0
        if stable >= 4:
            return now
        last = now
        await asyncio.sleep(0.25)
    return last


async def same_tab(rec, selector):
    """Quick access opens a new tab; on camera it should open in this one."""
    await rec.js("(s) => document.querySelectorAll(s).forEach(a => a.removeAttribute('target'))", selector)


# ---------------------------------------------------------------------------
# The clips, in running order.

async def intro(rec):
    page = await rec.use("c")
    await rec.goto(f"{CARDS}/blank.html", settle=0.3)
    await rec.cursor(False)
    async with rec.take("intro") as t:
        await page.goto(f"{CARDS}/title.html")
        await rec.cursor(False)
        await t.hold(5.2)


async def b1(rec):
    page = await rec.use("anon", fresh=True)   # always signed out, whatever beat 2 left
    await rec.goto(BASE + "/", settle=2.0)
    rec.pos = (1180, 560)
    await page.mouse.move(*rec.pos)
    async with rec.take("b1") as t:
        await t.hold(0.6)
        await t.say("b1a")
        await rec.glide(1100, 470, 1.6)
        await t.say("b1b")
        await t.hold(1.6)
        await rec.scroll_to(".stage", "center")
        await t.say("b1c")
        await t.word("b1c", "no")
        await rec.click("#stage-tab-no-code")
        await t.word("b1c", "low")
        await rec.click("#stage-tab-low-code")
        await t.word("b1c", "high")
        await rec.click("#stage-tab-high-code")
        await t.spoken(1.6)


async def b2a(rec):
    page = await rec.use("a", fresh=True)
    await rec.goto(BASE + "/", settle=2.0)
    rec.pos = (1300, 260)
    await page.mouse.move(*rec.pos)
    pw = "Cm-" + secrets.token_urlsafe(10)
    with open(OUT / "accounts.txt", "a") as f:
        f.write(NEWCOMER["user"] + "\n")
    NEWCOMER_PW.write_text(pw)
    NEWCOMER_PW.chmod(0o600)
    async with rec.take("b2a") as t:
        await rec.click(page.get_by_text("Login - Register"))
        await page.wait_for_load_state("networkidle")
        a = t.now()
        await rec.click(page.get_by_role("link", name="Register"))
        await page.wait_for_selector("#firstName")
        await asyncio.sleep(0.3)
        t.cut(a, t.now() - 0.1)
        await t.say("b2a")
        for sel, text in (("#username", NEWCOMER["user"]), ("#password", pw),
                          ("#password-confirm", pw), ("#email", NEWCOMER["email"]),
                          ("#firstName", NEWCOMER["first"]), ("#lastName", NEWCOMER["last"])):
            await rec.click(sel, pause=0.08, dur=0.35)
            await rec.type(text, cps=22)
        await rec.click(page.get_by_role("button", name="Register"))
        a = t.now()
        await page.wait_for_url(re.compile(re.escape(BASE)), timeout=30000)
        await page.wait_for_load_state("networkidle")
        await page.get_by_role("button", name="Close").wait_for(timeout=20000)
        await asyncio.sleep(0.4)
        t.cut(a, t.now() - 0.1)
        await t.say("b2b")
        await t.hold(2.4)
        await rec.click(page.get_by_role("button", name="Close"))
        await t.hold(0.5)
        await rec.hover(page.locator("mat-list-item", has_text="Deployments"))
        await t.spoken(1.4)


async def b2b(rec):
    page = await rec.use("b")
    await rec.goto(BASE + "/admin", settle=2.0)
    rec.pos = (1100, 640)
    await page.mouse.move(*rec.pos)
    card = page.locator("mat-card", has_text=NEWCOMER["user"]).first
    await card.wait_for(timeout=20000)
    async with rec.take("b2b") as t:
        await t.hold(0.4)
        await t.say("b2c")
        await rec.hover(card.locator(".admin-who"), dur=0.9)
        await t.word("b2c", "approves")
        await rec.click(card.get_by_role("button", name="Approve"))
        await t.spoken(1.8)


async def b2c(rec):
    page = await rec.use("a")
    await rec.goto(BASE + "/", settle=2.0)
    close = page.get_by_role("button", name="Close")
    if await close.count():
        await close.click()
    rec.pos = (1400, 200)
    await page.mouse.move(*rec.pos)
    async with rec.take("b2c") as t:
        await rec.click(page.locator("button", has_text=NEWCOMER["first"]).last)
        await asyncio.sleep(0.6)
        logout = page.get_by_role("menuitem").filter(has_text=re.compile("log ?out|sign ?out", re.I))
        await rec.click(logout)
        a = t.now()
        await page.get_by_text("Login - Register").wait_for(timeout=20000)
        await asyncio.sleep(0.3)
        await rec.click(page.get_by_text("Login - Register"))
        await page.wait_for_selector("#username")
        t.cut(a, t.now() - 0.1)
        await rec.click("#username", dur=0.5)
        await rec.type(NEWCOMER["user"], cps=20)
        await rec.click("#password", dur=0.3)
        await rec.type(NEWCOMER_PW.read_text().strip(), cps=24)
        await rec.click("#kc-login")
        a = t.now()
        await page.wait_for_url(re.compile(re.escape(BASE)), timeout=30000)
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(1.0)
        t.cut(a, t.now() - 0.3)
        await t.say("b2d")
        close = page.get_by_role("button", name="Close")
        if await close.count():
            await t.hold(1.2)
            await rec.click(close)
        await rec.hover(page.locator("mat-list-item", has_text="Deployments"), dur=0.8)
        await t.spoken(1.2)


async def b3a(rec):
    page = await rec.use("c")
    await rec.goto(BASE + "/catalog/modules", settle=2.0)
    rec.pos = (900, 420)
    await page.mouse.move(*rec.pos)
    async with rec.take("b3a") as t:
        await rec.click(page.locator("mat-list-item", has_text="LLMs"))
        await page.locator("mat-card", has_text="Qwen3.5-2B").first.wait_for()
        await rec.chapter("No code", "A private language model")
        await t.say("b3a")
        await rec.glide(1160, 470, 1.2)
        await rec.glide(1290, 450, 1.0)
        await t.say("b3b")
        await rec.click(page.locator("mat-card", has_text="Qwen3.5-2B").first.locator("mat-card-title"))
        await page.get_by_text("Configure deployment").wait_for()
        await t.hold(0.6)
        await rec.click(page.locator("mat-form-field", has_text="Deployment title").locator("input"))
        await rec.type("Radiology assistant")
        await rec.hover(page.locator("mat-form-field", has_text="VLLM model"), dur=0.8)
        await t.spoken(1.2)


async def b3b(rec):
    page = await rec.use("c")
    links = await quick_access(rec)
    await rec.goto(links["Private language model"], settle=2.0)
    await tidy_chat(rec)
    await rec.goto(BASE + "/tasks/deployments", settle=2.5)
    rec.pos = (1000, 520)
    await page.mouse.move(*rec.pos)
    row = page.locator("mat-row", has_text="Private language model")
    async with rec.take("b3b") as t:
        await t.say("b3c")
        await rec.hover(row.locator("mat-cell").nth(1), dur=0.9)
        await t.word("b3c", "private")
        await same_tab(rec, "#quickAccessButton")
        await rec.click(row.locator("#quickAccessButton"))
        a = t.now()
        await page.wait_for_url(re.compile(r"https://ui-"), timeout=30000)
        box = page.locator("#chat-input")
        await box.wait_for(timeout=30000)
        await asyncio.sleep(1.0)
        await tidy_chat(rec)
        t.cut(a, t.now() - 0.2)
        await t.spoken(0.3)
        await t.say("b3d")
        await rec.click(box)
        await page.keyboard.insert_text(NOTE)
        await t.hold(1.0)
        await page.keyboard.press("Enter")
        answer = await chat_answer(page)
        if not re.search(r"lesion", answer, re.I) or re.search(r"unable|cannot|can't|as an ai|not able", answer, re.I):
            raise Retake(f"the model answered: {answer[:160]!r}")
        print(f"           answer: {answer[:200]}", flush=True)
        await t.hold(0.6)
        await t.say("b3e")
        await rec.glide(900, 520, 1.2)
        await t.spoken(2.2)


async def b4a(rec):
    page = await rec.use("c")
    await rec.goto(BASE + "/catalog/modules", settle=2.0)
    rec.pos = (1000, 300)
    await page.mouse.move(*rec.pos)
    async with rec.take("b4a") as t:
        await rec.chapter("Low code", "Serverless inference")
        await t.say("b4a")
        await rec.click(page.locator("mat-card", has_text="YOLO models"))
        await page.get_by_text("Deploy", exact=True).first.wait_for()
        await t.say("b4b")
        await rec.click(page.get_by_text("Deploy", exact=True).first)
        await asyncio.sleep(0.6)
        await rec.hover(page.get_by_text("Inference API (serverless)"), dur=0.6)
        await t.word("b4b", "only")
        await rec.click(page.get_by_text("Inference API (serverless)"))
        await page.get_by_text("Configure deployment").wait_for()
        await t.spoken(1.4)


async def b4b(rec):
    page = await rec.use("c")
    await rec.goto(BASE + "/tasks/inference", settle=2.0)
    rec.pos = (1100, 500)
    await page.mouse.move(*rec.pos)
    row = page.locator("mat-row", has_text="Object detection")
    async with rec.take("b4b") as t:
        await t.say("b4c")
        await rec.click(row.locator("button").first)
        await page.get_by_role("heading", name="Synchronous calls", exact=True).wait_for()
        await asyncio.sleep(0.5)
        await rec.js("""() => { const el = [...document.querySelectorAll('*')].find(e => e.childElementCount === 0
                         && e.textContent.trim() === 'Endpoint'); el && el.scrollIntoView({behavior: 'smooth', block: 'center'}); }""")
        await asyncio.sleep(1.0)
        label = await page.get_by_text("Endpoint", exact=True).first.bounding_box()
        box = (label["x"] + 300, label["y"] + label["height"] + 44) if label else None
        if box:
            await rec.glide(*box, 0.9)
        await t.spoken(2.0)


async def b4c(rec):
    page = await rec.use("c")
    where = "caios_server"
    await rec.goto(f"{CARDS}/shell.html?port=7681&where={where}", settle=2.5)
    await rec.cursor(False)
    frame = page.frame_locator("#t")
    await frame.locator(".xterm-helper-textarea").focus()
    async with rec.take("b4c") as t:
        await t.say("b4d")
        await rec.type(CURL, cps=26)
        await t.hold(0.4)
        await page.keyboard.press("Enter")
        a = t.now()
        await wait_term(page, "#t", r'"confidence"', 60)
        await wait_term(page, "#t", r"researcher@caios_server \$ *$", 20)
        t.cut(a + 0.8, t.now() - 0.4)
        await t.say("b4e")
        await t.spoken(2.0)


async def term_text(page, frame_sel):
    fr = page.frame_locator(frame_sel)
    return await fr.locator("body").evaluate("""() => { const b = window.term.buffer.active, out = [];
        for (let i = 0; i < b.length; i++) out.push(b.getLine(i).translateToString(true));
        return out.join('\\n').replace(/\\s+$/, ''); }""")


async def wait_term(page, frame_sel, pattern, timeout):
    rx = re.compile(pattern, re.M)
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if rx.search(await term_text(page, frame_sel)):
            return
        await asyncio.sleep(0.25)
    raise TimeoutError(f"{pattern!r} never appeared in {frame_sel}")


async def b5a(rec):
    page = await rec.use("c")
    await rec.goto(BASE + "/catalog/modules/ai4os-yolo-torch", settle=2.0)
    rec.pos = (1000, 520)
    await page.mouse.move(*rec.pos)
    async with rec.take("b5a") as t:
        await rec.chapter("High code", "A JupyterLab workspace")
        await t.say("b5a")
        await rec.click(page.get_by_text("Deploy", exact=True).first)
        await asyncio.sleep(0.6)
        await rec.hover(page.get_by_text("Dedicated deployment"), dur=0.6)
        await rec.click(page.get_by_text("Dedicated deployment"))
        await page.get_by_text("Service to run").wait_for()
        await t.word("b5a", "jupyter")
        await rec.click(page.get_by_text("Jupyter", exact=True))
        await t.spoken(1.4)


async def b5b(rec):
    page = await rec.use("c")
    links = await quick_access(rec)
    lab = links["YOLO notebook"].rstrip("/")
    await rec.goto(lab + "/lab/tree/caios-demo/high-code.ipynb", settle=5.0)
    await reset_notebook(rec)
    await rec.goto(BASE + "/tasks/deployments", settle=2.5)
    rec.pos = (1000, 300)
    await page.mouse.move(*rec.pos)
    row = page.locator("mat-row", has_text="YOLO notebook")
    async with rec.take("b5b") as t:
        await same_tab(rec, "#quickAccessButton")
        await rec.click(row.locator("#quickAccessButton"))
        a = t.now()
        await page.wait_for_url(re.compile(r"https://ide-"), timeout=30000)
        await page.locator(".jp-Notebook .jp-Cell").first.wait_for(timeout=60000)
        await wait_kernel_idle(page)
        await asyncio.sleep(1.0)
        await page.mouse.move(*rec.pos)
        t.cut(a, t.now() - 0.3)
        cells = page.locator(".jp-Notebook .jp-CodeCell")

        async def run_cell(i):
            await rec.click(cells.nth(i).locator(".jp-InputArea-editor"), dur=0.6)
            await asyncio.sleep(0.25)
            await page.keyboard.press("Shift+Enter")

        await run_cell(0)
        await cells.nth(0).locator(".jp-OutputArea-output img").wait_for(timeout=60000)
        await asyncio.sleep(0.3)
        await rec.js("() => document.querySelectorAll('.jp-Notebook .jp-CodeCell')[0].querySelector('.jp-RenderedImage').scrollIntoView({behavior: 'smooth', block: 'center'})")
        await t.say("b5b")
        await rec.glide(900, 560, 1.2)
        await t.spoken(0.5)
        await rec.js("() => document.querySelectorAll('.jp-Notebook .jp-CodeCell')[1].scrollIntoView({behavior: 'smooth', block: 'center'})")
        await asyncio.sleep(0.8)
        await run_cell(1)
        await cells.nth(1).locator(".jp-OutputArea-output").first.wait_for(timeout=30000)
        await t.hold(1.2)
        await rec.js("() => document.querySelectorAll('.jp-Notebook .jp-CodeCell')[2].scrollIntoView({behavior: 'smooth', block: 'center'})")
        await asyncio.sleep(0.8)
        await run_cell(2)
        await t.say("b5c")
        a = t.now()
        await cells.nth(2).locator(".jp-OutputArea-output").first.wait_for(timeout=120000)
        b = t.now()
        if b - a > 5.0:
            t.cut(a + 4.2, b - 0.6)
        await t.spoken(0.2)
        await rec.js("() => document.querySelectorAll('.jp-Notebook .jp-CodeCell')[3].scrollIntoView({behavior: 'smooth', block: 'center'})")
        await asyncio.sleep(0.6)
        await run_cell(3)
        await t.say("b5d")
        await cells.nth(3).locator(".jp-OutputArea-output").first.wait_for(timeout=120000)
        await t.spoken(0.8)
        await t.say("b5e")
        await rec.glide(1000, 640, 1.4)
        await t.spoken(2.0)


async def wait_kernel_idle(page, timeout=60):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        status = await page.evaluate("""() => document.querySelector('.jp-Notebook-ExecutionIndicator')?.getAttribute('data-status')
                                         || document.body.innerText.match(/Python 3 \\(ipykernel\\) \\| (\\w+)/)?.[1] || ''""")
        if status.lower() in ("idle",):
            return
        await asyncio.sleep(0.4)


async def reset_notebook(rec):
    """Kernel > Restart Kernel and Clear Outputs of All Cells, off camera."""
    page = rec.page
    await page.locator(".jp-Notebook .jp-Cell").first.wait_for(timeout=60000)
    for label in ("No", "Dismiss"):
        b = page.get_by_role("button", name=label, exact=True)
        if await b.count():
            await b.first.click()
    await page.locator(".lm-MenuBar-itemLabel", has_text="Kernel").click()
    await page.locator(".lm-Menu-itemLabel", has_text="Restart Kernel and Clear Outputs of All Cells").click()
    confirm = page.locator(".jp-Dialog-button.jp-mod-accept, .jp-Dialog-button.jp-mod-warn")
    try:
        await confirm.first.click(timeout=5000)
    except Exception:
        pass
    await asyncio.sleep(2.0)
    await wait_kernel_idle(page)
    await page.keyboard.press("Control+s")
    await asyncio.sleep(1.0)
    await page.evaluate("() => document.querySelector('.jp-Notebook .jp-Cell')?.scrollIntoView({block: 'start'})")


async def b6a(rec):
    page = await rec.use("c")
    fl = [p for p in PANES if p.get("role") == "fl"]
    if len(fl) != 4:
        raise RuntimeError("the federated terminals are not up: python3 demo/recording/terminals.py up")
    q = "&".join("p=" + "|".join([str(p["port"]), p["label"], p["node"],
                                  "server" if p["key"] == "server" else "site"]).replace(" ", "%20")
                 for p in fl)
    await rec.goto(f"{CARDS}/federation.html?{q}", settle=4.0)
    await rec.cursor(False)
    srv, sites = f"#p{fl[0]['port']}", [f"#p{p['port']}" for p in fl[1:]]
    for sel in [srv, *sites]:
        await wait_term(page, sel, r"\$ *$", 30)

    async def run_in(sel, cmd, cps=30):
        await page.frame_locator(sel).locator(".xterm-helper-textarea").focus()
        await rec.type(cmd, cps=cps)
        await asyncio.sleep(0.25)
        await page.keyboard.press("Enter")

    async with rec.take("b6a") as t:
        await rec.chapter("Federated learning", "Three hospitals, one model", 4600)
        await t.say("b6a")
        await run_in(srv, "cd /srv/ai4os-federated-server/fedserver && python3 server.py")
        await t.say("b6b")
        for sel in sites:
            await run_in(sel, "cd ~/caios-fl && ./run.sh --quiet", cps=34)
        await wait_term(page, srv, r"\[ROUND 1\]", 90)
        a = t.now()
        await t.say("b6c")
        await wait_term(page, srv, r"Run finished 10 round", 180)
        b = t.now()
        await t.hold(1.5)
        t.speed(a + 2.0, b, 2.0)
        await t.spoken(1.0)


async def b6b(rec):
    page = await rec.use("c")
    await rec.goto(f"{CARDS}/blank.html", settle=0.3)
    await rec.cursor(False)
    async with rec.take("b6b") as t:
        await page.goto(f"{CARDS}/chart.html")
        await rec.cursor(False)
        await t.hold(1.0)
        await t.say("b6d")
        await t.say("b6e")
        await t.spoken(2.0)


async def b7(rec):
    page = await rec.use("c")
    await rec.goto(BASE + "/statistics", settle=4.0)
    rec.pos = (1000, 560)
    await page.mouse.move(*rec.pos)
    async with rec.take("b7") as t:
        await t.say("b7a")
        await rec.glide(1160, 430, 1.4)
        await rec.glide(1260, 440, 1.2)
        await t.spoken(1.2)


async def outro(rec):
    page = await rec.use("c")
    await rec.goto(f"{CARDS}/blank-dark.html", settle=0.3)
    await rec.cursor(False)
    async with rec.take("outro") as t:
        await page.goto(f"{CARDS}/end.html")
        await rec.cursor(False)
        await t.hold(0.9)
        await t.say("b7b")
        await t.spoken(3.0)


ORDER = ["intro", "b1", "b2a", "b2b", "b2c", "b3a", "b3b", "b4a", "b4b", "b4c",
         "b5a", "b5b", "b6a", "b6b", "b7", "outro"]
CLIP_FN = {name: globals()[name] for name in ORDER}


async def main(argv):
    async with async_playwright() as pw:
        rec = Recorder(pw)
        if argv and argv[0] == "setup":
            await setup(rec)
            return
        names = argv[1:] if argv and argv[0] == "record" and len(argv) > 1 else ORDER
        failed = []
        for name in names:
            for attempt in range(1, 5):
                try:
                    await CLIP_FN[name](rec)
                    break
                except Retake as e:
                    print(f"  {name:<8} retaking ({attempt}): {e}"[:300], flush=True)
                except Exception as e:
                    failed.append(name)
                    print(f"  {name:<8} FAILED: {e!r}"[:400], flush=True)
                    try:
                        await rec.page.screenshot(path=str(CLIPS / f"{name}-failed.png"))
                    except Exception:
                        pass
                    break
            else:
                failed.append(name)
        if rec.ctx:
            await rec.ctx.close()
        if failed:
            print("  retake:", " ".join(failed))
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
