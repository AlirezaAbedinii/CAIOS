#!/usr/bin/env python3
"""The one model definition, shared by the baselines and by every FL client.

Imported by ``baselines.py`` here and by ``client.py`` inside each hospital's
workspace, so it must stay self-contained: numpy and tensorflow, nothing else,
no imports from elsewhere in this repository. It is copied into the per-site
bundles verbatim (see ``scripts/build-fl-bundles.sh``).

WHY EVERY MODEL IN THE DEMO IS THIS ONE

Site-alone, centralised and federated are only comparable if the architecture,
the optimiser and the preprocessing are identical and the only thing that
changes is which data was seen. One file, three callers.

WHY IT IS SMALL, AND WHY THERE IS NO BATCH NORMALISATION

Small because the client nodes are CPU-only (D-18) and a federated round has to
finish while an audience watches. ~200k parameters trains a round in seconds and
is plenty for three tumour classes at 64x64.

No batch normalisation, deliberately. BatchNorm keeps running mean and variance
as non-trainable state, and FedAvg averages those across sites that hold very
different class mixes — exactly our case. The usual result is a model that
scores well on each client and badly on the shared test set, which would look
like a federated learning failure while actually being a normalisation
artefact. Dropout does the regularising instead.
"""

from pathlib import Path

import numpy as np

N_CLASSES = 3
IMAGE_SIZE = 64
INPUT_SHAPE = (IMAGE_SIZE, IMAGE_SIZE, 1)


def load_split(path):
    """Load one .npz shard as (x, y) ready for Keras.

    Images arrive as uint8 (see ``prepare_data.py``) and are scaled to 0-1 here
    rather than at preparation time, so the cached arrays stay 1 byte a pixel.
    """
    data = np.load(Path(path), allow_pickle=True)
    x = data["x"].astype("float32") / 255.0
    x = x.reshape((-1, IMAGE_SIZE, IMAGE_SIZE, 1))
    y = data["y"].astype("int32")
    return x, y


def build_model(seed: int = 20260815):
    """A small CNN. Same weights at every call for a given seed.

    The seed matters more than it looks: FedAvg averages weights position by
    position, so every client has to start from the same architecture. Starting
    from the same *initial values* as well makes runs reproducible and the
    first round's aggregate meaningful rather than an average of three unrelated
    random models.
    """
    import keras
    from keras import layers

    keras.utils.set_random_seed(seed)

    model = keras.Sequential(
        [
            layers.Input(shape=INPUT_SHAPE),
            layers.Conv2D(32, 3, activation="relu"),
            layers.MaxPooling2D(2),
            layers.Conv2D(64, 3, activation="relu"),
            layers.MaxPooling2D(2),
            layers.Conv2D(64, 3, activation="relu"),
            layers.MaxPooling2D(2),
            layers.Flatten(),
            layers.Dense(64, activation="relu"),
            layers.Dropout(0.3),
            layers.Dense(N_CLASSES, activation="softmax"),
        ],
        name="caios_brain_mri",
    )
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=1e-3),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )
    return model


def quiet_tensorflow(cpu_only: bool = True):
    """Silence TensorFlow's startup banner. Call this *before* importing keras.

    Cosmetic, but this runs in front of an audience: the federated round output
    should not be buried under CUDA warnings.

    ``cpu_only`` defaults to true because every FL client is CPU-only by
    decision (D-18) and TensorFlow otherwise spends the first seconds probing
    for a GPU it will not be given. Pass false if you are deliberately checking
    that a workspace can see its GPU.
    """
    import os

    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    if cpu_only:
        os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
