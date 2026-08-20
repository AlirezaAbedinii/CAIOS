# docuum — Docker image garbage collector, one per compute node.
#
#   nomad job run nomad-jobs/docuum.hcl        (or: ansible/playbook-docuum.yml)
#
# WHY THIS FILE EXISTS
# --------------------
# Upstream deploys this from roles/nomad/templates/nomad-docuum-job.j2 with
# `--threshold 50 GB` hardcoded. That was fine until the LLM tool arrived:
#
#     vllm/vllm-openai:v0.27.1     30.8 GB on disk   (10.5 GB compressed)
#     ghcr.io/open-webui           7.1 GB
#     ai4os-dev-env:pytorch2.1     12.9 GB
#     ai4os-federated-server x2    9.5 GB
#     ...everything else           ~6 GB
#     -------------------------------------
#     the full pre-pull set        ~68 GB
#
# So on 2026-08-19, running playbook-prepull-images.yml against caios_llm pulled
# all eleven images, reported success for all eleven, and docuum silently deleted
# six of them before the playbook finished. `docker images` showed five. The
# playbook's whole purpose is to keep a 30 GB pull off the demo's critical path,
# and a garbage collector was undoing it as it worked.
#
# Worse than the wasted bandwidth: the vLLM image is the biggest thing on the
# node, so it is a prime eviction candidate. A dev environment deployed after it
# would push past the threshold and evict it, and the next LLM deployment would
# re-download 30 GB — in front of an audience.
#
# 80 GB leaves ~12 GB of headroom above the full set, and still leaves ~45 GB of
# the 125 GB volume for allocation directories, logs and the Hugging Face model
# cache. Raising it further would start competing with those.
#
#   !!  Re-running ansible/playbook-nomad.yml against nomad_master REVERTS this
#       to 50 GB, because that role re-submits its own template. Re-run
#       ansible/playbook-docuum.yml afterwards. scripts/verify-cluster.sh reports
#       the live threshold so the regression is visible rather than silent.

job "docuum" {
  namespace = "default"
  type      = "system"
  region    = "global"
  id        = "docuum"
  priority  = "75"

  constraint {
    attribute = "${meta.compute}"
    operator  = "="
    value     = "true"
  }

  group "usergroup" {

    count = 1

    task "usertask" {

      driver = "docker"

      config {
        image = "stephanmisc/docuum"
        init  = true
        args  = ["--threshold", "80 GB"]

        mount {
          type   = "bind"
          target = "/var/run/docker.sock"
          source = "/var/run/docker.sock"
        }

        mount {
          type   = "volume"
          target = "/root"
          source = "docuum"
        }
      }

      resources {
        cpu    = 100
        memory = 200
      }
    }
  }
}
