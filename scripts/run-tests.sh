#!/usr/bin/env bash
# Run the CAIOS unit tests.
#
#   bash scripts/run-tests.sh              # everything
#   bash scripts/run-tests.sh -k llm       # a subset, pytest -k syntax
#
# Offline. No cluster, no Nomad, no network. These read the files in this
# repository and assert things about them, so they run in seconds and can run on
# every change — which is the point. Anything needing the live cluster is a
# scripts/check-*.sh smoke test instead.
#
# The virtualenv is created once at .venv-tests/ and reused. It is gitignored.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV="$ROOT/.venv-tests"

if [[ ! -x "$VENV/bin/pytest" ]]; then
    echo "Creating the test virtualenv at $VENV ..."
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet -r tests/requirements.txt
fi

# tests/ on the path so the tests can import conftest and render directly, which
# keeps them readable.
exec env PYTHONPATH="$ROOT/tests" "$VENV/bin/pytest" tests/ -q "$@"
