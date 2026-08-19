#!/usr/bin/env bash
# Copy vendored upstream into build/ and apply the CAIOS patches there.
# vendor/ is never modified.
#
#   bash scripts/apply-patches.sh
#
# Re-runnable: build/ is recreated from scratch each time.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

apply_repo() {
    local repo="$1"
    local src="vendor/$repo"
    local dst="build/$repo"
    local patchdir="patches/$repo"

    if [[ ! -d "$src" ]]; then
        echo "  skip $repo — not cloned. Run scripts/clone-vendor.sh first."
        return 0
    fi

    echo "==> $repo"
    # build/ai4-dashboard picks up root-owned files from the Docker build in
    # scripts/build-dashboard.sh, so a plain rm fails with "Permission denied"
    # partway through — leaving a half-deleted tree and, because of `set -e`,
    # skipping every repo after it. That is how ai4-dashboard came to be silently
    # left unpatched while ai4-papi looked fine.
    if ! rm -rf "$dst" 2>/dev/null; then
        echo "    (removing root-owned build output from a previous container build)"
        sudo rm -rf "$dst"
    fi
    mkdir -p "$(dirname "$dst")"
    cp -r "$src" "$dst"

    if [[ ! -d "$patchdir" ]]; then
        echo "    no patches"
        return 0
    fi

    shopt -s nullglob
    for p in "$patchdir"/*.patch; do
        if git -C "$dst" apply --check "$ROOT/$p" 2>/dev/null; then
            git -C "$dst" apply "$ROOT/$p"
            echo "    applied $(basename "$p")"
        else
            echo "    FAILED  $(basename "$p")"
            echo "            Upstream has moved. Read the patch, not the error —"
            echo "            patches/README.md explains what each one is for."
            exit 1
        fi
    done
    shopt -u nullglob
}

mkdir -p build
apply_repo ai4-papi
apply_repo ai4-nomad_tests
apply_repo ai4-dashboard

echo
echo "Patched sources are in build/. Build containers from there, not from vendor/."
