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

# 2. theme
mkdir -p "$DST/src/theme/caios"
cp "$CFG/theme/caios/variables.scss" "$CFG/theme/caios/_material.scss" "$DST/src/theme/caios/"

# 3. images
mkdir -p "$DST/src/assets/images/caios"
if compgen -G "$CFG/images/*" >/dev/null; then
    cp "$CFG"/images/* "$DST/src/assets/images/caios/"
else
    # Fall back to upstream artwork so the build succeeds before the real logo
    # exists. A build that fails for want of a favicon helps nobody.
    echo "    NOTE: configs/dashboard/images/ is empty — using placeholder artwork."
    echo "          Drop dashboard-logo.png, favicon.ico, forbidden.png and"
    echo "          not-found.png there before the demo."
    cp "$SRC"/src/assets/images/kmd4eosc/* "$DST/src/assets/images/caios/"
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
