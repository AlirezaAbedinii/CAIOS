#!/usr/bin/env bash
# Make the narrated recording of the CAIOS walkthrough.
#
#   bash demo/recording/run.sh build             # the two images, once
#   bash demo/recording/run.sh tts [line ...]    # speak narration.yaml
#   python3 demo/recording/terminals.py up       # the terminals beats 4 and 6 use
#   bash demo/recording/run.sh setup             # sign the browser profiles in
#   bash demo/recording/run.sh record [clip ...] # all clips, or just these
#   bash demo/recording/run.sh assemble          # cut, voice, captions -> out/final
#   bash demo/recording/run.sh readme-media      # the README's preview GIF and 720p video
#   python3 demo/recording/terminals.py down
#   bash demo/recording/accounts.sh delete-all   # the account beat 2 created
#
# Everything runs on caios_server, in containers, as you; nothing is installed
# on the host. README.md says what each step does and what can go wrong.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
mkdir -p "$HERE/out/home"
DOCKER="docker"
docker info >/dev/null 2>&1 || DOCKER="sudo -n docker"

recorder() {
    $DOCKER run --rm --network host --shm-size=2g --user "$(id -u):$(id -g)" \
        -e HOME="$HERE/out/home" -e DISPLAY=:99 \
        -v "$HERE:$HERE" -w "$HERE" -v "$ROOT:/repo:ro" \
        -v "$ROOT/configs/env/caios.env:/caios.env:ro" \
        -v "$ROOT/compose/certs/caios-ca.pem:/ca.pem:ro" \
        caios/recorder bash -c '
            set -e
            Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp >/dev/null 2>&1 &
            for _ in $(seq 50); do [ -e /tmp/.X11-unix/X99 ] && break; sleep 0.1; done
            db="sql:$HOME/.pki/nssdb"; mkdir -p "$HOME/.pki/nssdb"
            certutil -d "$db" -L >/dev/null 2>&1 || certutil -d "$db" -N --empty-password
            certutil -d "$db" -A -t "C,," -n caios-ca -i /ca.pem
            exec "$@"' _ "$@"
}

case "${1:-}" in
    build)
        $DOCKER build -t caios/recorder:latest "$HERE/docker/recorder"
        $DOCKER build -t caios/tts:latest "$HERE/docker/tts"
        ;;
    tts)
        $DOCKER run --rm --network host --user "$(id -u):$(id -g)" \
            -e HF_HOME="$HERE/out/hf-cache" -e HOME="$HERE/out/home" \
            -v "$HERE:$HERE" -w "$HERE" caios/tts python3 tts.py "${@:2}"
        ;;
    setup)    recorder python3 record.py setup ;;
    record)   recorder python3 record.py record "${@:2}" ;;
    assemble) recorder python3 assemble.py "${@:2}" ;;
    readme-media)
        recorder python3 readme_media.py "${@:2}"
        mkdir -p "$ROOT/docs/assets"
        for f in demo-preview.gif caios-logo-light.png caios-logo-dark.png; do
            [[ -f "$HERE/out/final/$f" ]] && cp "$HERE/out/final/$f" "$ROOT/docs/assets/"
        done
        true
        ;;
    shell)    recorder bash ;;
    *) sed -n '2,14p' "$0"; exit 2 ;;
esac
