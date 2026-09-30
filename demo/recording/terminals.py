"""The recording's terminals, served to the browser by ttyd.

    python3 demo/recording/terminals.py up     # before recording
    python3 demo/recording/terminals.py down   # after

Runs on caios_server, on the host, because it needs the nomad CLI and its
certificates. `up` finds the federated demo's four allocations and the
serverless service's endpoint, and serves five terminals on loopback:

    7681  caios_server, for beat 4: ENDPOINT, TOKEN and portrait.json ready
    7682  the federated server's container
    7683  site_a's container         7684  site_b's      7685  site_c's

Each is a real shell. The four federated ones are `nomad alloc exec` into the
deployment, exactly what a JupyterLab terminal in that workspace would be.
Everything a take must not show (the token, the exports) is set up here, off
camera; the shell opens on a clean prompt. `down` stops the terminals and any
federated process a take left running.
"""
import base64
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = HERE / "out" / "term"
TTYD = HERE / "out" / "bin" / "ttyd"
CA = ROOT / "compose" / "certs" / "caios-ca.pem"
VO = "vo.caios.ca"
SITES = ("site_a", "site_b", "site_c")
SERVICE_TITLE = "Object detection"
PORTRAIT = ROOT / "tests" / "fixtures" / "modules" / "grace_hopper.jpg"
# Bracketed, so a pattern never matches the shell that carries it
# (scripts/lib/check_fl_cluster.py).
STRAYS = "pkill -f '[s]erver[.]py'; pkill -f '[c]lient[.]py'; pkill -f '[r]un[.]sh'; true"

# The dashboard's console palette (configs/dashboard/home: --h-console and
# friends), so the terminals read as part of the same product.
THEME = {"background": "#0a2129", "foreground": "#e4edef", "cursor": "#37cfe4",
         "selectionBackground": "#1d4b56", "black": "#0a2129", "brightBlack": "#6f939c",
         "cyan": "#37cfe4", "brightCyan": "#80d2dc", "green": "#7fd19b", "brightGreen": "#9be3b1",
         "yellow": "#e8c170", "brightYellow": "#f0d493", "blue": "#6fb3d9", "brightBlue": "#93c9e6",
         "red": "#e07a5f", "brightRed": "#ec9a82", "magenta": "#c49bd6", "white": "#e4edef",
         "brightWhite": "#ffffff"}


def load_env():
    env = {}
    for line in (ROOT / "configs" / "env" / "caios.env").read_text().splitlines():
        m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line.strip())
        if m:
            v = m.group(2).strip().strip("'\"")
            env[m.group(1)] = re.sub(r"\$\{(\w+)\}", lambda x: env.get(x.group(1), ""), v)
    return env


E = load_env()
SCHEME = E.get("CAIOS_SCHEME", "https")
API = f"{SCHEME}://{E['CAIOS_API_HOST']}/v1"
ISSUER = f"{SCHEME}://{E['CAIOS_AUTH_HOST']}/realms/{E['KEYCLOAK_REALM']}"


def token():
    r = requests.post(f"{ISSUER}/protocol/openid-connect/token", verify=str(CA), timeout=30,
                      data={"client_id": "caios-dashboard", "grant_type": "password",
                            "username": "researcher", "password": E["CAIOS_PW_RESEARCHER"],
                            "scope": "openid profile email"})
    r.raise_for_status()
    return r.json()["access_token"]


def nomad_json(*args):
    out = subprocess.run(["nomad", *args], stdin=subprocess.DEVNULL, capture_output=True,
                         text=True, timeout=60, check=True)
    return json.loads(out.stdout)


def running(job):
    live = [a for a in nomad_json("job", "allocs", "-namespace=caios", "-json", job)
            if a["ClientStatus"] == "running"]
    if not live:
        sys.exit(f"job {job} has no running allocation")
    return live[0]["ID"], live[0]["NodeName"]


def ttyd(port, cmd, font_size):
    log = open(OUT / f"ttyd-{port}.log", "w")
    args = [str(TTYD), "-p", str(port), "-i", "lo", "-W", "-O",
            "-t", f"fontSize={font_size}", "-t", "fontFamily=IBM Plex Mono",
            "-t", "lineHeight=1.2", "-t", "cursorBlink=true", "-t", "disableLeaveAlert=true",
            "-t", "disableResizeOverlay=true", "-t", "titleFixed=CAIOS", "-t", "rendererType=dom",
            "-t", "theme=" + json.dumps(THEME), "--", *cmd]
    return subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, start_new_session=True).pid


def prompt(label):
    return rf"\[\e[38;5;80m\]{label}\[\e[0m\] \[\e[38;5;244m\]\w\[\e[0m\] $ "


def up():
    OUT.mkdir(parents=True, exist_ok=True)
    os.chmod(OUT, 0o700)
    down(quiet=True)
    tok = token()
    hdr = {"Authorization": f"Bearer {tok}"}

    # Beat 4: the serverless service, called from this machine.
    svcs = requests.get(f"{API}/inference/oscar/services", params={"vo": VO}, headers=hdr,
                        verify=str(CA), timeout=60).json()
    svc = next((s for s in svcs if s.get("title") == SERVICE_TITLE), None) or (svcs[0] if svcs else None)
    if not svc:
        sys.exit("no serverless service: create 'Object detection' first (docs/demo-script.md)")
    detail = requests.get(f"{API}/inference/oscar/services/{svc['name']}", params={"vo": VO},
                          headers=hdr, verify=str(CA), timeout=60).json()
    work = OUT / "b4"
    work.mkdir(exist_ok=True)
    doc = {"oscar-files": [{"key": "files", "file_format": "jpg",
                            "data": base64.b64encode(PORTRAIT.read_bytes()).decode()}]}
    (work / "portrait.json").write_text(json.dumps(doc))
    rc = OUT / "b4.rc"
    rc.write_text("\n".join([
        f"export ENDPOINT={shlex.quote(detail['endpoint'])}",
        f"export TOKEN={shlex.quote(detail['token'])}",
        f"export CURL_CA_BUNDLE={shlex.quote(str(CA))}",
        "export HISTFILE=/dev/null",
        f"cd {shlex.quote(str(work))}",
        "PS1=" + shlex.quote(r"\[\e[38;5;80m\]researcher@caios_server\[\e[0m\] $ "),
        "clear", ""]))
    os.chmod(rc, 0o600)

    panes = [{"port": 7681, "label": "caios_server", "node": "caios_server", "role": "shell"}]
    pids = [ttyd(7681, ["bash", "--rcfile", str(rc), "-i"], 16)]

    # Beat 6: the federation's four containers.
    tools = requests.get(f"{API}/deployments/tools", params={"vos": VO}, headers=hdr,
                         verify=str(CA), timeout=60).json()
    by_title = {d.get("title"): d for d in tools}
    fl = [("server", "CAIOS federated server", "Coordinating server")] + \
         [(s, f"CAIOS {s}", f"Hospital {s[-1].upper()}") for s in SITES]
    for i, (key, title, label) in enumerate(fl):
        d = by_title.get(title)
        if not d:
            sys.exit(f"no '{title}' deployment: run scripts/deploy-fl-demo.sh")
        alloc, node = running(d["job_ID"])
        subprocess.run(["nomad", "alloc", "exec", "-namespace=caios", "-task", "main", "-i=false",
                        "-t=false", alloc, "bash", "-lc", STRAYS], stdin=subprocess.DEVNULL,
                       capture_output=True, timeout=60)
        port = 7682 + i
        shell = ["env", "TF_CPP_MIN_LOG_LEVEL=3", "PYTHONWARNINGS=ignore", "TERM=xterm-256color",
                 "HISTFILE=/dev/null", f"PS1={prompt(key)}", "bash", "--norc", "-i"]
        pids.append(ttyd(port, ["nomad", "alloc", "exec", "-namespace=caios", "-task", "main",
                                "-i", "-t", alloc, *shell], 14))
        panes.append({"port": port, "key": key, "label": label, "node": node, "alloc": alloc,
                      "role": "fl"})

    (OUT / "pids").write_text("\n".join(map(str, pids)))
    (OUT / "panes.json").write_text(json.dumps(panes, indent=1))
    time.sleep(1.0)
    for p in panes:
        print(f"  {p['port']}  {p['label']:<20} {p['node']}")


def down(quiet=False):
    pids = OUT / "pids"
    if pids.exists():
        for pid in pids.read_text().split():
            try:
                os.killpg(int(pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        pids.unlink()
    panes = OUT / "panes.json"
    if panes.exists():
        for p in json.loads(panes.read_text()):
            if p.get("alloc"):
                subprocess.run(["nomad", "alloc", "exec", "-namespace=caios", "-task", "main",
                                "-i=false", "-t=false", p["alloc"], "bash", "-lc", STRAYS],
                               stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
    for f in (OUT / "b4.rc", OUT / "b4" / "portrait.json"):
        f.unlink(missing_ok=True)
    if not quiet:
        print("  terminals stopped")


if __name__ == "__main__":
    {"up": up, "down": down}[sys.argv[1] if len(sys.argv) > 1 else "up"]()
