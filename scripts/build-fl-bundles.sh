#!/usr/bin/env bash
# Package one self-contained bundle per hospital site, and publish them.
#
#   bash scripts/build-fl-bundles.sh
#
# Writes demo/fl/dist/:
#
#   caios-fl-site_a.tar.gz    that site's data, the shared test set, the
#   caios-fl-site_b.tar.gz    client, the model and the CAIOS CA
#   caios-fl-site_c.tar.gz
#   bootstrap.sh              the one line pasted into a workspace terminal
#   index.html                what a browser sees at /fl/
#
# Caddy serves the directory at https://<dashboard>/fl/ (see
# compose/caddy/Caddyfile), so a workspace fetches its bundle over the private
# subnet with no credentials and no storage backend.
#
# WHY A BUNDLE AND NOT SHARED STORAGE
#
# The platform's answer is Nextcloud over WebDAV, mounted into the workspace by
# rclone. We are not running it for MVP (D-15), so datasets are copied into the
# dev environment instead. A per-site tarball is that copy, and it has one
# property worth keeping regardless: Site A's bundle physically does not contain
# Site B's data. When the demo claims each hospital holds only its own patients,
# that is enforced here rather than promised.
#
# WHY IT IS PUBLISHED ON THE DASHBOARD HOST
#
# A dedicated data.<...> hostname would need a new SAN in the control-plane
# certificate, which currently covers exactly four names, and regenerating it
# risks the working login for a file download. The dashboard host already serves
# the CA from a path for the same reason.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="configs/env/caios.env"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE"; exit 1; }
set -a; source "$ENV_FILE"; set +a

: "${CAIOS_DASHBOARD_HOST:?CAIOS_DASHBOARD_HOST is empty in $ENV_FILE}"

SITES_DIR="demo/data/sites"
DIST="demo/fl/dist"
CA_SRC="${CAIOS_CA_PEM:-compose/certs/caios-ca.pem}"
BASE_URL="https://${CAIOS_DASHBOARD_HOST}/fl"
SITES=(site_a site_b site_c)

[[ -f "$SITES_DIR/test.npz" ]] || { echo "No data — run demo/fl/partition.py first."; exit 1; }
[[ -f "$CA_SRC" ]] || { echo "No CA at $CA_SRC — run scripts/make-traefik-certs.sh."; exit 1; }

rm -rf "$DIST"
mkdir -p "$DIST"
staging="$(mktemp -d)"
trap 'rm -rf "$staging"' EXIT

for site in "${SITES[@]}"; do
    [[ -f "$SITES_DIR/$site.npz" ]] || { echo "Missing $SITES_DIR/$site.npz"; exit 1; }

    work="$staging/caios-fl-$site"
    mkdir -p "$work/data"

    cp demo/fl/client.py demo/fl/model.py "$work/"
    cp "$CA_SRC" "$work/caios-ca.pem"
    # Only this site's shard, plus the shared test set. Deliberately not a loop
    # over all three: see the note at the top of this file.
    cp "$SITES_DIR/$site.npz" "$work/data/"
    cp "$SITES_DIR/test.npz" "$work/data/"

    cat > "$work/README.txt" <<EOF
CAIOS federated learning — $site

  ./run.sh                     join the federation (written by bootstrap.sh)

or by hand:

  python3 client.py --site $site --ca caios-ca.pem \\
      --server fedserver-<uuid>.${CAIOS_DEPLOYMENTS_DOMAIN:-<domain>}:443

Contents:
  client.py        this hospital's federated client
  model.py         the model, identical at every site and in the baselines
  caios-ca.pem     the CA that signed the server's certificate
  data/$site.npz   this hospital's own slices — no other site's data is here
  data/test.npz    the shared held-out test set, for scoring the global model
EOF

    tar czf "$DIST/caios-fl-$site.tar.gz" -C "$staging" "caios-fl-$site"
    echo "  built caios-fl-$site.tar.gz  ($(du -h "$DIST/caios-fl-$site.tar.gz" | cut -f1))"
done

sed "s|@@FL_BASE_URL@@|$BASE_URL|g" demo/fl/bootstrap.sh > "$DIST/bootstrap.sh"
chmod +x "$DIST/bootstrap.sh"
echo "  built bootstrap.sh          (base $BASE_URL)"

cat > "$DIST/index.html" <<EOF
<!doctype html>
<meta charset="utf-8">
<title>CAIOS federated learning bundles</title>
<style>body{font:15px/1.6 system-ui,sans-serif;max-width:44rem;margin:3rem auto;padding:0 1rem}
code{background:#f4f4f5;padding:.15em .4em;border-radius:3px}pre{background:#f4f4f5;padding:1rem;overflow-x:auto}</style>
<h1>CAIOS federated learning</h1>
<p>Run this in a site workspace's terminal, with that site's name:</p>
<pre>curl -k -sSL $BASE_URL/bootstrap.sh | bash -s site_a</pre>
<p>Bundles: <a href="caios-fl-site_a.tar.gz">site_a</a> ·
<a href="caios-fl-site_b.tar.gz">site_b</a> ·
<a href="caios-fl-site_c.tar.gz">site_c</a></p>
<p>Each contains only that site's own slices, plus the shared test set.</p>
EOF

echo
echo "  published at $BASE_URL/  (reload Caddy if this is the first build:"
echo "  docker compose -f compose/docker-compose.yml --env-file $ENV_FILE up -d caddy)"
