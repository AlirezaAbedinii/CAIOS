# Documentation

## Run it

| Document | What it is for |
|---|---|
| [runbook.md](runbook.md) | Operating and debugging the running cluster, and the federated demo |
| [ssh-setup.md](ssh-setup.md) | Giving the control-plane node SSH access to the others |
| [public-access.md](public-access.md) | How the platform is reached from outside, through one public address |
| [nginx-proxy.md](nginx-proxy.md) | The public proxy VM in front of the platform |
| [oscar-gui-guide.md](oscar-gui-guide.md) | Serverless inference through the dashboard, screen by screen |
| [demo-script.md](demo-script.md) | The five-minute demo, beat by beat |
| [../demo/recording/README.md](../demo/recording/README.md) | How the narrated recording is made |

## Understand it

| Document | What it is for |
|---|---|
| [infrastructure.md](infrastructure.md) | The seven nodes, what each does, and why |
| [concepts.md](concepts.md) | Nomad, Consul and Traefik, for someone new to them |
| [llm-concepts.md](llm-concepts.md) | vLLM and Open WebUI, and how they differ |
| [llm-infrastructure.md](llm-infrastructure.md) | The GPU hardware, measured, and what fits on it |
| [scope.md](scope.md) | What is in and out of scope |
| [feature-coverage.md](feature-coverage.md) | Each section of the reference AI4OS dashboard, and whether CAIOS has it |
| [licensing.md](licensing.md) | What CAIOS is licensed under, and what it inherits |

## Why it is the way it is

| Document | What it is for |
|---|---|
| [decisions.md](decisions.md) | Every settled decision, with what was rejected (append-only) |

The team's working plans and progress log are kept outside this repository.
Where a comment cites one of them (`docs/demo-plan.md`, `docs/progress.md` and
the like), the decision it records is in [decisions.md](decisions.md).
