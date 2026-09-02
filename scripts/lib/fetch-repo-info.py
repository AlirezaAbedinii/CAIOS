#!/usr/bin/env python3
"""Fetch licence and dates for each catalogue repository from the GitHub API.

    python3 scripts/lib/fetch-repo-info.py <repo-list> <output.json>

Called by scripts/mirror-catalogue.sh. Reads one `owner/repo` per line and
writes a JSON object keyed by that string:

    {"ai4os-hub/ai4os-yolo-torch": {"created": ..., "updated": ..., "license": "AGPL-3.0"}}

WHY THIS EXISTS

`ai4-metadata.yml` (schema 2.0.0) has no `license` key, so a module's licence is
only ever known from its repository. PAPI reads that from api.github.com — but
only when `IS_PROD` is true, and `IS_PROD` must be false for CAIOS (gotcha 1).
`IS_DEV` therefore short-circuits `utils.get_github_info()` to a mock that says
`MIT` and `1970-01-01`, and PAPI writes it over the real metadata, so every
module in the marketplace reported MIT.

Doing the lookup here rather than at request time keeps the platform offline
during a demo and stays well inside GitHub's unauthenticated rate limit of 60
requests an hour per IP — fifteen entries per refresh, rather than fifteen per
cold page load.

A repository that cannot be read is omitted rather than guessed at. PAPI then
shows no licence for it, which is the honest answer and is what D-50 asks for:
an absent value is a state, not a failure.
"""

import json
import sys
import urllib.error
import urllib.request

TIMEOUT = 20


def fetch(repo: str) -> dict | None:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}",
        headers={"Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as f:
            d = json.load(f)
    except urllib.error.HTTPError as e:
        # 403 here is nearly always the rate limit rather than a private repo.
        note = "rate limited (60/hour/IP)" if e.code == 403 else f"HTTP {e.code}"
        print(f"  [warn] {repo} — {note}; licence will be absent")
        return None
    except Exception as e:  # network, DNS, timeout
        print(f"  [warn] {repo} — {e.__class__.__name__}; licence will be absent")
        return None

    return {
        "created": (d.get("created_at") or "")[:10],
        "updated": (d.get("updated_at") or "")[:10],
        # spdx_id is "NOASSERTION" when GitHub sees a LICENSE file it cannot
        # identify. Reporting that verbatim is better than reporting nothing:
        # it says a licence exists and has to be read, rather than implying none.
        "license": ((d.get("license") or {}).get("spdx_id") or ""),
    }


def main() -> int:
    repos = [line.strip() for line in open(sys.argv[1]) if line.strip()]
    out: dict[str, dict] = {}

    for repo in repos:
        info = fetch(repo)
        if info is None:
            continue
        out[repo] = info
        print(f"  [ ok ] {repo} — {info['license'] or '(none declared)'}")

    with open(sys.argv[2], "w") as f:
        json.dump(out, f, indent=1, sort_keys=True)
        f.write("\n")

    print(f"  [ ok ] {len(out)}/{len(repos)} repositories")

    # A completely empty result means the API was unreachable or exhausted, not
    # that these repositories have no licences. Fail so the mirror says so.
    return 0 if out else 1


if __name__ == "__main__":
    sys.exit(main())
