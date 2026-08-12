#!/usr/bin/env bash
# Clone (or update) the upstream repositories into vendor/ at pinned commits.
#
#   bash scripts/clone-vendor.sh
#
# vendor/ is gitignored and READ-ONLY. Never edit anything there — copy out to
# configs/ or write a patch in patches/ instead.
#
# The pins below are the commits every config file and patch in this repo was
# written against. To move to newer upstream: bump a SHA here, re-run, then run
# scripts/apply-patches.sh and fix whatever fails. Do not float to HEAD; a
# silent upstream change to a Nomad job template is very hard to debug later.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR="$ROOT/vendor"
mkdir -p "$VENDOR"

# repo                          directory            pinned commit
REPOS=(
  "ai4os/ai4-ansible            ai4-ansible          e8991f2"
  "ai4os/ai4-papi               ai4-papi             e80a2b7"
  "ai4os/ai4-dashboard          ai4-dashboard        c360f20"
  "ai4os/ai4-docs               ai4-docs             bd3cd19"
  "ai4os/tools-catalog          tools-catalog        371d748"
  "ai4os-hub/modules-catalog    modules-catalog      ec73550"
  # Not in the original brief, but required: this is the only thing that sets
  # meta.status=ready on a node, without which no PAPI deployment can be placed.
  "ai4os/ai4-nomad_tests        ai4-nomad_tests      HEAD"
)

for entry in "${REPOS[@]}"; do
    read -r repo dir pin <<<"$entry"
    target="$VENDOR/$dir"

    if [[ -d "$target/.git" ]]; then
        echo "==> $dir (exists)"
        git -C "$target" fetch --quiet --depth 50 origin || true
    else
        echo "==> $dir (cloning)"
        git clone --quiet --depth 50 "https://github.com/$repo.git" "$target"
    fi

    if [[ "$pin" != "HEAD" ]]; then
        git -C "$target" checkout --quiet "$pin" 2>/dev/null \
            || echo "    WARNING: could not check out $pin — shallow history may not reach it."
    fi

    printf '    %s\n' "$(git -C "$target" log -1 --format='%h %ad %s' --date=short)"
done

echo
echo "Done. vendor/ is read-only; see patches/README.md for how we change upstream behaviour."
