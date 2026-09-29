# The high-code notebook

The high-code tier of the demo (`docs/demo-plan.md`): the YOLO module from the
marketplace, deployed as a JupyterLab workspace instead of an API, and a
four-cell notebook run inside it.

| Cell | What it shows | Measured |
|---|---|---|
| 1 | YOLO detects objects in an image and draws them | 1.4 s, CPU |
| 2 | what it found, counted | 0.0 s |
| 3 | the same model, called as the low-code tier's serverless service | 5.2–8.2 s |
| 4 | the private LLM from the no-code tier, describing the result | 0.3 s |

All on CPU. None of the marketplace modules can use this cluster's GPU (step 2
of the plan), and YOLO does not need one to answer in a second and a half.

## Files

| File | |
|---|---|
| `high-code.ipynb` | the notebook, committed with its outputs cleared |
| `caios_demo.py` | its two remote calls, `serverless()` and `ask()` |

Neither contains an endpoint or a secret. `scripts/stage-high-code.sh` fetches
them from PAPI with the owners' own tokens and writes them into the workspace as
`.caios.json` (mode 600) and `.caios-ca.pem` — dotfiles, so the file browser on
camera does not list them. `tests/test_high_code_notebook.py` holds all of that.

## Staging it

1. Deploy the workspace from the dashboard, as `researcher`: Marketplace →
   YOLO → *Deploy* ▾ → the dedicated option → **Service: Jupyter**, one CPU,
   no GPU, and a password you will type on camera.
2. Have a running LLM deployment and a YOLO serverless service for the same
   account.
3. On `caios_server`:

   ```bash
   bash scripts/stage-high-code.sh <workspace-uuid> <llm-uuid>
   ```

   It writes the files into `/srv/caios-demo/` and runs the notebook once,
   headless, printing each cell's time and result. That run is also the
   warm-up: YOLO's weights come from GitHub at first use, and the serverless
   service scales from zero.

4. In JupyterLab: `caios-demo/high-code.ipynb`, *Run → Run All Cells*.

The serverless call is the only slow cell, and only when the service has scaled
to zero — Knative keeps it warm for about 30 s after a request. Run it once just
before the take, or cut.
