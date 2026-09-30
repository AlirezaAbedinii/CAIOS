#!/usr/bin/env bash
# Delete the accounts the recording created, and only those.
#
#   bash demo/recording/accounts.sh list
#   bash demo/recording/accounts.sh delete <username>   # must be in out/accounts.txt
#   bash demo/recording/accounts.sh delete-all
#
# record.py appends every username it registers to out/accounts.txt. Nothing
# else is ever deleted: a name not in that file is refused. Deletes the way
# scripts/check-registration.sh does, through kcadm in the Keycloak container.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
set -a; source "$ROOT/configs/env/caios.env"; set +a
REALM="${KEYCLOAK_REALM:-caios}"
LEDGER="$HERE/out/accounts.txt"
touch "$LEDGER"

kc() { sudo -n docker exec -i caios_keycloak /opt/keycloak/bin/kcadm.sh "$@"; }
auth() {
    kc config credentials --server http://localhost:8080 --realm master \
        --user "$KEYCLOAK_ADMIN" --password "$KEYCLOAK_ADMIN_PASSWORD" >/dev/null
}
delete_one() {
    local name="$1"
    grep -qx "$name" "$LEDGER" || { echo "  refused: $name was not created by the recording"; return 1; }
    local id
    id="$(kc get users -r "$REALM" -q "username=$name" -q exact=true --fields id --format csv --noquotes | tail -n1)"
    if [[ -n "$id" ]]; then
        kc delete "users/$id" -r "$REALM"
        echo "  deleted $name"
    else
        echo "  $name: no such account"
    fi
    sed -i "/^${name}\$/d" "$LEDGER"
}

case "${1:-list}" in
    list) cat "$LEDGER" ;;
    delete) auth; delete_one "${2:?username}" ;;
    delete-all) auth; for n in $(cat "$LEDGER"); do delete_one "$n" || true; done ;;
    *) echo "usage: accounts.sh list | delete <username> | delete-all"; exit 2 ;;
esac
