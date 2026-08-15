#!/usr/bin/env python3
"""A stand-in for the deployed federated server, for rehearsing without the cluster.

    python3 demo/fl/local_server.py --rounds 10

On the cluster this job is the ``ai4os-federated-server`` tool, deployed from
the dashboard, running upstream's ``fedserver/server.py`` in a container. That
is the one the demo uses. This file exists so the *clients* can be developed and
proven on caios_server in a couple of minutes, instead of by redeploying a Nomad
job every time a line changes.

It is deliberately a mirror, not an improvement. The strategy is configured the
same way upstream configures it from its environment variables:

  * FedAvg, matching the ``strategy`` default in
    ``configs/papi/tools/ai4os-federated-server/user.yaml``
  * ``min_fit_clients`` and ``min_available_clients`` both 3, so nothing
    aggregates until all three hospitals have reported
  * accuracy aggregated as a weighted mean over each client's slice count,
    which is what upstream's ``wavg_metric`` does

One upstream quirk is reproduced by not mattering: server.py passes
``min_available_clients=FEDERATED_MIN_FIT_CLIENTS`` and
``min_fit_clients=FEDERATED_MIN_AVAILABLE_CLIENTS`` — the two are swapped. With
both set to 3 the swap is invisible. It would not be if they ever differed, so
keep them equal.

Plaintext gRPC on 5000, no TLS: on the cluster Traefik terminates TLS in front
of the server, and the server itself never sees a certificate either.
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results" / "federated_server.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--clients", type=int, default=3)
    parser.add_argument("--address", default="0.0.0.0:5000")
    parser.add_argument("--out", type=Path, default=RESULTS)
    args = parser.parse_args()

    import flwr as fl

    curve = []

    def weighted_accuracy(metrics):
        """Weighted mean of client accuracies — upstream's wavg_metric."""
        total = sum(count for count, _ in metrics)
        value = sum(count * m["accuracy"] / total for count, m in metrics)
        curve.append(round(float(value), 4))
        print(f"  round {len(curve):2d}  federated accuracy {value:.3f}", flush=True)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps({"rounds": args.rounds, "curve": curve}, indent=2) + "\n"
        )
        return {"accuracy": value}

    strategy = fl.server.strategy.FedAvg(
        min_fit_clients=args.clients,
        min_available_clients=args.clients,
        min_evaluate_clients=args.clients,
        evaluate_metrics_aggregation_fn=weighted_accuracy,
    )

    print(f"waiting for {args.clients} hospitals on {args.address} ...", flush=True)
    fl.server.start_server(
        server_address=args.address,
        config=fl.server.ServerConfig(num_rounds=args.rounds),
        strategy=strategy,
    )
    print(f"\nfederated curve written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
