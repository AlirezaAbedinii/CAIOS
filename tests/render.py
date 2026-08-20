"""Render a PAPI job template the way PAPI does, for tests and for `nomad job validate`.

PAPI uses string.Template.safe_substitute, so ${UPPERCASE} keys it knows are
replaced and Nomad's own ${lowercase} interpolations survive untouched. Anything
that behaves differently here would not be testing the real thing.
"""

import json
from string import Template

# The same keys routers/v1/deployments/tools.py passes for ai4os-llm, with
# representative values.
LLM_SUBS = {
    "JOB_UUID": "abc123def456",
    "NAMESPACE": "caios",
    "PRIORITY": "50",
    "OWNER": "owner-id",
    "OWNER_NAME": "Test Researcher",
    "OWNER_EMAIL": "researcher@example.org",
    "TITLE": "Test LLM",
    "DESCRIPTION": "A test deployment",
    "BASE_DOMAIN": "deployments.192.168.104.105.sslip.io",
    "HOSTNAME": "abc123def456",
    "VLLM_ARGS": json.dumps(
        ["--gpu-memory-utilization", "0.80", "--max-model-len", "16384", "Qwen/Qwen3.5-2B"]
    ),
    "API_TOKEN": "0123456789abcdef",
    # What patch 0010 substitutes for a "both" deployment. Upstream puts the
    # public vLLM hostname here; that is what left Open WebUI with an empty
    # model list behind an HTTP 200 in Stage L4. The rendered job is the only
    # place a test can see this value, so it has to be the real one.
    "API_ENDPOINT": "http://${NOMAD_ADDR_vllm}/v1",
    "HUGGINGFACE_TOKEN": "",
    "OPEN_WEBUI_USERNAME": "researcher@example.org",
    "OPEN_WEBUI_PASSWORD": "hunter2",
}

# A standalone "open-webui" deployment keeps pointing at whatever endpoint the
# user supplied, which is the one case where leaving the cluster is correct.
STANDALONE_UI_SUBS = {
    **LLM_SUBS,
    "API_ENDPOINT": "https://someone-elses-llm.example.org/v1",
}


def render(path, subs=None):
    with open(path, encoding="utf-8") as f:
        return Template(f.read()).safe_substitute(subs or LLM_SUBS)


if __name__ == "__main__":
    import sys

    print(render(sys.argv[1]))
