#!/usr/bin/env python3
"""Train the two non-federated baselines the demo is measured against.

    python3 demo/fl/baselines.py                        # 10 rounds, 2 epochs each
    python3 demo/fl/baselines.py --rounds 5

Writes ``demo/fl/results/baselines.json``: an accuracy-per-round curve for each
of the three sites training alone, and one for a centralised model that has been
given every site's data at once.

WHAT THE TWO BASELINES MEAN

*Site-alone* is what each hospital can do today: train on its own patients, keep
them in the building, and accept whatever the model learns from an unbalanced
local case mix. Three curves, one per site.

*Centralised* is what they could do if they were allowed to pool the data in one
place. It is the upper bound, and it is the thing that is usually illegal. One
curve.

Federated should land between them and near the top: most of the benefit of
pooling, none of the pooling. Producing that third curve is Stage 4E; this file
exists so the first two are ready and verified before any of it is deployed.

WHY THE X-AXIS IS "ROUNDS" AND NOT "EPOCHS"

A federated round is a fixed number of local epochs on each client followed by
an aggregation. For the three lines to sit on one axis, the baselines are
trained in the same units: ``--local-epochs`` passes, then evaluate, repeat. A
site-alone run at round 5 has therefore seen exactly as many passes over its own
data as an FL client has by round 5. Anything else compares training budgets
rather than methods.

Every curve is scored on ``demo/data/sites/test.npz`` — held out before the
sites were formed, patient-disjoint from all of them.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model import build_model, load_split, quiet_tensorflow  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SITES_DIR = ROOT / "demo" / "data" / "sites"
RESULTS = ROOT / "demo" / "fl" / "results" / "baselines.json"
SITES = ["site_a", "site_b", "site_c"]


def train_curve(name, x, y, x_test, y_test, rounds, local_epochs, batch_size):
    """Train one model, recording test accuracy after every block of epochs."""
    model = build_model()
    curve = []
    started = time.time()
    for step in range(1, rounds + 1):
        model.fit(
            x,
            y,
            epochs=local_epochs,
            batch_size=batch_size,
            verbose=0,
            shuffle=True,
        )
        loss, accuracy = model.evaluate(x_test, y_test, verbose=0)
        curve.append(round(float(accuracy), 4))
        print(f"  {name:12s} round {step:2d}/{rounds}  test acc {accuracy:.3f}")
    print(f"  {name:12s} done in {time.time() - started:.0f}s\n")
    return curve


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--local-epochs", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--sites-dir", type=Path, default=SITES_DIR)
    parser.add_argument("--out", type=Path, default=RESULTS)
    args = parser.parse_args()

    quiet_tensorflow()

    test_file = args.sites_dir / "test.npz"
    if not test_file.exists():
        print(f"Missing {test_file} — run demo/fl/partition.py first.")
        return 1
    x_test, y_test = load_split(test_file)
    print(f"shared test set: {len(x_test)} slices\n")

    curves, sizes = {}, {}

    print("=== site-alone: each hospital trains on its own patients ===")
    site_data = {}
    for site in SITES:
        x, y = load_split(args.sites_dir / f"{site}.npz")
        site_data[site] = (x, y)
        sizes[site] = len(x)
        curves[site] = train_curve(
            site, x, y, x_test, y_test, args.rounds, args.local_epochs, args.batch_size
        )

    print("=== centralised: one model, everybody's data pooled ===")
    x_all = np.concatenate([site_data[s][0] for s in SITES])
    y_all = np.concatenate([site_data[s][1] for s in SITES])
    sizes["central"] = len(x_all)

    # A centralised round sees three sites' worth of data where a site-alone
    # round sees one, so it does a third of the epochs to keep the number of
    # gradient steps per round comparable. Without this the "upper bound" is
    # partly just a bigger training budget.
    central_epochs = max(1, round(args.local_epochs * len(site_data[SITES[0]][0]) / len(x_all)))
    print(f"  ({central_epochs} epoch(s) per round over {len(x_all)} slices)")
    curves["central"] = train_curve(
        "central", x_all, y_all, x_test, y_test, args.rounds, central_epochs, args.batch_size
    )

    payload = {
        "rounds": args.rounds,
        "local_epochs": args.local_epochs,
        "central_epochs": central_epochs,
        "batch_size": args.batch_size,
        "test_slices": int(len(x_test)),
        "train_slices": sizes,
        "curves": curves,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")

    print("=== final accuracy on the shared test set ===")
    for name, curve in curves.items():
        print(f"  {name:12s} {curve[-1]:.3f}   (best {max(curve):.3f})")
    print(f"\n  wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
