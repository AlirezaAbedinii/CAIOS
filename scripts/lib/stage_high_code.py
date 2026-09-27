"""Stage the high-code notebook into a running YOLO JupyterLab deployment.

Driven by scripts/stage-high-code.sh. Collects what the notebook's two remote
calls need — the OSCAR service's endpoint and token, the LLM's endpoint, key
and model — from PAPI with the owners' own tokens, writes them into the
workspace beside the notebook, and then runs the notebook once headlessly.

That run is the test and the warm-up at once: it fetches YOLO's weights, wakes
the serverless service and the model, and proves every cell works, so the
first run on camera is the second run there has ever been.

Prints no secret. The config is written mode 600, as a dotfile the file browser
hides, inside the workspace and nowhere else.
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CA = os.path.join(ROOT, "compose", "certs", "caios-ca.pem")
SOURCE = os.path.join(ROOT, "demo", "high-code")
DEST = "/srv/caios-demo"
VO = "vo.caios.ca"

API = os.environ["CAIOS_API"].rstrip("/")
ISSUER = os.environ["CAIOS_ISSUER"].rstrip("/")


def say(msg):
    print(msg, flush=True)


def token(user):
    pw = os.environ.get("CAIOS_PW_" + user.upper().replace("-", "_"), "")
    if not pw:
        sys.exit(f"no password for {user} in configs/env/caios.env")
    r = requests.post(f"{ISSUER}/protocol/openid-connect/token", verify=CA, timeout=30,
                      data={"client_id": "caios-dashboard", "grant_type": "password",
                            "username": user, "password": pw, "scope": "openid profile email"})
    r.raise_for_status()
    return r.json()["access_token"]


def papi(tok, path, **params):
    r = requests.get(f"{API}{path}", headers={"Authorization": f"Bearer {tok}"},
                     params={"vo": VO, **params}, timeout=60)
    r.raise_for_status()
    return r.json()


def nomad(*args, timeout=120):
    """Run the nomad CLI and return its stdout.

    stdin is a pipe held open until the command has finished. `nomad alloc
    exec` ends its session when it sees EOF on stdin — with or without -i — and
    whatever output had not yet arrived is lost. Measured: 1.28 MB of a 1.73 MB
    file with stdin at /dev/null, and a warm-up whose whole summary vanished.
    """
    proc = subprocess.Popen(["nomad", *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    try:
        out = proc.stdout.read()
        err = proc.stderr.read()
        proc.wait(timeout=timeout)
    finally:
        proc.stdin.close()
    if proc.returncode != 0:
        sys.exit(f"nomad {' '.join(args[:3])}: {err.strip()[:300]}")
    return out


def running_alloc(job):
    allocs = json.loads(nomad("job", "allocs", "-namespace=caios", "-json", job))
    live = [a for a in allocs if a["ClientStatus"] == "running"]
    if not live:
        sys.exit(f"deployment {job} has no running allocation — is it deployed, and in Jupyter mode?")
    return live[0]["ID"]


def put(alloc, name, content, mode="644"):
    """Write one file into the workspace. Through the argument list rather than
    stdin: `nomad alloc exec` without a terminal does not reliably pass EOF."""
    b64 = base64.b64encode(content if isinstance(content, bytes) else content.encode()).decode()
    nomad("alloc", "exec", "-namespace=caios", "-task", "main", "-i=false", "-t=false", alloc,
          "sh", "-c", f"mkdir -p {DEST} && umask 077 && echo {b64} | base64 -d > {DEST}/{name} "
                      f"&& chmod {mode} {DEST}/{name}")


# Summarised inside the workspace, not copied out: the executed notebook is
# about 1.7 MB with its drawn image, and `nomad alloc exec` can drop the tail of
# a large output when its stdin closes first — measured, 1.28 MB of 1.73 arrived.
SUMMARY = r"""
import json, datetime
nb = json.load(open("/tmp/high-code.executed.ipynb"))
ts = lambda s: datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
for c in nb["cells"]:
    if c["cell_type"] != "code":
        continue
    m = c.get("metadata", {}).get("execution", {})
    took = ""
    if "iopub.execute_input" in m and "shell.execute_reply" in m:
        took = "%.1fs" % (ts(m["shell.execute_reply"]) - ts(m["iopub.execute_input"])).total_seconds()
    shown, error = "", 0
    for o in c.get("outputs", []):
        if o.get("output_type") == "error":
            shown, error = "ERROR %s: %s" % (o["ename"], o["evalue"][:120]), 1
        elif "image/png" in o.get("data", {}):
            shown = "an image"
        elif "text/plain" in o.get("data", {}) and not shown:
            shown = " ".join("".join(o["data"]["text/plain"]).split())[:160]
    src = c["source"] if isinstance(c["source"], str) else "".join(c["source"])
    print(json.dumps({"took": took, "first": src.strip().splitlines()[0], "shown": shown, "error": error}))
"""


def sh_quote(s):
    return "'" + s.replace("'", "'\\''") + "'"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workspace", help="uuid of the YOLO deployment running in Jupyter mode")
    ap.add_argument("llm", help="uuid of a running LLM deployment")
    ap.add_argument("--service", default="", help="OSCAR service name (default: the user's YOLO service)")
    ap.add_argument("--user", default=os.environ.get("CAIOS_DEMO_USER", "researcher"))
    ap.add_argument("--llm-owner", default="", help="account owning the LLM (default: --user)")
    ap.add_argument("--no-run", action="store_true", help="stage only; skip the warm-up run")
    args = ap.parse_args()

    user_tok = token(args.user)
    llm_tok = token(args.llm_owner) if args.llm_owner else user_tok

    # The serverless service: the named one, or the user's YOLO service.
    services = papi(user_tok, "/inference/oscar/services")
    if args.service:
        svc = next((s for s in services if s["name"] == args.service), None)
    else:
        # The newest: a service created after patch 0022 answers with plain
        # JSON, an older one with its job's log (the helper reads both).
        yolo = [s for s in services if s.get("image", "").endswith("/ai4os-yolo-torch")]
        yolo.sort(key=lambda s: s.get("environment", {}).get("variables", {}).get("PAPI_CREATED", ""))
        svc = yolo[-1] if yolo else None
    if svc is None:
        sys.exit("no YOLO serverless service for this user: create one from the marketplace "
                 "(YOLO -> Deploy -> Inference API (serverless)), or pass --service")
    say(f"serverless  {svc['name']}  ({svc.get('environment', {}).get('variables', {}).get('PAPI_TITLE', '')})")

    # The LLM: its endpoint from PAPI, its key from Vault through PAPI, its model from itself.
    llm = papi(llm_tok, f"/deployments/tools/{args.llm}")
    endpoint = (llm.get("endpoints") or {}).get("vllm", "")
    if not endpoint or "${" in endpoint:
        sys.exit(f"LLM {args.llm} publishes no vLLM endpoint yet (status: {llm.get('status')})")
    secrets = papi(llm_tok, "/secrets", subpath=f"/deployments/{args.llm}")
    key = next((v.get("token", "") for k, v in secrets.items() if k.endswith("/llm/vllm")), "")
    if not key:
        sys.exit(f"no API key in Vault for LLM {args.llm}")
    models = requests.get(f"{endpoint}/v1/models", headers={"Authorization": f"Bearer {key}"},
                          verify=CA, timeout=30).json()
    model = models["data"][0]["id"]
    say(f"llm         {model}  at {endpoint.split('//')[1].split('.')[0]}…")

    config = {"serverless": {"endpoint": svc["endpoint"], "token": svc["token"]},
              "llm": {"endpoint": endpoint, "key": key, "model": model}}

    alloc = running_alloc(args.workspace)
    put(alloc, "high-code.ipynb", open(os.path.join(SOURCE, "high-code.ipynb")).read())
    put(alloc, "caios_demo.py", open(os.path.join(SOURCE, "caios_demo.py")).read())
    put(alloc, ".caios-ca.pem", open(CA).read())
    put(alloc, ".caios.json", json.dumps(config), mode="600")
    say(f"staged      {DEST}/high-code.ipynb, caios_demo.py, .caios-ca.pem, .caios.json (600)")

    if args.no_run:
        return 0

    say("warm-up     running the notebook once, headless")
    t0 = time.time()
    out = nomad("alloc", "exec", "-namespace=caios", "-task", "main", "-t=false", alloc,
                "sh", "-c", f"cd {DEST} && jupyter nbconvert --to notebook --execute high-code.ipynb "
                            f"--output /tmp/high-code.executed.ipynb >/dev/null 2>&1; "
                            f"python3 -c {sh_quote(SUMMARY)}; "
                            # Leave the folder as the camera should find it.
                            f"rm -rf {DEST}/runs {DEST}/__pycache__", timeout=900)
    say(f"            finished in {time.time() - t0:.0f}s")
    cells = [json.loads(l) for l in out.splitlines() if l.startswith("{")]
    if not cells:
        # Silence is not a pass: an empty summary is how a truncated exec, or a
        # notebook that never ran, looks from here.
        say("  [FAIL] the warm-up returned no summary — run it again, or open the notebook")
        return 1
    failed = 0
    for cell in cells:
        failed += cell["error"]
        say(f"  [{cell['took']:>5}] {cell['first'][:48]:48} -> {cell['shown']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
