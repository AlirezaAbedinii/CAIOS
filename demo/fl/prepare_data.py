#!/usr/bin/env python3
"""Fetch the public brain-tumour MRI set and reduce it to one small array file.

    python3 demo/fl/prepare_data.py                 # download, decode, cache
    python3 demo/fl/prepare_data.py --size 96       # a different image size

Writes ``demo/data/brain_mri.npz``. Downloads are cached under
``demo/data/raw/`` and reused, so a second run costs nothing.

WHAT THE DATASET IS

Cheng et al., "brain tumor dataset", figshare (CC BY 4.0): 3064 T1-weighted
contrast-enhanced MRI slices from 233 patients, each labelled with one of three
tumour types — meningioma, glioma, pituitary. It is public, needs no
registration, and is the standard benchmark for this task, which is exactly what
D-07 asks for: no real patient imaging of ours, so no ethics question and no
audience question we cannot answer.

Three classes is not an accident of the data — it is what makes the federated
story legible. One site can be given mostly meningioma, another mostly glioma,
and the third a mix, and the resulting models are visibly different. See
``partition.py``.

WHY THE PATIENT ID IS CARRIED THROUGH

Each ``.mat`` holds a ``PID`` alongside the image. A patient contributes several
slices, and consecutive slices of one tumour are nearly identical. Split those
at random and the same patient lands in both training and test, the test score
climbs several points, and the number is meaningless. So the patient ID is kept
here and every split downstream is patient-disjoint. It costs one array and
removes the first question a reviewer would ask.

WHY 64x64

The demo has to complete a federated round in seconds on a CPU-only client
(D-18). At 64x64 the whole dataset is ~12 MB and a round takes a few seconds; at
the native 512x512 it is 800 MB and minutes. Nothing about the federated
mechanism changes with resolution, and the mechanism is the point.
"""

import argparse
import io
import sys
import zipfile
from pathlib import Path
from urllib.request import urlopen

import h5py
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "demo" / "data" / "raw"
OUT_FILE = ROOT / "demo" / "data" / "brain_mri.npz"

# figshare article 1512427. The download IDs are stable; the article API is not
# consulted at runtime so that a prepared machine works without figshare being up.
ARCHIVES = {
    "brainTumorDataPublic_1-766.zip": "https://ndownloader.figshare.com/files/3381290",
    "brainTumorDataPublic_767-1532.zip": "https://ndownloader.figshare.com/files/3381296",
    "brainTumorDataPublic_1533-2298.zip": "https://ndownloader.figshare.com/files/3381293",
    "brainTumorDataPublic_2299-3064.zip": "https://ndownloader.figshare.com/files/3381302",
}

# The .mat files label 1/2/3. We store 0/1/2 so the arrays index directly.
CLASS_NAMES = ["meningioma", "glioma", "pituitary"]

EXPECTED_SLICES = 3064


def download(name: str, url: str) -> Path:
    """Fetch one archive unless it is already on disk and non-trivial in size."""
    dest = RAW_DIR / name
    if dest.exists() and dest.stat().st_size > 1_000_000:
        print(f"  cached   {name} ({dest.stat().st_size / 1e6:.0f} MB)")
        return dest

    print(f"  fetching {name} ...", end="", flush=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    with urlopen(url, timeout=120) as response, open(tmp, "wb") as handle:
        while chunk := response.read(1 << 20):
            handle.write(chunk)
    tmp.rename(dest)
    print(f" {dest.stat().st_size / 1e6:.0f} MB")
    return dest


def decode_slice(raw: bytes, size: int):
    """Turn one .mat member into (image, label, patient-id).

    The files are MATLAB v7.3, which is HDF5, so h5py reads them directly.
    Intensities are int16 with a per-scan range, so each slice is min-max
    normalised to 0-255 before resizing. Normalising globally instead would let
    one bright scan flatten every other.
    """
    with h5py.File(io.BytesIO(raw), "r") as handle:
        record = handle["cjdata"]
        image = np.array(record["image"], dtype=np.float32)
        label = int(np.array(record["label"]).squeeze())
        # PID is stored as MATLAB character codes, one per row.
        patient = "".join(chr(c) for c in np.array(record["PID"]).flatten())

    lo, hi = float(image.min()), float(image.max())
    image = (image - lo) / (hi - lo) * 255.0 if hi > lo else np.zeros_like(image)

    resized = Image.fromarray(image.astype(np.uint8)).resize(
        (size, size), Image.BILINEAR
    )
    return np.asarray(resized, dtype=np.uint8), label - 1, patient.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=64, help="output edge in pixels")
    parser.add_argument("--out", type=Path, default=OUT_FILE)
    args = parser.parse_args()

    print("=== 1. archives ===")
    paths = [download(name, url) for name, url in ARCHIVES.items()]

    print(f"\n=== 2. decoding to {args.size}x{args.size} ===")
    images, labels, patients = [], [], []
    for path in paths:
        with zipfile.ZipFile(path) as archive:
            members = [m for m in archive.namelist() if m.endswith(".mat")]
            for member in sorted(members, key=lambda m: int(m.split(".")[0])):
                image, label, patient = decode_slice(archive.read(member), args.size)
                images.append(image)
                labels.append(label)
                patients.append(patient)
        print(f"  {path.name}: {len(members)} slices")

    x = np.stack(images)
    y = np.asarray(labels, dtype=np.int8)
    pid = np.asarray(patients)

    if len(x) != EXPECTED_SLICES:
        print(f"\n  WARNING: got {len(x)} slices, expected {EXPECTED_SLICES}.")
    if set(np.unique(y)) != {0, 1, 2}:
        print(f"\n  FAILED: labels are {np.unique(y)}, expected 0/1/2.")
        return 1

    print("\n=== 3. summary ===")
    print(f"  slices    {len(x)}")
    print(f"  patients  {len(np.unique(pid))}")
    for index, name in enumerate(CLASS_NAMES):
        count = int((y == index).sum())
        print(f"  {name:11s} {count:5d}  ({count / len(y):.0%})")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.out, x=x, y=y, pid=pid, class_names=CLASS_NAMES)
    print(f"\n  wrote {args.out} ({args.out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
