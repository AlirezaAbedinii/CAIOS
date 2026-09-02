#!/usr/bin/env bash
# Mirror the marketplace catalogue so the platform never reads GitHub at request
# time.
#
#   bash scripts/mirror-catalogue.sh
#
# WHY THIS EXISTS
#
# PAPI builds the marketplace from raw.githubusercontent.com on every cold
# request: one fetch for the catalogue's .gitmodules, then one per entry for its
# ai4-metadata.yml — about fifteen requests for a full page. That host is
# Fastly-fronted and it went unreachable from every CAIOS node for roughly three
# hours on 2026-09-01 while api.github.com, github.com, Docker Hub and Hugging
# Face all kept working. requests.Session() carries no timeout, so the failure
# arrives as a page that spins rather than a page that errors.
#
# The dependency is on the demo's critical path: Modules and Tools are the only
# routes to a JupyterLab workspace (the high-code use case) and to
# "Deploy -> Inference API (serverless)" (the low-code one, which lives on a
# module detail page).
#
# So we mirror it, and PAPI reads the mirror. Fifth application of a pattern the
# project already has: self-hosted fonts, icons, vllm.yaml and the status feed.
#
# THE LAYOUT IS NOT ARBITRARY
#
# It reproduces raw.githubusercontent.com's own path structure exactly:
#
#   <mirror>/<owner>/<repo>/<branch>/<file>
#
# which is what lets patches/ai4-papi/0014 be a single base-URL swap rather than
# a rewrite of how the catalogue is addressed. Get the paths wrong and the patch
# has to grow.
#
# HOW IT FETCHES
#
# Over github.com (140.82.x), which is a different network path from
# raw.githubusercontent.com (185.199.x) and stayed up throughout the outage.
# Shallow, blobless, single-file checkouts — a few hundred KB for the whole run.
#
# Re-runnable. Refresh whenever the catalogue changes; the output is committed
# so that a fresh clone can serve the marketplace with no internet at all.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="configs/env/caios.env"
if [[ -f "$ENV_FILE" ]]; then
    set -a; source "$ENV_FILE"; set +a
fi

MODULES_REPO="${MODULES_CATALOGUE_REPO:-ai4os-hub/modules-catalog}"
TOOLS_REPO="${TOOLS_CATALOGUE_REPO:-ai4os/tools-catalog}"

# The AI4Life model list. PAPI reads it for the loader's dropdown; the dashboard
# reads the same file for its AI4Life tab. One path, both consumers.
AI4LIFE_REPO="ai4os/ai4os-ai4life-loader"
AI4LIFE_REF="refs/heads/main"
AI4LIFE_FILE="models/filtered_models.json"

OUT="catalog/mirror"
MANIFEST="$OUT/MANIFEST.txt"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail=0
ok()   { printf '  [ ok ] %s\n' "$1"; }
bad()  { printf '  [FAIL] %s\n' "$1"; fail=1; }
warn() { printf '  [warn] %s\n' "$1"; }

# Fetch one file from a GitHub repo at a ref, without cloning its history or its
# blobs. Writes to $3. Prints the commit it came from on stdout.
#
# --filter=blob:none --no-checkout fetches the tree but no file contents; the
# checkout that follows then pulls exactly the one blob asked for.
fetch_file() {
    local url="$1" branch="$2" dest="$3" file="$4"
    local dir="$TMP/$(echo "$url$file" | md5sum | cut -c1-12)"

    local args=(clone --depth 1 --filter=blob:none --no-checkout --quiet)
    [[ -n "$branch" ]] && args+=(--branch "$branch")

    if ! git "${args[@]}" "$url" "$dir" 2>/dev/null; then
        return 1
    fi
    if ! git -C "$dir" checkout HEAD -- "$file" 2>/dev/null; then
        return 2
    fi
    mkdir -p "$(dirname "$dest")"
    cp "$dir/$file" "$dest"
    git -C "$dir" rev-parse HEAD
}

# Mirror one catalogue: its .gitmodules, then every entry's ai4-metadata.yml.
#
# PAPI addresses the catalogue's .gitmodules at <repo>/master/.gitmodules with
# `master` hardcoded, so that path is literal here whatever the fork's default
# branch is actually called.
mirror_catalogue() {
    local repo="$1" label="$2"
    echo "=== $label — $repo ==="

    local gm_dest="$OUT/$repo/master/.gitmodules"
    local sha
    if ! sha="$(fetch_file "https://github.com/$repo" "" "$gm_dest" ".gitmodules")"; then
        bad "cannot fetch .gitmodules for $repo"
        return 1
    fi
    ok ".gitmodules ($(grep -c '^\[submodule' "$gm_dest") entries) @ ${sha:0:8}"
    echo "$repo/master/.gitmodules $sha" >> "$MANIFEST"

    # Parse the submodule stanzas. Each carries a path, a url and usually a
    # branch; PAPI falls back to `master` when the branch is absent, so the
    # mirror must file it under `master` too even if the repo's real default
    # branch is called something else.
    python3 - "$gm_dest" <<'PY' > "$TMP/entries"
import configparser, sys
cfg = configparser.ConfigParser()
cfg.read_string(open(sys.argv[1]).read())
for s in cfg.sections():
    d = dict(cfg.items(s))
    url = d["url"].replace(".git", "")
    # PAPI: items[name].get("branch", "master")
    print(f'{d["path"]}\t{url}\t{d.get("branch", "")}')
PY

    while IFS=$'\t' read -r name url branch; do
        [[ -z "$name" ]] && continue
        # The path PAPI will ask for, which uses its own fallback.
        local papi_branch="${branch:-master}"
        local owner_repo="${url#https://github.com/}"
        local dest="$OUT/$owner_repo/$papi_branch/ai4-metadata.yml"

        local s rc
        s="$(fetch_file "$url" "$branch" "$dest" "ai4-metadata.yml")"; rc=$?
        if [[ $rc -eq 1 ]]; then
            bad "$name — cannot clone $url"
        elif [[ $rc -eq 2 ]]; then
            # Upstream tolerates this: _get_metadata() reports "the module is
            # lacking a metadata file". Mirror the absence rather than inventing
            # a file, so behaviour matches.
            warn "$name — no ai4-metadata.yml in the repo (upstream tolerates this)"
        else
            ok "$name @ ${s:0:8}"
            echo "$owner_repo/$papi_branch/ai4-metadata.yml $s" >> "$MANIFEST"
        fi

        # The licence and repository dates, which are NOT in ai4-metadata.yml —
        # schema 2.0.0 has no `license` key at all, so upstream reads them from
        # the GitHub API. See repo_info() for why that has to happen here.
        echo "$owner_repo" >> "$TMP/repos"
    done < "$TMP/entries"
}

# Mirror the licence and dates for every entry, from api.github.com.
#
# WHY THIS IS SEPARATE, AND WHY IT MATTERS
#
# ai4-metadata.yml (schema 2.0.0) carries no licence field at all. Upstream
# fills it from api.github.com — but only when IS_PROD is true. IS_PROD must be
# false here (gotcha 1), which makes IS_DEV true, which makes
# utils.get_github_info() return a mock: {"created": "1970-01-01", "updated":
# "1970-01-01", "license": "MIT"}. Written through unconditionally, as upstream
# does, that made EVERY module in the marketplace report MIT and 1970.
#
# Not cosmetic. ai4os-yolo-torch wraps Ultralytics YOLO and is AGPL-3.0;
# posenet-tf is Apache-2.0. Presenting either as MIT misstates a third party's
# terms to our own users. See docs/licensing.md.
#
# api.github.com is a different host from raw.githubusercontent.com — 140.82.x
# rather than 185.199.x — and stayed reachable throughout the 2026-09-01 outage.
# It is rate limited to 60 requests an hour per IP unauthenticated, which is
# ample for a mirror refresh of fifteen entries and would not be ample per page
# load. That asymmetry is the whole argument for doing it here.
repo_info() {
    echo "=== Licences and dates ==="
    local out="$OUT/repo-info.json"
    sort -u "$TMP/repos" > "$TMP/repos.uniq"

    if python3 scripts/lib/fetch-repo-info.py "$TMP/repos.uniq" "$out"; then
        echo "repo-info.json (from api.github.com)" >> "$MANIFEST"
    else
        bad "could not build repo-info.json — licences would fall back to blank"
    fi
}

echo "Mirroring into $OUT/"
echo

# Empty IN PLACE, never rm -rf + mkdir. D-44, learned the hard way twice now:
# compose bind-mounts this directory into Caddy at /srv/catalog, and a bind
# mount follows the INODE rather than the path. Recreating the directory gives
# it a new inode, so Caddy goes on serving the deleted one — every /mirror/ URL
# 404s while the freshly built files sit on the host looking perfect. The host
# and the container disagree, and only the container's view matters.
mkdir -p "$OUT"
find "$OUT" -mindepth 1 -delete
{
    echo "# Catalogue mirror — generated by scripts/mirror-catalogue.sh"
    echo "# $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "#"
    echo "# <path served>  <upstream commit it came from>"
} > "$MANIFEST"

mirror_catalogue "$MODULES_REPO" "Modules"
echo
mirror_catalogue "$TOOLS_REPO" "Tools"
echo

echo "=== AI4Life model list ==="
ai4life_dest="$OUT/$AI4LIFE_REPO/$AI4LIFE_REF/$AI4LIFE_FILE"
if sha="$(fetch_file "https://github.com/$AI4LIFE_REPO" "main" "$ai4life_dest" "$AI4LIFE_FILE")"; then
    count="$(python3 -c "import json;print(len(json.load(open('$ai4life_dest'))))" 2>/dev/null || echo '?')"
    ok "$AI4LIFE_FILE ($count models) @ ${sha:0:8}"
    echo "$AI4LIFE_REPO/$AI4LIFE_REF/$AI4LIFE_FILE $sha" >> "$MANIFEST"
else
    bad "cannot fetch $AI4LIFE_FILE"
fi

repo_info
echo

echo "=== summary ==="
printf '  %s files, %s\n' \
    "$(find "$OUT" -type f ! -name MANIFEST.txt | wc -l)" \
    "$(du -sh "$OUT" | cut -f1)"

if [[ $fail -ne 0 ]]; then
    echo
    echo "MIRROR INCOMPLETE — the platform would serve a partial catalogue."
    exit 1
fi
echo "  mirror complete"
