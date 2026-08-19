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
    "API_ENDPOINT": "https://vllm-abc123def456.${meta.domain}-deployments.192.168.104.105.sslip.io/v1",
    "HUGGINGFACE_TOKEN": "",
    "OPEN_WEBUI_USERNAME": "researcher@example.org",
    "OPEN_WEBUI_PASSWORD": "hunter2",
}


def render(path, subs=None):
    with open(path, encoding="utf-8") as f:
        return Template(f.read()).safe_substitute(subs or LLM_SUBS)


if __name__ == "__main__":
    import sys

    print(render(sys.argv[1]))
