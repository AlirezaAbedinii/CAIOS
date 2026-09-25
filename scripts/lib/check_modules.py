"""Deploy every marketplace module, in both modes, and report which ones work.

Driven by scripts/check-modules.sh, which supplies the token and the API base.
Everything goes through PAPI exactly as the dashboard would send it, so a pass
here means a researcher clicking Deploy gets a working deployment.

  DEEPaaS mode   the API lists its model, a prediction on a real input returns
                 200, and the Gradio page answers
  Jupyter mode   JupyterLab serves /login and the deployment password logs in

Deployments run in a rolling window, each tested the moment it runs and deleted
straight after, and every deployment this created is deleted in a `finally`,
whatever happens. Results are written as they arrive.
"""

import argparse
import datetime
import io
import json
import math
import os
import secrets
import string
import struct
import sys
import time
import wave

import requests

VO = "vo.caios.ca"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CA = os.path.join(ROOT, "compose", "certs", "caios-ca.pem")
IMAGE_FIXTURE = os.path.join(ROOT, "tests", "fixtures", "modules", "grace_hopper.jpg")
RESULTS = os.path.join(ROOT, "demo", "modules", "check-results.tsv")

API = os.environ["CAIOS_API"].rstrip("/")          # https://api.<domain>/v1
ISSUER = os.environ["CAIOS_ISSUER"].rstrip("/")    # https://auth.<domain>/realms/<realm>
USER = os.environ["CAIOS_CHECK_USER"]
PASSWORD = os.environ["CAIOS_CHECK_PASSWORD"]

# A sweep outlives an access token (1800 s in the realm template), and the
# deletes in the `finally` are the calls that must not fail. So the token is
# renewed every ten minutes, and a 401 is retried once with a fresh one.
_token = {"value": "", "at": 0.0}


def token(force=False):
    if force or not _token["value"] or time.time() - _token["at"] > 600:
        r = requests.post(f"{ISSUER}/protocol/openid-connect/token", verify=CA, timeout=30,
                          data={"client_id": "caios-dashboard", "grant_type": "password",
                                "username": USER, "password": PASSWORD,
                                "scope": "openid profile email"})
        r.raise_for_status()
        _token.update(value=r.json()["access_token"], at=time.time())
    return _token["value"]


def say(msg):
    print(msg, flush=True)


def papi(method, path, **kw):
    for attempt in (0, 1):
        r = requests.request(method, f"{API}{path}", timeout=60,
                             headers={"Authorization": f"Bearer {token(force=attempt == 1)}"}, **kw)
        if r.status_code != 401:
            return r
    return r


def wav_fixture():
    """One second of a 440 Hz tone. The audio classifier's labels are
    meaningless on it; the point is that the API accepts audio and answers."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"".join(
            struct.pack("<h", int(12000 * math.sin(2 * math.pi * 440 * i / 16000)))
            for i in range(16000)))
    return buf.getvalue()


def submit(module, mode, password):
    """POST what the dashboard's deploy form would, with the form's defaults."""
    cfg = papi("GET", f"/catalog/modules/{module}/config", params={"vo": VO}).json()
    values = {sec: {k: v.get("value") for k, v in fields.items()} for sec, fields in cfg.items()}
    values["general"].update(title=f"check-modules {mode} {module}"[:45],  # PAPI caps titles at 45
                             desc="scripts/check-modules.sh; deleted afterwards",
                             service=mode,
                             jupyter_password=password if mode == "jupyter" else "")
    values["hardware"].update(gpu_num=0)
    r = papi("POST", "/deployments/modules", params={"vo": VO}, json=values)
    if r.status_code != 200:
        return None, f"PAPI refused the deployment: {r.status_code} {r.text[:200]}"
    return r.json()["job_ID"], ""


def endpoint(info, key):
    url = (info.get("endpoints") or {}).get(key, "")
    return "" if (not url or "${" in url) else url


def test_deepaas(info, datatypes):
    """The API lists a model, predicts on a real input, and the UI answers."""
    base = endpoint(info, "api")
    if base.endswith("/ui"):
        base = base[: -len("/ui")]
    ui = endpoint(info, "ui")
    if not base:
        return False, "no api endpoint published"

    # DEEPaaS can take a while after the container starts: TensorFlow 1.x
    # loads its graph on a single core.
    t0, models = time.time(), None
    while time.time() - t0 < 300:
        try:
            r = requests.get(f"{base}/v2/models/", verify=CA, timeout=20)
            if r.status_code == 200:
                models = r.json().get("models", [])
                break
        except requests.RequestException:
            pass
        time.sleep(5)
    if not models:
        return False, "the API never listed a model"
    name = models[0]["id"]

    spec = requests.get(f"{base}/swagger.json", verify=CA, timeout=20).json()
    path = next((p for p in spec.get("paths", {}) if p.endswith(f"/{name}/predict/")), None)
    if path is None:
        return False, f"{name}: no predict endpoint in swagger"
    params = spec["paths"][path]["post"].get("parameters", [])
    files_params = [p for p in params if p.get("type") == "file"]
    query = {}
    if any(p["name"] == "accept" for p in params):
        query["accept"] = "application/json"

    files = None
    if files_params:
        fp = next((p for p in files_params if p.get("required")), files_params[0])
        if "Audio" in datatypes:
            files = {fp["name"]: ("tone.wav", wav_fixture(), "audio/wav")}
        else:
            files = {fp["name"]: ("grace_hopper.jpg", open(IMAGE_FIXTURE, "rb").read(), "image/jpeg")}

    t = time.time()
    try:
        r = requests.post(f"{base}{path}", params=query, files=files, data={} if files else None,
                          headers={"accept": "application/json"}, verify=CA, timeout=300)
    except requests.RequestException as e:
        # The exception's type, not its text: the text carries the deployment's
        # full hostname, which does not belong in a results file that outlives
        # the domain.
        return False, f"{name}: predict failed after {time.time() - t:.0f}s: {type(e).__name__}"
    took = time.time() - t
    if r.status_code != 200:
        return False, f"{name}: predict HTTP {r.status_code} after {took:.1f}s: {r.text[:160]}"
    result = " ".join(r.text.split())[:140]

    # The Gradio sidecar waits for the API, then builds its interface from the
    # API's swagger, so it answers some seconds after the API does. The first
    # version checked once, straight after predicting, and failed a module whose
    # prediction was correct because its page was still starting: 502 from
    # Traefik, meaning nothing listening yet. Three minutes, and say how long.
    ui_note, ok = "no ui endpoint", False
    if ui:
        t_ui, last = time.time(), ""
        while time.time() - t_ui < 180:
            try:
                u = requests.get(ui, verify=CA, timeout=30)
                if u.status_code == 200 and "gradio" in u.text.lower():
                    ui_note, ok = f"ui 200 after {time.time() - t_ui:.0f}s more", True
                    break
                last = f"ui {u.status_code}"
            except requests.RequestException as e:
                last = f"ui unreachable: {type(e).__name__}"
            time.sleep(5)
        else:
            ui_note = f"{last} for 180s"
    return ok, f"{name}: predict {took:.1f}s, {ui_note}: {result}"


def test_jupyter(info, password):
    ide = endpoint(info, "ide")
    if not ide:
        return False, "no ide endpoint published"
    s = requests.Session()
    s.verify = CA
    t0 = time.time()
    while time.time() - t0 < 300:          # JupyterLab is pip-installed at start
        try:
            r = s.get(f"{ide}/login", timeout=20)
            if r.status_code == 200 and "jupyter" in r.text.lower():
                break
        except requests.RequestException:
            pass
        time.sleep(5)
    else:
        return False, "JupyterLab never served /login"
    r = s.post(f"{ide}/login", params={"next": "/lab"}, allow_redirects=False, timeout=20,
               data={"password": password, "_xsrf": s.cookies.get("_xsrf", "")})
    if r.status_code != 302 or "/lab" not in r.headers.get("Location", ""):
        return False, f"login with the deployment password: HTTP {r.status_code}"
    listing = s.get(f"{ide}/api/contents/", timeout=20)
    names = [c["name"] for c in listing.json().get("content", [])] if listing.ok else []
    return True, f"login 302 -> /lab; /srv holds {', '.join(names[:3]) or 'nothing'}"


def record(rows, module, mode, verdict, ready_s, note):
    """Keep the row, and write it at once: an interrupted sweep keeps its results."""
    rows.append((module, mode, verdict, ready_s, note))
    fresh = not os.path.exists(RESULTS)
    os.makedirs(os.path.dirname(RESULTS), exist_ok=True)
    with open(RESULTS, "a", encoding="utf-8") as f:
        if fresh:
            f.write("date\tmodule\tmode\tverdict\tready_s\tnote\n")
        stamp = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        f.write(f"{stamp}\t{module}\t{mode}\t{verdict}\t{ready_s}\t{' '.join(note.split())}\n")
    say(f"  [{' ok ' if verdict == 'pass' else 'FAIL'}] {module:30} {mode:8} "
        f"{'running in ' + ready_s + 's; ' if ready_s else ''}{note}")


def delete(uuid, what):
    r = papi("DELETE", f"/deployments/modules/{uuid}", params={"vo": VO})
    if r.status_code != 200:
        say(f"  could not delete {uuid} ({what}): {r.status_code} — delete it by hand")


def run_all(pairs, datatypes, rows, window, timeout):
    """A rolling window rather than fixed batches.

    A module deployment reserves a whole core plus 500 MHz for its UI, so beside
    a running LLM only about six fit on this cluster. The first version
    submitted eight at once and waited for all of them: two queued for
    capacity, and would have been recorded as failures for the crime of
    waiting. Now each deployment is tested the moment it runs and deleted
    straight after, which is also what frees the capacity the next one needs.
    """
    queue = list(pairs)
    active = {}
    try:
        while queue or active:
            while queue and len(active) < window:
                module, mode = queue.pop(0)
                pw = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
                uuid, err = submit(module, mode, pw)
                if uuid is None:
                    record(rows, module, mode, "fail", "", err)
                    continue
                active[uuid] = {"module": module, "mode": mode, "pw": pw, "t0": time.time()}
                say(f"  deploying {module} ({mode})")
            for uuid in list(active):
                d = active[uuid]
                age = time.time() - d["t0"]
                info = papi("GET", f"/deployments/modules/{uuid}", params={"vo": VO}).json()
                st = info.get("status")
                if st == "running":
                    ok, note = test_deepaas(info, datatypes.get(d["module"], [])) \
                        if d["mode"] == "deepaas" else test_jupyter(info, d["pw"])
                    record(rows, d["module"], d["mode"], "pass" if ok else "fail", f"{age:.0f}", note)
                elif st in ("failed", "dead", "error", "complete") and age > 20:
                    record(rows, d["module"], d["mode"], "fail", "",
                           f"{st} after {age:.0f}s: {(info.get('error_msg') or '')[:200]}")
                elif age > timeout:
                    record(rows, d["module"], d["mode"], "fail", "",
                           f"never reached running in {timeout}s (last: {st})")
                else:
                    continue
                delete(uuid, f"{d['module']} {d['mode']}")
                del active[uuid]
            time.sleep(10)
    finally:
        for uuid, d in active.items():
            delete(uuid, f"{d['module']} {d['mode']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated substrings of module ids")
    ap.add_argument("--modes", default="deepaas,jupyter")
    ap.add_argument("--window", type=int, default=6, help="deployments alive at once")
    ap.add_argument("--timeout", type=int, default=1200, help="seconds from submission to running")
    args = ap.parse_args()

    wanted = [w for w in args.only.split(",") if w]
    modules = [m for m in papi("GET", "/catalog/modules").json()
               if not wanted or any(w in m for w in wanted)]
    detail = papi("GET", "/catalog/modules/detail").json()
    datatypes = {d["id"]: d.get("data-type") or [] for d in detail}
    modes = [m for m in args.modes.split(",") if m]
    say(f"{len(modules)} modules x {len(modes)} modes, at most {args.window} deployments at once")

    rows = []
    run_all([(m, mode) for m in modules for mode in modes], datatypes, rows, args.window, args.timeout)

    passed = sum(1 for r in rows if r[2] == "pass")
    say(f"\n{passed} of {len(rows)} passed. Results appended to {os.path.relpath(RESULTS, ROOT)}")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
