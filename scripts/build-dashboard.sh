#!/usr/bin/env bash
# Assemble the CAIOS dashboard tenant into build/ai4-dashboard and build the image.
#
#   bash scripts/build-dashboard.sh            # stage files + build image
#   bash scripts/build-dashboard.sh --stage    # stage files only, no docker
#
# Upstream ships five tenants (ai4eosc, imagine, tutorials, ai4life, kmd4eosc).
# Adding a sixth means four things, all done here:
#   1. src/assets/config/caios.json      tenant config, merged over _base.json
#   2. src/theme/caios/                  variables.scss + _material.scss
#   3. src/assets/images/caios/          logo, favicon, error pages
#   4. angular.json                      caios-production build + serve targets
#
# Re-runnable. build/ is disposable; configs/ is the source of truth.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SRC="vendor/ai4-dashboard"
DST="build/ai4-dashboard"
CFG="configs/dashboard"

[[ -d "$SRC" ]] || { echo "vendor/ai4-dashboard missing. Run scripts/clone-vendor.sh."; exit 1; }

echo "==> staging tenant into $DST"
rm -rf "$DST"
mkdir -p build
cp -r "$SRC" "$DST"

# 0. source patches
#
# This script stages vendor/ -> build/ itself, which means it overwrites
# whatever scripts/apply-patches.sh put there. So the dashboard patches are
# applied here rather than relying on that script having run first — otherwise
# they are silently discarded and the build looks fine.
if compgen -G "patches/ai4-dashboard/*.patch" >/dev/null; then
    for p in patches/ai4-dashboard/*.patch; do
        if git -C "$DST" apply --check "$ROOT/$p" 2>/dev/null; then
            git -C "$DST" apply "$ROOT/$p"
            echo "    applied $(basename "$p")"
        else
            echo "    FAILED  $(basename "$p") — upstream has moved."
            echo "            Read the patch, not the error; see patches/README.md."
            exit 1
        fi
    done
fi

# 1. tenant config
#
# Annotations stripped on the way in. The image merges this over _base.json
# with jq and serves the result at /assets/config/config.json, so any _comment
# key here ends up published in the running page — including the notes naming
# the upstream URLs we replaced, which then read like leftover AI4EOSC
# references to anyone inspecting it.
#
# Third time this pattern has come up (Keycloak realm import, angular.json
# schema, now here): keep the notes in the source, strip them at the boundary.
python3 - "$CFG/caios.json" "$DST/src/assets/config/caios.json" <<'PYSTRIP'
import json, sys

def strip(o):
    if isinstance(o, dict):
        return {k: strip(v) for k, v in o.items() if not k.startswith("_comment")}
    if isinstance(o, list):
        return [strip(v) for v in o]
    return o

json.dump(strip(json.load(open(sys.argv[1]))), open(sys.argv[2], "w"), indent=4)
PYSTRIP

# 1b. the LLM model catalogue
#
# One file, two consumers. PAPI reads configs/papi/vllm.yaml to build the deploy
# form's dropdown; the dashboard reads it to draw the model cards and to decide
# whether the Hugging Face token field is required. Upstream had the dashboard
# fetching AI4OS's copy from raw.githubusercontent.com, so the cards described
# thirteen models while the dropdown offered our nine — see patch 0002.
#
# Copied verbatim: unlike the tenant config there are no annotations to strip,
# because YAML comments are comments and js-yaml drops them. The comments in
# that file explain measured vLLM behaviour and are worth keeping in the source.
cp configs/papi/vllm.yaml "$DST/src/assets/config/vllm.yaml"
models=$(grep -cE '^  [A-Za-z0-9_./-]+:$' "$DST/src/assets/config/vllm.yaml")
echo "    staged the LLM catalogue ($models models)"

# 2. theme
#
# Four files now, not two. overrides.scss is the one loaded AFTER upstream's
# src/styles.scss — see the header of that file for why the position matters —
# and _fonts.scss is the generated @font-face block it imports.
mkdir -p "$DST/src/theme/caios"
cp "$CFG/theme/caios/variables.scss" \
   "$CFG/theme/caios/_material.scss" \
   "$CFG/theme/caios/_fonts.scss" \
   "$CFG/theme/caios/overrides.scss" \
   "$DST/src/theme/caios/"

# 2b. fonts — staged but NOT yet used
#
# Stage F1 is shelved (see the top of scripts/fetch-fonts.sh). index.html still
# loads its typefaces from Google and overrides.scss does not import
# _fonts.scss, so these files are staged and served but nothing references
# them. Staging them keeps the image and the repository in step, and makes
# finishing F1 a one-line change rather than a rebuild of this pipeline.
#
# A warning rather than a hard failure, precisely because nothing depends on
# them right now. When F1 is finished this must become an error again: with the
# Google <link> tags gone, missing files here mean every icon renders as the
# word it is named after, behind nginx's HTTP 200.
if compgen -G "$CFG/fonts/*.woff2" >/dev/null; then
    mkdir -p "$DST/src/assets/fonts"
    cp "$CFG"/fonts/*.woff2 "$DST/src/assets/fonts/"
    echo "    staged $(ls "$CFG"/fonts/*.woff2 | wc -l) font files (unused — F1 shelved)"
else
    echo "    no fonts in $CFG/fonts/ — fine while F1 is shelved"
fi

# 3. images
mkdir -p "$DST/src/assets/images/caios"

# Check for the four files by name, not for "is the directory non-empty".
#
# It used to test `compgen -G "$CFG/images/*"`, which matched the README.md
# sitting in that directory explaining what to put there. So the fallback never
# ran, only README.md was copied, and the dashboard shipped with no logo and no
# favicon at all — nginx's SPA fallback then answered /assets/images/
# dashboard-logo.png with index.html and HTTP 200, so every page had a broken
# image in the top-left and nothing looked like an error.
#
# Generate them with: demo/.venv/bin/python scripts/make-brand-assets.py
# pacslab-logo.png is referenced by patches/ai4-dashboard/0001: it sits beside
# the CAIOS mark at the bottom of the sidenav, where upstream shows an EU flag.
REQUIRED_IMAGES=(dashboard-logo.png favicon.ico forbidden.png not-found.png pacslab-logo.png)
missing_images=()
for img in "${REQUIRED_IMAGES[@]}"; do
    [[ -s "$CFG/images/$img" ]] || missing_images+=("$img")
done

if (( ${#missing_images[@]} == 0 )); then
    for img in "${REQUIRED_IMAGES[@]}"; do
        cp "$CFG/images/$img" "$DST/src/assets/images/caios/"
    done
    echo "    using CAIOS artwork (${#REQUIRED_IMAGES[@]} files)"
else
    # Fall back to upstream artwork so the build still succeeds. A build that
    # fails for want of a favicon helps nobody — but say so loudly, because
    # shipping another project's logo defeats the point of branding (D-08).
    echo "    WARNING: missing CAIOS artwork: ${missing_images[*]}"
    echo "             falling back to upstream KMD4EOSC images — the dashboard"
    echo "             will carry somebody else's logo."
    for img in "${missing_images[@]}"; do
        if [[ "$img" == "pacslab-logo.png" ]]; then
            # Supplied, not generated: it is another organisation's mark and we
            # do not draw our own version of it.
            echo "             $img is supplied by PACS Lab — save the official"
            echo "               file to $CFG/images/$img"
        else
            echo "             $img: demo/.venv/bin/python scripts/make-brand-assets.py"
        fi
    done
    cp "$SRC"/src/assets/images/kmd4eosc/* "$DST/src/assets/images/caios/"
fi

# 3b. LLM catalogue card badges
#
# The card renders assets/images/llm-companies/{family}_logo.png, where family
# comes from vllm.yaml. Our nine models span five families; upstream ships a
# badge for two of them (Qwen, deepseek-ai) plus meta-llama, which we dropped.
# The other three are Mistral, LiquidAI and IBM, and LiquidAI alone is four of
# the nine — so without these, six of nine cards render a broken image. Because
# nginx answers every missing path with index.html and HTTP 200, nothing reports
# it. Same failure that once shipped this dashboard with no logo at all.
#
# tests/test_dashboard_catalogue.py fails if a family here has no badge, so
# adding a model with a new family cannot quietly reintroduce it.
if compgen -G "$CFG/images/llm-companies/*.png" >/dev/null; then
    mkdir -p "$DST/src/assets/images/llm-companies"
    cp "$CFG"/images/llm-companies/*.png "$DST/src/assets/images/llm-companies/"
    echo "    added $(ls "$CFG"/images/llm-companies/*.png | wc -l) model-family badges"
else
    echo "    WARNING: no model-family badges in $CFG/images/llm-companies/"
    echo "             cards for families upstream does not ship will show a"
    echo "             broken image. Generate them with:"
    echo "               demo/.venv/bin/python scripts/make-brand-assets.py"
fi

# 4. angular.json build + serve targets
python3 - "$DST/angular.json" "$CFG/angular-configurations.json" <<'PY'
import json, sys

angular_path, cfg_path = sys.argv[1], sys.argv[2]

with open(angular_path) as f:
    angular = json.load(f)
with open(cfg_path) as f:
    cfg = json.load(f)

project = angular["projects"]["ai4-dashboard"]
targets = project.get("architect") or project["targets"]


def strip_comments(o):
    """Remove _comment* keys at every level.

    The configuration file is annotated so the next person can see why the
    style and asset ordering matters. Angular validates angular.json against a
    schema that rejects unknown properties, so those notes have to come out on
    the way in — a top-level strip is not enough, because the notes sit inside
    each configuration block:

        Schema validation failed: Data path "" must NOT have additional
        properties(_comment_styles).
    """
    if isinstance(o, dict):
        return {k: strip_comments(v) for k, v in o.items()
                if not k.startswith("_comment")}
    if isinstance(o, list):
        return [strip_comments(v) for v in o]
    return o


for target in ("build", "serve"):
    targets[target].setdefault("configurations", {}).update(
        strip_comments(cfg[target])
    )

with open(angular_path, "w") as f:
    json.dump(angular, f, indent=2)
    f.write("\n")

print("    angular.json: added", ", ".join(
    f"{t}:{c}" for t in ("build", "serve")
    for c in cfg[t] if not c.startswith("_comment")
))
PY

# index.html title — the only branding string outside the tenant config
sed -i 's|<title>AI4Dashboard</title>|<title>CAIOS</title>|' "$DST/src/index.html"

echo "==> staged"

if [[ "${1:-}" == "--stage" ]]; then
    echo "Stopping before docker build (--stage)."
    exit 0
fi

command -v docker >/dev/null || { echo "docker not found; staged only."; exit 0; }

echo "==> building image caios/dashboard:latest"
docker build \
    -f "$DST/docker/Dockerfile.prod" \
    --build-arg TENANT=caios \
    -t caios/dashboard:latest \
    "$DST"

cat <<'EOF'

Built caios/dashboard:latest.

Runtime configuration is injected at container start, not baked in, so the
following can change without a rebuild:
  API_SERVER  ISSUER  CLIENT_ID  DUMMY_CLIENT_SECRET
compose/docker-compose.yml sets them from configs/env/caios.env.
EOF
