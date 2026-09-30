#!/usr/bin/env bash
# Check that nothing sensitive is, or would be, pushed to GitHub.
#
#   bash scripts/check-secrets.sh          # everything below
#   bash scripts/check-secrets.sh --ci     # 1 and 2 only, for a fresh clone
#
# 1. gitleaks over every commit, with .gitleaks.toml (the default rules).
# 2. No tracked file that is sensitive by its name: env files, keys,
#    certificates, tokens, Vault's init output.
# 3. Every real secret in configs/env/caios.env, checked by VALUE against the
#    tracked files and the whole history. gitleaks finds secrets that look
#    like secrets; a password is just a string, so it has to be looked for
#    as itself.
#
# A secret in a tracked file fails the check. A secret only in history is a
# warning: it is already public, so the fix is to rotate it, not to block the
# push. Values are never printed, only the variable's name and the commits.
#
# The pre-push hook runs this (.githooks/pre-push; enable with
# `git config core.hooksPath .githooks`), and CI runs the --ci part.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
CI_ONLY=0; [[ "${1:-}" == "--ci" ]] && CI_ONLY=1
GITLEAKS_VERSION=8.21.2
fail=0; warn=0
ok()   { printf '  [ ok ] %s\n' "$*"; }
bad()  { printf '  [FAIL] %s\n' "$*"; fail=1; }
note() { printf '  [warn] %s\n' "$*"; warn=1; }

echo "=== 1. gitleaks, every commit ==="
if command -v gitleaks >/dev/null 2>&1; then
    run_gitleaks() { gitleaks git --config .gitleaks.toml --redact --no-banner "$ROOT" 2>&1; }
else
    DOCKER=docker; docker info >/dev/null 2>&1 || DOCKER="sudo -n docker"
    run_gitleaks() {
        $DOCKER run --rm -v "$ROOT:/repo:ro" "zricethezav/gitleaks:v$GITLEAKS_VERSION" \
            git --config /repo/.gitleaks.toml --redact --no-banner /repo 2>&1
    }
fi
out="$(run_gitleaks)"; rc=$?
if [[ $rc -eq 0 ]]; then
    ok "no leaks found ($(grep -o '[0-9]* commits scanned' <<<"$out" || echo 'history scanned'))"
else
    bad "gitleaks found something:"; sed 's/^/        /' <<<"$out" | tail -40
fi

echo "=== 2. no sensitive file is tracked ==="
tracked="$(git ls-files | grep -E '(^|/)(\.env|[^/]*\.env)$|\.(pem|key|crt|p12|pfx|jks)$|(_|-)token$|vault-init\.json$|(^|/)secrets/' \
           | grep -v -E '\.env\.template$|(^|/)template\.env$' || true)"
if [[ -z "$tracked" ]]; then ok "none"; else bad "tracked sensitive files:"; sed 's/^/        /' <<<"$tracked"; fi

if [[ $CI_ONLY -eq 1 ]]; then
    [[ $fail -eq 0 ]] && echo "Secrets check passed (CI)." || echo "Secrets check FAILED."
    exit $fail
fi

echo "=== 3. real values from configs/env/caios.env ==="
ENV_FILE="configs/env/caios.env"
if [[ ! -f "$ENV_FILE" ]]; then
    note "$ENV_FILE is absent here, so real values cannot be checked"
else
    python3 - "$ENV_FILE" <<'PY'
import re, subprocess, sys
from pathlib import Path

names = re.compile(r"PASSWORD|SECRET|TOKEN|(^|_)PW_|_KEY$")
env = {}
for line in Path(sys.argv[1]).read_text().splitlines():
    m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line.strip())
    if m:
        env[m.group(1)] = m.group(2).strip().strip("'\"")
secrets = {k: v for k, v in env.items() if names.search(k) and len(v) >= 6 and not v.startswith(("/", "$"))}

tracked = subprocess.run(["git", "ls-files", "-z"], capture_output=True, text=True).stdout.split("\0")
head_hits, hist_hits = {}, {}
for key, value in secrets.items():
    files = []
    for f in filter(None, tracked):
        try:
            if value in Path(f).read_text(errors="ignore"):
                files.append(f)
        except (IsADirectoryError, FileNotFoundError):
            pass
    if files:
        head_hits[key] = files
    commits = subprocess.run(["git", "log", "--all", "--format=%h %ad %s", "--date=short", "-S", value],
                             capture_output=True, text=True).stdout.strip()
    if commits:
        hist_hits[key] = commits.splitlines()

print(f"  checked {len(secrets)} secret values")
for key, files in head_hits.items():
    print(f"  [FAIL] {key} is in tracked files: {', '.join(files)}")
for key, commits in hist_hits.items():
    if key not in head_hits:
        print(f"  [warn] {key} is in git history, not in any tracked file. It is public: rotate it.")
        for c in commits:
            print(f"           {c}")
if not head_hits and not hist_hits:
    print("  [ ok ] none of them appears in any tracked file or commit")
sys.exit(2 if head_hits else (1 if hist_hits else 0))
PY
    case $? in
        0) ;;
        1) warn=1 ;;
        *) fail=1 ;;
    esac
fi

echo
if [[ $fail -ne 0 ]]; then echo "Secrets check FAILED: do not push."; exit 1; fi
if [[ $warn -ne 0 ]]; then echo "Secrets check passed, with warnings above."; else echo "Secrets check passed."; fi
exit 0
