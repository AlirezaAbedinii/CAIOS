#!/usr/bin/env python3
"""One hospital's federated learning client.

This is what runs inside each site's workspace on the platform. It reads only
that site's own slices, trains locally, and sends weights — never data — to the
federated server.

    # on the cluster, from a site's JupyterLab terminal
    python3 client.py --site site_a \
        --server fedserver-<uuid>.pacs-deployments.<EDGE_IP>.sslip.io:443 \
        --ca caios-ca.pem

    # local rehearsal against demo/fl/local_server.py
    python3 client.py --site site_a --server 127.0.0.1:5000 --insecure

WHY --ca IS NOT OPTIONAL ON THE CLUSTER

The federated server listens on gRPC port 5000, and PAPI publishes it through
Traefik as ``fedserver-<uuid>...`` on port 443 with TLS in front (the route is
tagged ``scheme=h2c`` so gRPC survives the hop). Our wildcard certificate is
signed by the CAIOS local CA, which nothing trusts by default, so the client has
to be handed that CA explicitly. Upstream's own example passes ``certifi`` here,
which works only for a publicly-trusted certificate — for us it fails with a
handshake error that says nothing about certificates being the cause.

WHAT LEAVES THE BUILDING

Model weights, the number of slices trained on, and an accuracy number. No
images, no patient identifiers. That is the claim the demo is making, and it is
worth being able to point at this file while making it.

WHY EVALUATION USES THE SHARED TEST SET

Each round the client scores the *aggregated global model* on
``test.npz`` — held out before the sites were formed and identical for all
three. So this client's accuracy curve is the federated curve, directly
comparable with the site-alone and centralised baselines. Evaluating on local
data instead would give each site a flattering number on its own case mix and
nothing that could be plotted against anything.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from model import build_model, load_split, quiet_tensorflow  # noqa: E402

SITE_LABELS = {
    "site_a": "Hospital A",
    "site_b": "Hospital B",
    "site_c": "Hospital C",
}


def tidy_flower_logging(quiet: bool):
    """Drop Flower's deprecation banner, and optionally its per-message chatter.

    Flower 1.16 greets every client with ten yellow lines telling it to switch
    to ``flower-supernode``. That advice is wrong here: the deployed server runs
    upstream's ``fl.server.start_server()``, which is the matching legacy API, so
    a SuperNode would have nothing to talk to. Keeping the banner would mean the
    demo opens with a prominent warning that we cannot act on and that invites
    exactly one question.

    ``quiet`` additionally hides the "Received: train message <uuid>" lines, for
    when the terminal is on a projector. It is off by default because those
    lines are the first thing worth reading when a client will not connect.
    """

    class NoDeprecation(logging.Filter):
        def filter(self, record):
            return "DEPRECATED FEATURE" not in record.getMessage()

    flower = logging.getLogger("flwr")
    flower.addFilter(NoDeprecation())
    if quiet:
        flower.setLevel(logging.WARNING)


def find_data_dir(explicit):
    """Look where the bundle puts the data, then where the repository puts it."""
    if explicit:
        return Path(explicit)
    for candidate in (HERE / "data", HERE.parents[1] / "demo" / "data" / "sites"):
        if (candidate / "test.npz").exists():
            return candidate
    raise SystemExit(
        "Could not find the data. Pass --data-dir, or run demo/fl/partition.py."
    )


def build_client(args, data_dir):
    import flwr as fl

    label = SITE_LABELS.get(args.site, args.site)
    x_train, y_train = load_split(data_dir / f"{args.site}.npz")
    x_test, y_test = load_split(data_dir / "test.npz")

    print(f"[{label}] {len(x_train)} local slices, never leaving this workspace", flush=True)
    print(f"[{label}] scoring the global model on {len(x_test)} shared test slices", flush=True)

    model = build_model()
    history = []

    class HospitalClient(fl.client.NumPyClient):
        def get_parameters(self, config):
            return model.get_weights()

        def fit(self, parameters, config):
            model.set_weights(parameters)
            model.fit(
                x_train,
                y_train,
                epochs=args.local_epochs,
                batch_size=args.batch_size,
                verbose=0,
                shuffle=True,
            )
            print(
                f"[{label}] trained {args.local_epochs} local epoch(s), sending weights",
                flush=True,
            )
            return model.get_weights(), len(x_train), {}

        def evaluate(self, parameters, config):
            model.set_weights(parameters)
            loss, accuracy = model.evaluate(x_test, y_test, verbose=0)
            history.append(round(float(accuracy), 4))
            print(
                f"[{label}] round {len(history):2d}  "
                f"global model on shared test set: {accuracy:.3f}",
                flush=True,
            )
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(
                json.dumps(
                    {
                        "site": args.site,
                        "label": label,
                        "train_slices": int(len(x_train)),
                        "test_slices": int(len(x_test)),
                        "local_epochs": args.local_epochs,
                        "curve": history,
                    },
                    indent=2,
                )
                + "\n"
            )
            # The key has to be exactly the metric name the server was configured
            # with; it aggregates on metric[FEDERATED_METRIC] and KeyErrors on
            # anything else.
            return float(loss), len(x_test), {"accuracy": float(accuracy)}

    return HospitalClient().to_client()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", required=True, choices=sorted(SITE_LABELS))
    parser.add_argument(
        "--server",
        required=True,
        help="host:port of the federated server (443 through Traefik)",
    )
    parser.add_argument("--ca", type=Path, help="PEM of the CA that signed the server")
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="plaintext gRPC — local rehearsal only, never through Traefik",
    )
    parser.add_argument("--data-dir", help="directory holding <site>.npz and test.npz")
    parser.add_argument("--local-epochs", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="hide Flower's per-message logging — for demo day, not for debugging",
    )
    args = parser.parse_args()

    if not args.insecure and not args.ca:
        print("Refusing to connect: pass --ca <pem>, or --insecure for a local test.")
        print("On the cluster the CA is caios-ca.pem, shipped in this bundle.")
        return 1
    if args.out is None:
        args.out = HERE / "results" / f"federated_{args.site}.json"

    quiet_tensorflow()
    import flwr as fl

    tidy_flower_logging(args.quiet)
    data_dir = find_data_dir(args.data_dir)
    client = build_client(args, data_dir)

    print(f"[{args.site}] connecting to {args.server} ...", flush=True)
    fl.client.start_client(
        server_address=args.server,
        client=client,
        insecure=bool(args.insecure),
        root_certificates=None if args.insecure else args.ca.read_bytes(),
    )
    print(f"[{args.site}] federation finished; curve written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
