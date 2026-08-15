#!/usr/bin/env python3
"""Draw the chart the demo ends on: site-alone vs centralised vs federated.

    python3 demo/fl/plot_results.py

Reads ``results/baselines.json`` and ``results/cluster/federation.json`` and
writes ``results/federated-vs-baselines.png`` and ``.svg``.

WHAT THE CHART HAS TO SAY IN ONE LOOK

Three hospitals, none of which can see each other's patients. Each can train
alone and reach somewhere in the high 0.70s. Pooling all the data reaches 0.865,
and is the thing that is usually not permitted. Federated learning reaches 0.853
without any data moving.

So the three site lines are drawn thin and grey — they are context, not the
point — the centralised line is dashed, because it is a bound rather than an
option, and the federated line is solid and coloured. The gap between the
federated line and the best grey line is the argument.

The x-axis is rounds for every line. A site-alone model at round 5 has made
exactly as many passes over its own data as an FL client has by round 5, so the
comparison is between methods, not between training budgets. See
``baselines.py``.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"

# Clinical teal, matching the dashboard theme rather than matplotlib's default
# blue — this image ends up in a slide next to a screenshot of the platform.
TEAL = "#0f766e"
SLATE = "#475569"
GREY = "#94a3b8"


def main() -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    baselines_file = RESULTS / "baselines.json"
    federation_file = RESULTS / "cluster" / "federation.json"
    for path in (baselines_file, federation_file):
        if not path.exists():
            print(f"Missing {path}.")
            return 1

    baselines = json.loads(baselines_file.read_text())
    federation = json.loads(federation_file.read_text())

    curves = baselines["curves"]
    fed = federation["curve"]
    rounds = range(1, len(fed) + 1)

    figure, axes = plt.subplots(figsize=(8.5, 5.2), dpi=160)

    for index, site in enumerate(["site_a", "site_b", "site_c"]):
        label = "one hospital, training alone" if index == 0 else None
        axes.plot(
            range(1, len(curves[site]) + 1),
            curves[site],
            color=GREY,
            linewidth=1.3,
            label=label,
            zorder=2,
        )

    axes.plot(
        range(1, len(curves["central"]) + 1),
        curves["central"],
        color=SLATE,
        linewidth=1.8,
        linestyle="--",
        label="all data pooled centrally (not permitted in practice)",
        zorder=3,
    )

    axes.plot(
        rounds,
        fed,
        color=TEAL,
        linewidth=2.8,
        marker="o",
        markersize=4.5,
        label="federated across three hospitals (data never moves)",
        zorder=4,
    )

    best_site = max(max(curves[s]) for s in ["site_a", "site_b", "site_c"])
    axes.axhline(best_site, color=GREY, linewidth=0.8, linestyle=":", zorder=1)
    axes.annotate(
        f"best single hospital: {best_site:.3f}",
        xy=(len(fed), best_site),
        xytext=(-6, -14),
        textcoords="offset points",
        ha="right",
        fontsize=8.5,
        color=SLATE,
    )
    axes.annotate(
        f"federated: {max(fed):.3f}",
        xy=(fed.index(max(fed)) + 1, max(fed)),
        xytext=(6, 8),
        textcoords="offset points",
        fontsize=9.5,
        color=TEAL,
        fontweight="bold",
    )

    sites = federation["sites"]
    total = sum(s["train_slices"] for s in sites.values())
    axes.set_title(
        "Brain tumour classification across three hospital sites",
        fontsize=13,
        fontweight="bold",
        pad=14,
        loc="left",
    )
    axes.text(
        0,
        1.015,
        f"{total} MRI slices, split unevenly across three nodes · "
        f"{federation['strategy']} · {federation['rounds']} rounds · "
        f"scored on {baselines['test_slices']} held-out slices",
        transform=axes.transAxes,
        fontsize=9,
        color=SLATE,
    )

    axes.set_xlabel("federated round (or equivalent local training budget)")
    axes.set_ylabel("accuracy on the shared held-out test set")
    axes.set_xticks(list(rounds))
    axes.set_ylim(0.4, 0.95)
    axes.grid(True, alpha=0.25, linewidth=0.6)
    axes.spines[["top", "right"]].set_visible(False)
    axes.legend(loc="lower right", frameon=False, fontsize=9)

    figure.tight_layout()
    for suffix in ("png", "svg"):
        out = RESULTS / f"federated-vs-baselines.{suffix}"
        figure.savefig(out, bbox_inches="tight")
        print(f"  wrote {out}")

    print()
    print(f"  best single hospital  {best_site:.3f}")
    print(f"  federated             {max(fed):.3f}")
    print(f"  centralised           {max(curves['central']):.3f}")
    closed = (max(fed) - best_site) / (max(curves["central"]) - best_site)
    print(f"\n  federated closes {closed:.0%} of the gap, with no data leaving any site.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
