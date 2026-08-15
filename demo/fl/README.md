# Federated learning demo

The headline feature: a model trained across three hospital sites where the data
never leaves any of them.

To *run* it, see **`docs/runbook.md`, "Running the federated demo"**. This file
says what each piece is and why it exists.

---

## The claim, and where each part of it is enforced

> Three hospitals hold different patients. Each trains locally. Only weights are
> exchanged. The result beats what any hospital could do alone, and comes close
> to what pooling all the data would give.

| Part of the claim | Where it is made true |
|---|---|
| Different patients, unevenly | `partition.py` — non-IID by design, split by patient |
| Held separately | `scripts/build-fl-bundles.sh` — Site A's bundle has no Site B data |
| On separate machines | `ansible/playbook-scheduler-config.yml` — `spread`, not `binpack` |
| Only weights leave | `client.py` — sends weights, a count and an accuracy |
| Beats training alone | `baselines.py` and the chart |

---

## Files

| File | What it does |
|---|---|
| `prepare_data.py` | Downloads the public brain-tumour MRI set, reduces it to one array file |
| `partition.py` | Splits it non-IID across three sites, plus a shared held-out test set |
| `model.py` | The one model definition — used by the baselines *and* every client |
| `baselines.py` | Trains site-alone (×3) and centralised: the two lines FL is measured against |
| `client.py` | One hospital's Flower client. Runs inside a workspace |
| `local_server.py` | Stand-in for the deployed server, for rehearsing without the cluster |
| `bootstrap.sh` | The one line pasted into a workspace terminal |
| `plot_results.py` | The three-line chart the demo ends on |
| `results/` | Baseline curves, the cluster run, and the chart |

Scripts that drive these live in `scripts/`: `fl-rehearse.sh` (whole federation
on one machine, one minute), `build-fl-bundles.sh`, `deploy-fl-demo.sh`.

---

## Results, as measured

```
  federated across three sites   0.710 -> 0.842, best 0.853
  best single hospital alone     0.806
  all data pooled centrally      0.865
```

Federated closes 81% of the gap between the best single site and pooling
everything. Ten rounds, thirty seconds, three nodes, zero failed rounds.

Two things make those numbers comparable rather than decorative. Every line is
scored on one test set, held out before the sites were formed and
patient-disjoint from all of them. And every line is trained in **rounds**, not
epochs — at round 5 a site-alone model has made exactly as many passes over its
own data as a federated client has — so the chart compares methods, not training
budgets.

These are single runs. Round-to-round movement of ±0.03 is noise, and the
centralised line crosses the federated one in places for that reason. Read the
levels, not the crossings.

---

## Two things that look like bugs and are not

**The server hangs after starting.** It waits for all three clients
(`min_fit_clients: 3`). Two connected clients wait forever, by design.

**Every site reports the identical accuracy.** They are all scoring the same
aggregated global model on the same shared test set, so they agree exactly. That
is what makes any one client's curve *the* federated curve.

---

## Changing something

The workspaces fetch the **bundle**, not this repository. After editing
`client.py` or `model.py`:

```bash
bash scripts/fl-rehearse.sh        # prove it locally first — one minute
bash scripts/build-fl-bundles.sh   # then republish
```

Skipping the second step is the most likely reason a change appears to have no
effect.
