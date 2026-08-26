#!/usr/bin/env bash
# Install OSCAR serverless inference on caios_oscar (192.168.104.69).
#
#   bash scripts/install-oscar.sh            # print what it would do
#   bash scripts/install-oscar.sh --apply    # actually install
#
# Prints by default, like scripts/openstack-security-groups.sh. This installs a
# second orchestrator on a node; read it before running it.
#
# Idempotent: helm upgrade --install, and every kubectl apply is declarative.
#
# WHY K3S AND NOT NOMAD
#
# OSCAR is a Kubernetes application — the OSCAR manager, MinIO and the Jobs it
# creates all speak the Kubernetes API. It cannot run on Nomad. So this node
# runs K3s and is deliberately absent from ansible/inventory/hosts.ini: K3s and
# Nomad both manage containerd and cgroups, and a node running both half-works
# in ways that are miserable to diagnose (R-32).
#
# THE THREE THINGS THAT ARE NOT OBVIOUS
#
# 1. --data-dir /mnt/k3s.  The root disk is 20 GB and container images are not
#    small. K3s defaults everything to /var/lib/rancher/k3s. Measured after
#    install: images land in /mnt/k3s/agent/containerd, and about 250 MB of
#    self-extracted static binaries stay on the root disk regardless — fixed
#    size, does not grow. Verify with du; do not trust the flag (R-37, D-53).
#
# 2. --disable traefik.  K3s ships Traefik and binds 80/443 with it. The CAIOS
#    platform already has a Traefik on caios_edge, and this node needs its 443
#    for the OSCAR and MinIO ingresses.
#
# 3. SSL_CERT_DIR on the OSCAR pod.  OSCAR talks to Keycloak and to MinIO over
#    HTTPS, both signed by the CAIOS local CA, which its container has no
#    reason to trust. Without this it exits with code 2 immediately after
#    printing "OIDC authentication enabled: true" and NOTHING ELSE — no stack
#    trace, no TLS error, nothing naming a certificate. This is R-30, the fifth
#    time a private CA has broken a component in this project.
#
#    Go reads every file in every directory of SSL_CERT_DIR, so listing the
#    system directory first keeps public CAs working while adding ours. TLS
#    verification stays ON, per D-43 — distribute the CA, do not skip the check.
set -uo pipefail

NODE="${CAIOS_OSCAR_NODE:-192.168.104.69}"
OIDC_ISSUER="${CAIOS_OIDC_ISSUER:-https://auth.134.87.8.230.sslip.io/realms/caios}"
OSCAR_HOST="oscar.${NODE}.sslip.io"
MINIO_HOST="minio.${NODE}.sslip.io"

APPLY=false
[[ "${1:-}" == "--apply" ]] && APPLY=true

say() { printf '%s\n' "$*"; }
run() { if $APPLY; then eval "$@"; else say "    $*"; fi; }

say "=== OSCAR install plan for ${NODE} ==="
say "  OSCAR   https://${OSCAR_HOST}"
say "  MinIO   https://${MINIO_HOST}"
say "  issuer  ${OIDC_ISSUER}"
say
$APPLY || say "  (printing only — pass --apply to run)"
say

say "1. k3s, data-dir on /mnt, no Traefik"
run "curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC='--data-dir /mnt/k3s --disable traefik --write-kubeconfig-mode 644' sh -"

say "2. verify the data really landed on /mnt — this is the check, not the flag"
run "sudo ls -d /mnt/k3s/agent/containerd && df -h / /mnt"

say "3. namespaces, the CAIOS-signed TLS secret, and the CA secret"
say "   (cert issued from the CAIOS CA with SANs for both hostnames above)"
run "sudo k3s kubectl create namespace ingress-nginx --dry-run=client -o yaml | sudo k3s kubectl apply -f -"
run "sudo k3s kubectl create namespace minio --dry-run=client -o yaml | sudo k3s kubectl apply -f -"
run "sudo k3s kubectl create namespace oscar --dry-run=client -o yaml | sudo k3s kubectl apply -f -"
run "sudo k3s kubectl -n minio create secret tls caios-node-tls --cert=/tmp/oscar-node-fullchain.pem --key=/tmp/oscar-node.key --dry-run=client -o yaml | sudo k3s kubectl apply -f -"
run "sudo k3s kubectl -n oscar create secret tls caios-node-tls --cert=/tmp/oscar-node-fullchain.pem --key=/tmp/oscar-node.key --dry-run=client -o yaml | sudo k3s kubectl apply -f -"
run "sudo k3s kubectl -n oscar create secret generic caios-ca --from-file=ca.crt=/tmp/caios-ca.pem --dry-run=client -o yaml | sudo k3s kubectl apply -f -"

say "4. ingress-nginx"
run "helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx && helm repo update"
run "helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx --namespace ingress-nginx --set controller.service.type=LoadBalancer --wait --timeout 6m"

say "5. MinIO (manifest in configs/oscar/minio.yaml), plus its ingress"
run "sudo k3s kubectl apply -f configs/oscar/minio.yaml"

say "6. RBAC: OSCAR's service account must be able to list nodes"
say "   Without it the manager logs three 'nodes is forbidden' errors on every"
say "   start. Not fatal on its own, but it is noise on top of a real fault."
run "sudo k3s kubectl apply -f configs/oscar/rbac.yaml"

say "7. OSCAR — async only, no Knative (D-51)"
run "helm repo add grycap https://grycap.github.io/helm-charts/ && helm repo update"
run "helm upgrade --install oscar grycap/oscar --namespace oscar \\
      --set authUser=oscar --set authPass=\"\$OSCAR_PASS\" \\
      --set serverlessBackend='' \\
      --set oidc.enable=true --set oidc.issuer='${OIDC_ISSUER}' \\
      --set minIO.endpoint='https://${MINIO_HOST}' --set minIO.TLSVerify=true \\
      --set minIO.accessKey=\"\$MINIO_USER\" --set minIO.secretKey=\"\$MINIO_PASS\" \\
      --set ingress.create=false --wait --timeout 8m"

say "8. R-30: mount the CAIOS CA so OSCAR can verify Keycloak and MinIO"
say "   Without this the pod exits 2 with no diagnostic whatsoever."
run "sudo k3s kubectl -n oscar patch deploy oscar --type=strategic -p @configs/oscar/ca-patch.json"

say "9. the OSCAR ingress"
run "sudo k3s kubectl apply -f configs/oscar/oscar-ingress.yaml"

say
say "=== verify ==="
say "  curl --cacert ~/caios-ca.pem https://${OSCAR_HOST}/health"
say "  curl --cacert ~/caios-ca.pem -u oscar:\$OSCAR_PASS https://${OSCAR_HOST}/system/info"
say
say "  A CAIOS Keycloak token is still REFUSED until OIDC_GROUPS is set and"
say "  Keycloak emits a matching claim — see docs/oscar-plan.md, Stage O3."
