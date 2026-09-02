#!/usr/bin/env bash
# Set one hospital's workspace up for federated learning. Run inside the
# JupyterLab (or VS Code) terminal of a dev environment deployed from CAIOS.
#
#   curl -k -sSL <dashboard>/fl/bootstrap.sh | bash -s site_a
#   curl -k -sSL <dashboard>/fl/bootstrap.sh | bash -s site_a fedserver-<uuid>.<domain>
#
# The scheme follows CAIOS_SCHEME; scripts/build-fl-bundles.sh prints the exact
# line, and the bundle carries it baked in.
#
# Fetches that site's bundle — its own data, the shared test set, the client,
# the model, and the CAIOS CA — installs the pinned Flower release, and writes a
# ready-to-run command. Given the federated server's hostname as a second
# argument, the command is filled in completely.
#
# WHY curl -k HERE
#
# Under CAIOS_SCHEME=https: the workspace container does not trust the CAIOS CA,
# and this is the request that fetches it, so there is nothing to verify against
# yet. The exposure is one download inside a private subnet reachable only over
# the VPN.
#
# Under CAIOS_SCHEME=http it does nothing at all — there is no certificate to
# skip. It is kept so the same bundle works either way.
#
# Either way it says nothing about the federated connection itself, which is
# verified properly: client.py passes this CA to gRPC explicitly and a wrong
# certificate fails the handshake. The federated server keeps TLS under both
# schemes (D-67), so that check is real in both.
#
# WHY THE FLOWER VERSION IS PINNED
#
# The deployed server runs a fork of Flower based on 1.16.0. `pip install flwr`
# would fetch whatever is current, and a client on a different major will
# connect, sit there, and time out without saying why.
#
# WHY THE OPENAI CLIENT IS HERE AT ALL
#
# It has nothing to do with federated learning. It is here because the demo's
# last beat calls a CAIOS-hosted language model from this same workspace — the
# argument being that a hospital's own code can use the private model, not just
# a chat window. Installing it takes five seconds and belongs at bootstrap
# rather than on camera.
#
# Under https it needs the CA in the bundle to reach the endpoint at all: the
# deployment is served by Traefik under our own certificate, which this
# container does not trust (docs/llm-risks.md R-05). The notebook points
# SSL_CERT_FILE at caios-ca.pem and verifies properly. Under http the vLLM
# endpoint needs no certificate and SSL_CERT_FILE is simply unused.
#
# Checked against the federated path: flwr 1.16.0, TensorFlow 2.14 and numpy
# 1.26 are unchanged by it, and `pip check` reports nothing new.
set -euo pipefail

SITE="${1:-}"
SERVER="${2:-}"
BASE_URL="${CAIOS_FL_BASE:-@@FL_BASE_URL@@}"
WORKDIR="${CAIOS_FL_DIR:-$HOME/caios-fl}"
FLWR_VERSION="1.16.0"
OPENAI_VERSION="2.9.0"

case "$SITE" in
    site_a|site_b|site_c) ;;
    *) echo "usage: bootstrap.sh <site_a|site_b|site_c> [fedserver-<uuid>.<domain>]"; exit 1 ;;
esac

echo "==> fetching the $SITE bundle from $BASE_URL"
mkdir -p "$WORKDIR"
curl -k -sSL --fail "$BASE_URL/caios-fl-$SITE.tar.gz" -o "$WORKDIR/bundle.tar.gz"
tar xzf "$WORKDIR/bundle.tar.gz" -C "$WORKDIR" --strip-components=1
rm -f "$WORKDIR/bundle.tar.gz"

echo "==> installing flwr==$FLWR_VERSION (TensorFlow is already in this image)"
python3 -m pip install --quiet --disable-pip-version-check "flwr==$FLWR_VERSION"

echo "==> installing openai==$OPENAI_VERSION (for the language-model beat)"
python3 -m pip install --quiet --disable-pip-version-check "openai==$OPENAI_VERSION"

echo "==> checking the bundle"
for f in client.py model.py caios-ca.pem "data/$SITE.npz" data/test.npz; do
    [[ -s "$WORKDIR/$f" ]] || { echo "    MISSING: $f"; exit 1; }
done
python3 - <<PY
import numpy as np
d = np.load("$WORKDIR/data/$SITE.npz", allow_pickle=True)
print(f"    {len(d['x'])} local slices, {len(np.unique(d['pid']))} patients")
PY

# Both imports, here rather than in front of an audience. A version conflict
# between these two would otherwise surface as a traceback in the last beat.
python3 -c "import flwr, openai" || {
    echo "    flwr and openai do not both import — do not start the demo"
    exit 1
}

RUN="python3 client.py --site $SITE --ca caios-ca.pem --server ${SERVER:-<FEDSERVER_HOST>}:443"
printf '#!/usr/bin/env bash\ncd "$(dirname "$0")"\nexec %s "$@"\n' "$RUN" > "$WORKDIR/run.sh"
chmod +x "$WORKDIR/run.sh"

echo
echo "==> ready. To join the federation:"
echo
echo "    cd $WORKDIR && $RUN"
echo
if [[ -z "$SERVER" ]]; then
    echo "    Replace <FEDSERVER_HOST> with the federated server's address — it is"
    echo "    on the deployment's page in the dashboard, as fedserver-<uuid>.<domain>."
fi
