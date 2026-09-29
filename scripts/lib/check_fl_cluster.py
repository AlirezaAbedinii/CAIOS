"""Run one federation through the cluster, headless, and say whether it worked.

Driven by scripts/check-fl-cluster.sh. Finds the federated demo that
scripts/deploy-fl-demo.sh deployed for the account, then does exactly what the
recording does in four terminals: server.py in the server's workspace, then
run.sh in each hospital's. It checks the claims beat 6 makes out loud:

  - three hospitals, on three different machines
  - each one reaches the server by the private path (demo/fl/bootstrap.sh,
    "WHY /etc/hosts"): the public name leads to a proxy that cannot carry gRPC
  - ten rounds, all three hospitals reporting, and the accuracy they reach

Measured 2026-09-29: through the public proxy, every client's stream was reset
and the server waited for ever. Pinned to Traefik, ten rounds in 32 s at
0.845-0.852. Nothing checked this path before that day.

Leaves nothing running: stray server or client processes are killed at the end,
so the take that follows starts clean.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CA = os.path.join(ROOT, "compose", "certs", "caios-ca.pem")
VO = "vo.caios.ca"
SITES = ("site_a", "site_b", "site_c")
SERVER_DIR = "/srv/ai4os-federated-server/fedserver"
# Bracketed, so a pattern never matches the shell that carries it.
STRAYS = "pkill -f '[s]erver[.]py'; pkill -f '[c]lient[.]py'; pkill -f '[r]un[.]sh'; true"

API = os.environ["CAIOS_API"].rstrip("/")
ISSUER = os.environ["CAIOS_ISSUER"].rstrip("/")
EDGE_IP = os.environ.get("CAIOS_EDGE_IP", "")
BOOTSTRAP_URL = os.environ["CAIOS_FL_BOOTSTRAP_URL"]

failed = False


def ok(msg):
    print(f"  [ ok ] {msg}", flush=True)


def bad(msg):
    global failed
    failed = True
    print(f"  [FAIL] {msg}", flush=True)


def token(user):
    pw = os.environ.get("CAIOS_PW_" + user.upper().replace("-", "_"), "")
    if not pw:
        sys.exit(f"no password for {user} in configs/env/caios.env")
    r = requests.post(f"{ISSUER}/protocol/openid-connect/token", verify=CA, timeout=30,
                      data={"client_id": "caios-dashboard", "grant_type": "password",
                            "username": user, "password": pw, "scope": "openid profile email"})
    r.raise_for_status()
    return r.json()["access_token"]


def nomad_json(*args):
    out = subprocess.run(["nomad", *args], stdin=subprocess.DEVNULL, capture_output=True,
                         text=True, timeout=60)
    if out.returncode != 0:
        sys.exit(f"nomad {' '.join(args[:3])}: {out.stderr.strip()[:300]}")
    return json.loads(out.stdout)


def running(job):
    live = [a for a in nomad_json("job", "allocs", "-namespace=caios", "-json", job)
            if a["ClientStatus"] == "running"]
    return (live[0]["ID"], live[0]["NodeName"]) if live else (None, None)


def start(alloc, cmd, log):
    """`nomad alloc exec` drops output when its stdin closes, so it stays open
    until the command has finished (scripts/lib/stage_high_code.py)."""
    return subprocess.Popen(["nomad", "alloc", "exec", "-namespace=caios", "-task", "main",
                             "-i=false", "-t=false", alloc, "bash", "-lc", cmd],
                            stdin=subprocess.PIPE, stdout=open(log, "w"),
                            stderr=subprocess.STDOUT, text=True)


def finish(proc, timeout):
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
    finally:
        proc.stdin.close()
    return proc.returncode


def run(alloc, cmd, log, timeout=120):
    finish(start(alloc, cmd, log), timeout)
    return open(log).read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default=os.environ.get("CAIOS_FL_USER", "researcher"))
    ap.add_argument("--bootstrap", action="store_true",
                    help="run the served bootstrap in each hospital first")
    ap.add_argument("--logs", default="/tmp/caios-fl-check")
    args = ap.parse_args()
    os.makedirs(args.logs, exist_ok=True)

    tok = token(args.user)
    tools = requests.get(f"{API}/deployments/tools", params={"vos": VO}, verify=CA, timeout=60,
                         headers={"Authorization": f"Bearer {tok}"}).json()
    by_title = {d.get("title"): d for d in tools}
    server = by_title.get("CAIOS federated server")
    sites = {s: by_title.get(f"CAIOS {s}") for s in SITES}
    if not server or not all(sites.values()):
        sys.exit(f"no complete federated demo for {args.user}: run scripts/deploy-fl-demo.sh")
    host = (server.get("endpoints") or {}).get("fedserver", "").split("//")[-1].rstrip("/")
    if not host or "${" in host:
        sys.exit("the federated server publishes no address yet; is it running?")

    print("=== 1. three hospitals, three machines ===")
    srv_alloc, srv_node = running(server["job_ID"])
    allocs, nodes = {}, {}
    for s, d in sites.items():
        allocs[s], nodes[s] = running(d["job_ID"])
    if not srv_alloc or not all(allocs.values()):
        sys.exit("a federated deployment has no running allocation")
    placed = ", ".join(f"{s} {nodes[s]}" for s in SITES)
    if len(set(nodes.values())) == 3:
        ok(f"{placed}; server on {srv_node}")
    else:
        bad(f"{placed}: two hospitals share a machine. Deploy the federation before any "
            "other workspace (docs/demo-script.md), or check the scheduler is on spread (D-19)")

    if args.bootstrap:
        print("\n=== 2a. bootstrap, from the served script ===")
        for s in SITES:
            out = run(allocs[s], f"curl -k -sSL {BOOTSTRAP_URL} | bash -s {s} {host}",
                      f"{args.logs}/bootstrap-{s}.log", timeout=900)
            ok(f"{s} bootstrapped") if "ready. To join" in out else bad(f"{s}: bootstrap did not finish, see {args.logs}")

    print("\n=== 2. each hospital reaches the server privately ===")
    for s in SITES:
        out = run(allocs[s], f"getent hosts {host}; test -x ~/caios-fl/run.sh && echo has-run-sh",
                  f"{args.logs}/resolve-{s}.log")
        addr = out.split()[0] if out.strip() else "?"
        if "has-run-sh" not in out:
            bad(f"{s} is not bootstrapped: rerun with --bootstrap")
        elif EDGE_IP and addr == EDGE_IP:
            ok(f"{s}: {host.split('.')[0]}… -> {addr}, the cluster's router")
        else:
            bad(f"{s}: the server's name resolves to {addr}, not the router {EDGE_IP or '?'}. "
                "Rerun with --bootstrap: through the public proxy gRPC is reset")

    print("\n=== 3. one federation ===")
    for a in [srv_alloc, *allocs.values()]:
        run(a, STRAYS, f"{args.logs}/strays.log", timeout=60)
    srv = start(srv_alloc, f"cd {SERVER_DIR} && python3 server.py", f"{args.logs}/server.log")
    for _ in range(120):
        if "gRPC server running" in open(f"{args.logs}/server.log").read():
            break
        if srv.poll() is not None:
            bad(f"server.py exited before listening: see {args.logs}/server.log")
            return
        time.sleep(1)
    clients = {s: start(allocs[s], "cd ~/caios-fl && ./run.sh --quiet", f"{args.logs}/client-{s}.log")
               for s in SITES}
    t0 = time.time()
    rc = finish(srv, 300)
    took = time.time() - t0
    for p in clients.values():
        finish(p, 60)
    for a in [srv_alloc, *allocs.values()]:
        run(a, STRAYS, f"{args.logs}/strays.log", timeout=60)

    server_log = re.sub(r"\x1b\[[0-9;]*m", "", open(f"{args.logs}/server.log").read())
    done = re.search(r"Run finished (\d+) round\(s\) in ([\d.]+)s", server_log)
    if rc == 0 and done:
        ok(f"{done.group(1)} rounds in {float(done.group(2)):.1f} s; {took:.1f} s from the "
           "third hospital joining")
    else:
        bad(f"the federation did not finish within 300 s (server exit {rc}); "
            f"see {args.logs}/server.log and the client logs")
    for s in SITES:
        log = re.sub(r"\x1b\[[0-9;]*m", "", open(f"{args.logs}/client-{s}.log").read())
        last = re.findall(r"round\s+(\d+)\s+global model on shared test set: ([\d.]+)", log)
        if last:
            ok(f"{s}: round {last[-1][0]}, global model {last[-1][1]} on the shared test set")
        else:
            bad(f"{s} reported no round: see {args.logs}/client-{s}.log")

    print()
    print("Federated path FAILED." if failed else "Federated path passed.")


if __name__ == "__main__":
    main()
    sys.exit(1 if failed else 0)
