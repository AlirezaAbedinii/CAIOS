# LLM deployment — what the pieces are

Background for `docs/llm-plan.md`. Read this if "vLLM" and "Open WebUI" are
words rather than things. If you already know what they are, skip to
[the comparison table](#the-difference-in-one-table) and then to the plan.

---

## The feature in one sentence

A researcher picks a language model from a list, clicks Deploy, and two minutes
later has a private ChatGPT-like web page and an OpenAI-compatible API endpoint
running on CAIOS hardware — **with no prompt, no document and no patient note
ever leaving the cluster**.

That last clause is the whole point, and it is the same argument as federated
learning: the data stays where it is. Federated learning makes that true for
*training*; this makes it true for *inference*. Together they are one story
rather than two features.

---

## vLLM — the engine

**vLLM is an inference server.** You give it a model from Hugging Face; it
loads the weights onto the GPU and serves an HTTP API. It has no user
interface, no login page and no memory of a conversation.

Its API is deliberately **OpenAI-compatible**: the same request shape as
`api.openai.com`, on the same paths.

```
GET  /v1/models                 what is loaded
POST /v1/chat/completions       chat, optionally streamed
POST /v1/completions            raw text completion
```

That compatibility is the reason it is worth deploying at all. Anything already
written against the OpenAI SDK — a Python notebook, a VS Code assistant, a
LangChain pipeline — points at our endpoint by changing one base URL and one
key. No new client library, no new protocol.

**Why vLLM specifically, rather than plain `transformers`:** two techniques.
*PagedAttention* stores the attention cache in fixed-size pages instead of one
contiguous block per request, so memory is not wasted on padding and many
conversations share the GPU. *Continuous batching* lets a new request join the
running batch at the next token step instead of waiting for the batch to drain.
On a small GPU, that is the difference between one user at a time and a room
full of them.

**What it costs:** a GPU, for as long as it is running. vLLM reserves its memory
budget at startup and holds it. An idle vLLM is an occupied GPU.

## Open WebUI — the face

**Open WebUI is a chat front end.** It looks like ChatGPT: a conversation list
on the left, a message box at the bottom, streamed replies, markdown and code
highlighting. It has accounts, an admin panel, per-user chat history, document
upload, and a simple RAG feature ("chat with these PDFs").

It runs no model of its own. It is a client. It needs to be pointed at an
OpenAI-compatible endpoint, and it will happily talk to:

- a vLLM we deployed in the same job (`type: both`),
- a vLLM someone else deployed (`type: open-webui` + endpoint and key),
- OpenAI, Azure, or any other compatible provider.

**What it costs:** CPU and RAM, no GPU. It is a Python/Node web application
with a SQLite database. It is not free — it does document parsing and
embedding — but nothing it does needs a graphics card.

---

## The difference in one table

| | vLLM | Open WebUI |
|---|---|---|
| What it is | Model server | Chat web app |
| Runs the model? | Yes | No — it calls something that does |
| Needs a GPU? | **Yes** | No |
| Has a UI? | No | **Yes** |
| Has logins? | One shared bearer token | Real accounts, admin panel |
| Remembers a conversation? | No — stateless | Yes, per user |
| Speaks | HTTP, OpenAI schema | HTTP, to humans |
| In our job | task `vllm`, holds `meta.gpu` | task `open-webui` |
| Reachable at | `vllm-<uuid>.<domain>/v1` | `ui-<uuid>.<domain>` |

The short version: **vLLM is the engine, Open WebUI is the dashboard on the
steering wheel.** Neither is much use to a demo audience alone. vLLM alone is a
`curl` command; Open WebUI alone is a login page with nothing behind it.

---

## The three deployment types

The tool's `type` field picks which tasks the Nomad job actually contains.
PAPI builds the full job and then deletes the tasks that do not apply
(`routers/v1/deployments/tools.py`, the `exclude_tasks` block).

### `both` — the default, and what the demo uses

Four tasks in one allocation:

| Task | Lifecycle | Job |
|---|---|---|
| `vllm` | prestart sidecar | Loads the model, serves `/v1`. Holds the GPU. |
| `check_vllm_startup` | prestart, blocking | Polls `/v1/models` until it answers, then exits. Its whole purpose is to stop Open WebUI from starting against a model that is still loading. |
| `open-webui` | main | The chat UI. |
| `create-admin` | poststart | POSTs to `/api/v1/auths/signup` to claim the first account, because Open WebUI has no way to configure an admin from the environment. Without it, **the first stranger to find the URL becomes the administrator**. |

One deployment, one GPU, two hostnames, everything wired together. This is
what a demo should show.

### `vllm` — API only

Just the engine. Used when the consumer is code, not a person: a notebook, a
VS Code assistant, an evaluation script. PAPI mints a random bearer token,
stores it in Vault under `deployments/<uuid>/llm/vllm`, and shows it in the
deployment detail page.

This is also the cheapest thing to test with — no UI to log into, and `curl`
either gets a completion or it does not.

> One quirk: in `both` mode `vllm` is a *sidecar*, so the allocation lives as
> long as the main task. In `vllm`-only mode PAPI flips `Sidecar` to `false` and
> promotes it to the main task, otherwise Nomad would consider the job finished
> the moment the health check passed and shut it down.

### `open-webui` — UI only

A chat front end pointed at an endpoint you already have. Requires
`openai_api_url` and `openai_api_key`. No GPU. Useful for giving a team a
shared front door to one shared model, instead of every member deploying their
own copy of the same weights.

---

## Where this sits in the CAIOS architecture

Nothing new. It is a tool like any other, and it goes through the same path:

```
Browser ──▶ Dashboard ──▶ PAPI ──▶ Nomad ──▶ caios_llm node
                            │                     │
                            └─▶ Vault             ├─ task vllm       (GPU)
                              (the API token)     └─ task open-webui (CPU)
                                                        │
Browser ──────────── Traefik ◀───────────────────────────┘
             ui-<uuid>.pacs-deployments.<edge-ip>.sslip.io
             vllm-<uuid>.pacs-deployments.<edge-ip>.sslip.io
```

Both hostnames are already covered by the wildcard certificate we issue
(`*.pacs-deployments.192.168.104.105.sslip.io` — verified), so ingress needs no
change at all. The security groups need no change either; unlike NVFLARE this
is plain HTTPS on 443.

---

## What this is *not*

**It is not the "LLM Chat" sidenav entry.** That points at AI4EOSC's own hosted
assistant, and our tenant config blanks it (see `configs/dashboard/caios.json`).
Upstream's PAPI endpoint behind it is disabled in source anyway —
`routers/v1/llm/chat.py` raises `503 Endpoint temporarily disabled`. We are
building the self-service tool, not the hosted assistant.

**It is not a medical model.** Every model in the platform catalogue is a
general-purpose instruction-tuned model. The demo claim is "your own model on
your own hardware, privately", not "a model that knows medicine". Saying more
than that in front of reviewers would not survive a question. If a specific
medical or clinical-notes model is wanted, it is one line in
`configs/papi/vllm.yaml` plus a fit check — see the open question at the end of
`docs/llm-plan.md`.

**It is not free capacity.** A running vLLM holds an entire GPU. On five nodes
with one GPU each, that is 20% of the cluster per deployment, indefinitely,
until someone deletes it. See `docs/llm-infrastructure.md`.
