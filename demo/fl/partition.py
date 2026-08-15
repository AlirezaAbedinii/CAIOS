#!/usr/bin/env python3
"""Split the brain-tumour set across three hospital sites, non-IID.

    python3 demo/fl/partition.py            # write demo/data/sites/
    python3 demo/fl/partition.py --seed 7   # a different draw

Reads ``demo/data/brain_mri.npz`` (see ``prepare_data.py``) and writes

    demo/data/sites/site_a.npz      Site A's training data, and only that
    demo/data/sites/site_b.npz
    demo/data/sites/site_c.npz
    demo/data/sites/test.npz        held out, shared, never trained on
    demo/data/sites/manifest.json   what ended up where

WHY THE SPLIT IS DELIBERATELY UNEVEN

If every site held the same mix of tumours, each could train a decent model
alone and federating would gain almost nothing — the demo would prove the
plumbing works and nothing else. Real hospitals do not look like that. A centre
with a neuro-oncology referral stream sees far more gliomas than a general
hospital does.

So Site A gets mostly meningioma, Site B mostly glioma, and Site C a spread of
all three. Each site alone then learns a model that is good on what it sees and
poor on what it does not, and the federated model beats all three on data none
of them holds. That gap is the demo.

WHY PATIENTS ARE KEPT WHOLE

One patient contributes several near-identical slices. Splitting a patient
across sites, or between training and test, quietly inflates every number here.
Assignment is therefore by patient, never by slice — and because a patient has
one tumour type, this costs nothing in control over the class mix.

WHY ONE SHARED TEST SET

Site-alone, centralised and federated have to be scored on identical data or the
three lines in the final chart mean nothing. ``test.npz`` is held out before any
site is formed, is patient-disjoint from all of them, and keeps the natural
class balance. Every model in this demo is measured on it and on nothing else.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
IN_FILE = ROOT / "demo" / "data" / "brain_mri.npz"
OUT_DIR = ROOT / "demo" / "data" / "sites"

SITES = ["site_a", "site_b", "site_c"]
SITE_LABELS = {
    "site_a": "Hospital A",
    "site_b": "Hospital B",
    "site_c": "Hospital C",
}

# Fraction of each class's patients steered to each site. Rows sum to 1. These
# are targets, not guarantees: patients are indivisible and vary in slice count,
# so the achieved mix is close but not exact. The script prints what it got.
MIX = {
    # class index      site_a  site_b  site_c
    0: (0.60, 0.15, 0.25),  # meningioma -> mostly A
    1: (0.15, 0.60, 0.25),  # glioma     -> mostly B
    2: (0.25, 0.25, 0.50),  # pituitary  -> mostly C
}

TEST_FRACTION = 0.20


def patients_by_class(y, pid):
    """Group patients by class, checking each patient really has only one."""
    classes = defaultdict(set)
    for patient in np.unique(pid):
        labels = set(y[pid == patient].tolist())
        if len(labels) != 1:
            raise SystemExit(f"patient {patient} spans classes {labels}")
        classes[labels.pop()].add(patient)
    return {k: sorted(v) for k, v in classes.items()}


def take_test_patients(by_class, rng):
    """Hold out TEST_FRACTION of the patients in every class, before any site."""
    held = []
    for label, patients in by_class.items():
        order = list(patients)
        rng.shuffle(order)
        count = max(1, round(len(order) * TEST_FRACTION))
        held.extend(order[:count])
        by_class[label] = order[count:]
    return set(held)


def assign(by_class, pid, rng):
    """Walk each class's patients, giving each to the site furthest behind.

    Greedy against a slice-count target rather than a patient-count target,
    because patients differ in how many slices they contribute and it is the
    slices that decide how much a site actually learns.
    """
    slices_of = {p: int((pid == p).sum()) for p in np.unique(pid)}
    assignment = {site: [] for site in SITES}

    for label, patients in by_class.items():
        order = list(patients)
        rng.shuffle(order)
        total = sum(slices_of[p] for p in order)
        target = {site: total * share for site, share in zip(SITES, MIX[label])}
        got = {site: 0 for site in SITES}

        # Largest patients first: placing the big ones while every site is still
        # empty keeps any one of them from overshooting at the end.
        for patient in sorted(order, key=lambda p: -slices_of[p]):
            site = max(SITES, key=lambda s: target[s] - got[s])
            assignment[site].append(patient)
            got[site] += slices_of[patient]

    return assignment


def report(name, y, class_names):
    counts = [int((y == i).sum()) for i in range(len(class_names))]
    share = " ".join(
        f"{class_names[i][:4]}={counts[i]:4d} ({counts[i] / max(len(y), 1):3.0%})"
        for i in range(len(class_names))
    )
    print(f"  {name:12s} {len(y):5d} slices   {share}")
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20260815)
    parser.add_argument("--in-file", type=Path, default=IN_FILE)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()

    if not args.in_file.exists():
        print(f"Missing {args.in_file} — run demo/fl/prepare_data.py first.")
        return 1

    data = np.load(args.in_file, allow_pickle=True)
    x, y, pid = data["x"], data["y"], data["pid"]
    class_names = [str(c) for c in data["class_names"]]
    rng = np.random.default_rng(args.seed)

    by_class = patients_by_class(y, pid)
    test_patients = take_test_patients(by_class, rng)
    assignment = assign(by_class, pid, rng)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "seed": args.seed,
        "source": str(args.in_file.relative_to(ROOT)),
        "class_names": class_names,
        "test_fraction": TEST_FRACTION,
        "sites": {},
    }

    print("=== shared held-out test set ===")
    mask = np.isin(pid, list(test_patients))
    np.savez_compressed(args.out_dir / "test.npz", x=x[mask], y=y[mask], pid=pid[mask])
    counts = report("test", y[mask], class_names)
    manifest["test"] = {
        "slices": int(mask.sum()),
        "patients": len(test_patients),
        "class_counts": counts,
    }

    print("\n=== per-site training data (non-IID, patient-disjoint) ===")
    seen = set(test_patients)
    for site in SITES:
        patients = assignment[site]
        overlap = seen.intersection(patients)
        if overlap:
            print(f"  FAILED: {site} shares patients with an earlier split: {overlap}")
            return 1
        seen.update(patients)

        mask = np.isin(pid, patients)
        np.savez_compressed(
            args.out_dir / f"{site}.npz",
            x=x[mask],
            y=y[mask],
            pid=pid[mask],
            site=site,
            label=SITE_LABELS[site],
        )
        counts = report(SITE_LABELS[site], y[mask], class_names)
        manifest["sites"][site] = {
            "label": SITE_LABELS[site],
            "slices": int(mask.sum()),
            "patients": len(patients),
            "class_counts": counts,
        }

    covered = sum(m["slices"] for m in manifest["sites"].values()) + manifest["test"]["slices"]
    if covered != len(y):
        print(f"\n  FAILED: {covered} slices placed, {len(y)} in the source.")
        return 1

    (args.out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"\n  every slice placed exactly once ({covered})")
    print(f"  wrote {args.out_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
