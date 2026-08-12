# CAIOS catalogue

What a medical or neuroscience researcher sees when they open the Marketplace.

Deployed as-is, the stock catalogue shows them coral reef segmentation. This is
not polish — it is the first thing the audience looks at, and it decides whether
the platform reads as theirs.

---

## The gap, measured

46 modules in the upstream catalogue. Verified against `.gitmodules` and the
live catalogue API, not estimated.

| Domain | Count |
|---|---|
| Marine and environmental | ~20 |
| Generic backbones (classification, detection, benchmarks) | ~10 |
| Remote sensing and thermal | ~7 |
| Agricultural | ~4 |
| **Medical** | **2** |
| **Neuroscience** | **0** |

The two medical ones:

| Module | What it does |
|---|---|
| `image-classification-tf-dicom` | Chest X-ray, pathological vs non-pathological. Speaks DICOM, which anchors the PACS framing directly. |
| `retinopathy-test` | Retinopathy classification. |

Counting generously you reach four by adding `UC-adnaneds-DEEP-OC-unet`
(generic 2D semantic segmentation) and `posenet-tf` (body pose). Neither is
medical by tag or description.

---

## Closing it

Three routes, in order of value per day spent.

### 1. bioimage.io models through the AI4Life loader — highest value, zero code

The `ai4os-ai4life-loader` tool deploys any bioimage.io model by ID. Its
supported set is 68 models, of which **57 are life-science imaging** and several
are genuinely neuroscience rather than neuroscience-adjacent.

This is the finding that closes the neuroscience gap. Connectomics — tracing
neurons through electron microscopy volumes — is core neuroscience, and there
are three ready-to-deploy models for it.

**Deploy these first:**

| ID | Model | Why it matters |
|---|---|---|
| `zealous-snail` | 3D Attention U-Net, neuron segmentation | Circuit reconstruction from EM. Connectomics, tagged `neurons`. |
| `good-butterfly` | 3D Attention U-Net, mitochondria segmentation | Mitochondria in EM — standard neuroscience EM analysis. |
| `affable-shark` | NucleiSegmentationBoundaryModel | Nucleus segmentation, fluorescence microscopy. 70,000+ downloads, so it is the one most likely to be recognised. |

**Good second tier:**

| ID | Model | Note |
|---|---|---|
| `exuberant-parrot` | 3D ResUNet++, neuron segmentation | Same task as `zealous-snail`, different architecture — useful for showing model comparison. |
| `willing-whale` | 3D Residual U-Net, neuron segmentation | Third architecture on the same task. |
| `famous-fish` | CellPose (cyto3) | Widely used, instantly recognisable to a cell biologist. |
| `humorous-fox` | SEM_N2V | Denoising for scanning EM. Realistic preprocessing step. |
| `resourceful-otter` | 2D Attention U-Net, nucleus segmentation | 2D counterpart, cheaper to run live. |

Verified against the loader's own `filtered_models.json` at `main`, so every ID
here is one the tool will actually accept.

> Two of the three connectomics models report zero downloads. That is a
> statement about bioimage.io traffic, not about model quality — they are
> published, versioned and loadable. Worth knowing before someone asks.

### 2. Keep and promote the two real medical modules

`image-classification-tf-dicom` earns its place: it speaks DICOM, which is
exactly the PACS story. Feature it near the top rather than leaving it buried
among plankton classifiers.

### 3. One custom neuroscience module — first thing to cut

Built from `ai4-template`, for example brain MRI classification on a public
dataset. The only way to get a module that is natively ours. Costs 1.5-2 days.
Given route 1 delivers real connectomics models for free, this is now clearly a
V1 stretch item rather than a necessity.

---

## What to actually do

The catalogue is a fork of `ai4os-hub/modules-catalog`, which is a list of git
submodules. Curating means removing submodules, not writing code.

**MVP:**

1. Fork `ai4os-hub/modules-catalog`.
2. Remove the marine, agricultural and remote-sensing submodules — roughly 31 of
   46 — with `utils/remove-submodule.sh`.
3. Keep: the two medical modules, and the generic backbones a researcher would
   genuinely use on their own data (`ai4os-image-classification-tf`,
   `ai4os-yolo-torch`, `ai4os-fasterrcnn-torch`, `obj-detection-torch`,
   `ai4os-demo-app` for the try-me path).
4. Point PAPI at the fork.

That leaves roughly 15 modules, all plausibly useful to the audience.

**Then, in Stage 4:** deploy two or three of the bioimage.io models above
through the AI4Life loader, so the catalogue shows working neuroscience rather
than only medical-adjacent generic models.

> Emptier and relevant beats fuller and irrelevant. A researcher scanning 15
> modules that could all apply to their work forms a better impression than one
> scrolling past 30 they will never use to find 4 they might.
