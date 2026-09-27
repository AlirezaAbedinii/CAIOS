"""The two calls the high-code notebook makes to the rest of the platform.

`scripts/stage-high-code.sh` writes .caios.json and .caios-ca.pem beside this
file — dotfiles, so the file browser on camera does not list them — so no endpoint, token or key is ever typed into the notebook or shown on
screen. The notebook itself stays about the model.

    serverless(path)  the same YOLO model, as the low-code tier's OSCAR service
    ask(prompt)       the private language model from the no-code tier

Both verify TLS against the CAIOS CA rather than switching verification off
(D-43): the point of the demo is that nothing leaves the platform, and a
request that does not check who it is talking to undercuts that.
"""

import ast
import base64
import json
import pathlib
import re

import requests

HERE = pathlib.Path(__file__).resolve().parent
CONFIG = json.loads((HERE / ".caios.json").read_text())
CA = str(HERE / ".caios-ca.pem")


def serverless(image_path):
    """Send an image to the OSCAR service; return its detections."""
    svc = CONFIG["serverless"]
    data = base64.b64encode(pathlib.Path(image_path).read_bytes()).decode()
    r = requests.post(
        svc["endpoint"],
        json={"oscar-files": [{"key": "files", "file_format": "jpg", "data": data}]},
        headers={"Authorization": f"Bearer {svc['token']}"},
        verify=CA,
        timeout=300,
    )
    r.raise_for_status()
    try:
        # A service created after docs/demo-plan.md step 4 answers with the
        # result itself.
        result = r.json()
    except ValueError:
        # Upstream's service script answers with the job's log; the result is
        # the line DEEPaaS starts with "return:", as a Python literal. Some
        # DEEPaaS versions colour that line, hence the escape stripping.
        line = next(l for l in r.text.splitlines() if "return:" in l)
        line = re.sub(r"\x1b\[[0-9;]*m", "", line)
        result = ast.literal_eval(line.split("return:", 1)[1].strip())
    return result[0] if result and isinstance(result[0], list) else result


def ask(prompt, max_tokens=120):
    """One question to the private language model; return its answer."""
    llm = CONFIG["llm"]
    r = requests.post(
        f"{llm['endpoint']}/v1/chat/completions",
        # temperature 0: the most likely answer, the same one every time. A
        # recording is retaken, and a 2B model sampling at the default
        # temperature once "found" a missing stop sign in this very prompt.
        json={"model": llm["model"], "max_tokens": max_tokens, "temperature": 0,
              "messages": [{"role": "user", "content": prompt}]},
        headers={"Authorization": f"Bearer {llm['key']}"},
        verify=CA,
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()
