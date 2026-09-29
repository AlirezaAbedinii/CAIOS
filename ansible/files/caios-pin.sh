#!/usr/bin/env bash
# Keep the demo's images on a node, whatever docuum decides. Run on the node by
# playbook-prepull-images.yml through Ansible's `script` module.
#
#   caios-pin.sh pin <reference>          pin one image, if it is here
#   caios-pin.sh release <reference>...   remove every pin NOT for these
#   caios-pin.sh count <reference>...     how many are here and pinned
#
# A pin is a container created from the image and never started, named
# caios-pin-<the reference, sanitised> and labelled caios.pin=<the reference>.
# docuum never deletes an image a container references: its vacuum() filters
# them out before choosing what to evict (D-86). A pin that references an
# older image than its tag now names is moved, so the old image is released
# to docuum rather than kept forever.
#
# Kept out of the playbook so Docker's Go templates ({{.Id}}) never pass
# through Jinja, and so tests/test_prepull_split.py can run it against a fake
# docker.
set -uo pipefail

pin_name() {
    printf 'caios-pin-%s' "$(printf '%s' "$1" | tr -c 'A-Za-z0-9_.-' '-' | cut -c1-120)"
}

image_id() { docker image inspect --format '{{.Id}}' "$1" 2>/dev/null; }
pinned_to() { docker container inspect --format '{{.Image}}' "$(pin_name "$1")" 2>/dev/null; }

case "${1:-}" in
    pin)
        ref="${2:?usage: caios-pin.sh pin <reference>}"
        name="$(pin_name "$ref")"
        want="$(image_id "$ref")" || { echo "absent $ref"; exit 0; }
        have="$(pinned_to "$ref")" || have=""
        if [[ "$have" == "$want" ]]; then
            echo "held $ref"
            exit 0
        fi
        if [[ -n "$have" ]]; then
            docker rm "$name" >/dev/null || exit 1
        fi
        docker create --name "$name" --label "caios.pin=$ref" \
            --entrypoint /bin/true "$ref" >/dev/null || exit 1
        echo "pinned $ref"
        ;;
    release)
        shift
        keep=" $* "
        pins="$(docker ps -a --filter label=caios.pin \
            --format '{{.Names}} {{.Label "caios.pin"}}')" || exit 1
        while read -r name ref; do
            [[ -n "$name" ]] || continue
            case "$keep" in
                *" $ref "*) ;;
                *) docker rm "$name" >/dev/null && echo "released $ref" ;;
            esac
        done <<< "$pins"
        ;;
    count)
        shift
        n=0
        for ref in "$@"; do
            want="$(image_id "$ref")" || continue
            [[ "$(pinned_to "$ref")" == "$want" ]] && n=$((n + 1))
        done
        echo "$n"
        ;;
    *)
        echo "usage: caios-pin.sh pin <reference> | release <reference>... | count <reference>..." >&2
        exit 2
        ;;
esac
