# LLM catalogue test results

`catalogue-results.tsv` is the output of `scripts/check-llm-catalogue.sh`, which
deploys every model the dashboard offers, asks each one a question, and deletes
it again. Run on 2026-08-20 against `caios_llm`.

It exists because the catalogue was assembled by arithmetic — weights plus
overhead against a measured 9680 MiB budget — and arithmetic had already been
wrong twice on this project: the vLLM image was quoted at 10.5 GB and is 30.8 GB
on disk, and the weight cache was predicted to save minutes and saves 22 seconds.

## Results

| model | verdict | ready | tok/s |
|---|---|---|---|
| Qwen3.5-2B *(default)* | ok | 182 s | 76.6 |
| Qwen3.5-0.8B | ok | 172 s | 128.7 |
| Ministral-3-3B-Instruct-2512 | ok | 101 s | 18.2 |
| LFM2.5-1.2B-Instruct | ok | 81 s | 59.7 |
| LFM2.5-1.2B-Thinking | ok\* | 81 s | — |
| LFM2.5-VL-450M | ok | 91 s | 68.9 |
| LFM2.5-VL-1.6B | ok | 91 s | 63.4 |
| granite-4.1-3b | ok | 111 s | 51.4 |
| DeepSeek-R1-Distill-Qwen-1.5B | ok\* | 91 s | — |

**Nine of nine load and answer. Nothing ran out of GPU memory.**

\* The two thinking models return their answer in the OpenAI response's
`reasoning` field rather than `content` — see below.

## What this settled

**The memory budget is right.** No model failed to load, including
`granite-4.1-3b`, which `configs/papi/vllm.yaml` had warned was "the tightest
model we offer; if Stage L3 finds it will not load, drop it". It loads in 111 s.
The warning was wrong in the safe direction, and only testing showed that.

**The default is the slowest model on the list.** Qwen3.5-2B takes 182 s;
LFM2.5-1.2B-Instruct is ready in 81 s. Worth weighing before the demo — it is
less than half the wait, at some cost in answer quality.

**Throughput varies more than size predicts.** Ministral-3-3B manages 18 tok/s
against LFM2.5-1.2B's 60 and Qwen3.5-0.8B's 129. Fine for a chat window, but
Ministral is noticeably slower to watch.

## The two thinking models

`LFM2.5-1.2B-Thinking` and `DeepSeek-R1-Distill-Qwen-1.5B` keep vLLM's
`--reasoning-parser`, so they answer into `reasoning` and leave `content` null.
Every other model in the catalogue answers into `content`.

Both alternatives were measured, and both are imperfect:

| | `content` | how it reads |
|---|---|---|
| with the parser | `null` | Open WebUI renders the reasoning as a collapsible section — good. A plain OpenAI client reads `content` and gets `None`. |
| without the parser | the model's raw thinking | Opens with a literal `<think>` tag on LFM2.5. Looks broken to a person. |

The parser is kept, because the demo audience is people looking at a chat window
and a visible `<think>` tag is the worse of the two failures. Their catalogue
descriptions warn anyone calling the API to read `reasoning`.

**Still to confirm in Stage L4:** that Open WebUI does render these two well. If
it does not, they should be dropped — seven uniform models beat nine with two
that need an explanation.

## Re-running

```bash
bash scripts/check-llm-catalogue.sh          # all of them, about an hour
bash scripts/check-llm-deploy.sh <model-id>  # just one
```

`catalogue-results-BROKEN-HARNESS.tsv` is a first pass kept deliberately: it
reported three healthy models as timeouts because the harness cached PAPI's
endpoint while it still contained a literal `${meta.domain}`. Kept as a reminder
that a red result is a claim about the test as much as about the thing tested.
