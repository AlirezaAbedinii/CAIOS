/*
CAIOS job template for the LLM tool.

Mounted over /home/ai4-papi/etc/tools/ai4os-llm/nomad.hcl by
compose/docker-compose.yml. Upstream lives in vendor/ai4-papi/; never edit there.

Convention (upstream's, unchanged):
* ${UPPERCASE} are replaced by PAPI before submission
* ${lowercase} are replaced by Nomad at launch time
* PAPI uses safe_substitute(), so Nomad's placeholders survive untouched

WHAT IS DIFFERENT FROM UPSTREAM, AND WHY
========================================
Four changes. Three of them are the difference between "this tool cannot run
here" and "this tool runs here"; see docs/llm-risks.md for the full accounts.

1. THE GPU DEVICE CONSTRAINT IS GONE (R-02)
   Upstream pins device.model = "Tesla T4". No device in this cluster matches,
   so the job would be accepted by PAPI and then sit in `pending` forever with
   no error anywhere — the worst way to fail. There is exactly one GPU model
   here, so a constraint distinguishes nothing and can only go stale. Note the
   name changed under us once already, on 2026-08-19, when the device plugin
   started reporting the MIG instance.

2. IT ASKS FOR RESOURCES THAT EXIST (R-03)
   Upstream asks for 8 dedicated CPU cores and 32 GB across two tasks. These
   nodes have 3 cores and ~30 GB schedulable. The reference deployment has
   64-86 vCPU per node.

   There is a trap in the fix: Nomad's `cores` reserves whole CPUs AND removes
   their share of the MHz pool. Reserve all three on a 6000 MHz node and there
   is nothing left for the two helper tasks, so the job still will not place.
   Hence cores for vLLM, plain `cpu` shares for everything else:

       cores : 2 dedicated                = 4000 MHz reserved  (of 6000)
       shares: 1200 + 100 + 100           = 1400 MHz           (of 2000 left)
       memory: 12000 + 4000 + 300 + 300   = 16600 MB           (of ~30000)
       gpu   : 1                                               (of 1)

   tests/test_llm_job_template.py asserts that arithmetic, so it cannot rot.

3. NOTHING IN THIS JOB LEAVES THE CLUSTER TO REACH ITSELF (R-05)
   Upstream's `check_vllm_startup` and `create-admin` call their own deployment's
   PUBLIC HTTPS URL. Those are served by Traefik with our own CA's certificate,
   which a stock python image has never heard of, so `requests` raises SSLError.
   Neither script catches exceptions, and both are prestart/poststart hooks — so
   the traceback kills the whole allocation, with an error mentioning nothing
   about certificates.

   Both now talk to the allocation directly over ${NOMAD_ADDR_*} on plain HTTP.
   No DNS, no Traefik, no TLS in the startup path — and it tests the right
   thing: "is vLLM up", not "is the entire ingress chain up".

   Open WebUI ITSELF had the same problem, found in Stage L4 and missed by the
   original reading of R-05, which only looked at the two helpers. Its
   OPENAI_API_BASE_URL comes from PAPI, not from this file, so the fix is patch
   0010 rather than a line here. Its failure mode is worse than the helpers':
   aiohttp raises CERTIFICATE_VERIFY_FAILED, Open WebUI catches it, and
   GET /api/models answers **200 with an empty list**. The deployment is green,
   login works, and the model dropdown is empty.

4. IMAGES ARE PINNED AND NOT FORCE-PULLED (R-10, R-11)
   `vllm/vllm-openai:latest` is 10.5 GB and it moves. force_pull on every
   deployment turns a demo into a fifteen-minute silence, and an overnight
   upstream release can break a rehearsed demo. All four images are pinned —
   including python:3.12-slim-bullseye for the two helpers, where upstream's
   bare `python:slim-bullseye` is just as much a moving target — none are
   force-pulled, and all are pre-pulled by ansible/playbook-prepull-images.yml. The Hugging Face cache is
   bind-mounted from the host so a redeploy does not re-download the weights.
*/

job "tool-llm-${JOB_UUID}" {
  namespace = "${NAMESPACE}"
  type      = "service"
  region    = "global"
  id        = "${JOB_UUID}"
  priority  = "${PRIORITY}"

  meta {
    owner       = "${OWNER}"  # user-id from OIDC
    owner_name  = "${OWNER_NAME}"
    owner_email = "${OWNER_EMAIL}"
    title       = "${TITLE}"
    description = "${DESCRIPTION}"
  }

  # Only use nodes that have successfully passed the ai4-nomad_tests (ie. meta.status=ready)
  constraint {
    attribute = "${meta.status}"
    operator  = "regexp"
    value     = "ready"
  }

  # Only launch in compute nodes (to avoid clashing with system jobs, eg. Traefik)
  constraint {
    attribute = "${meta.type}"
    operator  = "="
    value     = "compute"
  }

  # Avoid deploying in nodes that are reserved to batch
  constraint {
    attribute = "${meta.type}"
    operator  = "!="
    value     = "batch"
  }

  # Only deploy in nodes serving that namespace
  constraint {
    attribute = "${meta.namespace}"
    operator  = "regexp"
    value     = "${NAMESPACE}"
  }

  # [CAIOS] Prefer the dedicated LLM host. Upstream's affinities here push CPU
  # work onto CPU nodes; ours is the same idea with our own tag. Soft on purpose
  # — if caios_llm is full or down, this still lands somewhere rather than
  # failing, which matters more for a demo than tidy placement.
  affinity {
    attribute = "${meta.role}"
    operator  = "regexp"
    value     = "llm"
    weight    = 100
  }

  # Avoid rescheduling the job on **other** nodes during a network cut
  reschedule {
    attempts  = 0
    unlimited = false
  }

  group "usergroup" {

    disconnect {
      lost_after = "48h"
      replace    = false
      reconcile  = "keep_original"
    }

    network {
      port "ui" {
        to = 8080
      }
      port "vllm" {
        to = 8000
      }
    }

    service {
      name = "${JOB_UUID}-ui"
      port = "ui"
      tags = [
        "traefik.enable=true",
        "traefik.http.routers.${JOB_UUID}-ui.tls=true",
        "traefik.http.routers.${JOB_UUID}-ui.rule=Host(`ui-${HOSTNAME}.${meta.domain}-${BASE_DOMAIN}`, `www.ui-${HOSTNAME}.${meta.domain}-${BASE_DOMAIN}`)",
      ]
    }

    service {
      name = "${JOB_UUID}-vllm"
      port = "vllm"
      tags = [
        "traefik.enable=true",
        "traefik.http.routers.${JOB_UUID}-vllm.tls=true",
        "traefik.http.routers.${JOB_UUID}-vllm.rule=Host(`vllm-${HOSTNAME}.${meta.domain}-${BASE_DOMAIN}`, `www.vllm-${HOSTNAME}.${meta.domain}-${BASE_DOMAIN}`)",
      ]
    }

    ephemeral_disk {
      size = 4096
    }

    task "vllm" {

      lifecycle {
        hook    = "prestart"
        sidecar = true
      }

      driver = "docker"

      config {
        # Pinned, and not force-pulled. See note 4 in the header.
        force_pull = false
        image      = "vllm/vllm-openai:v0.27.1"
        ports      = ["vllm"]
        args       = ${VLLM_ARGS}
        # vLLM's engine uses shared memory between its processes; Docker's 64 MB
        # default shows up as a "Bus error" that looks like a model problem.
        shm_size   = 2000000000
        # Model weights survive a redeploy instead of being pulled again. The
        # directory is created by ansible/playbook-prepull-images.yml — Docker
        # would otherwise create it silently, which is the D-29 failure mode.
        volumes = [
          "/mnt/data/hf-cache:/root/.cache/huggingface",
        ]
      }

      env {
        HUGGING_FACE_HUB_TOKEN = "${HUGGINGFACE_TOKEN}"
        VLLM_API_KEY           = "${API_TOKEN}"
        HF_HOME                = "/root/.cache/huggingface"
      }

      resources {
        cores  = 2
        memory = 12000

        device "gpu" {
          count = 1
        }
      }
    }

    task "check_vllm_startup" {

      lifecycle {
        hook    = "prestart"
        sidecar = false
      }

      driver = "docker"

      config {
        force_pull = false
        image      = "python:3.12-slim-bullseye"
        command    = "bash"
        args       = ["local/get_models.sh"]
      }

      env {
        # [CAIOS] The allocation's own address, not the public hostname. See
        # note 3 in the header — this is what stops our self-signed CA from
        # killing the deployment before it starts.
        VLLM_ENDPOINT = "http://${NOMAD_ADDR_vllm}/v1/models"
        TOKEN         = "${API_TOKEN}"
      }

      resources {
        cpu    = 100
        memory = 300
      }

      template {
        data = <<-EOF
        #!/bin/bash

        export PYTHONUNBUFFERED=1
        pip install --quiet requests

        python -c '
        import os
        import time

        import requests

        VLLM_ENDPOINT = os.environ["VLLM_ENDPOINT"]
        TOKEN = os.environ["TOKEN"]

        headers = {
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        }

        attempts = 0
        delay = 2

        with requests.Session() as session:
            session.headers.update(headers)

            while True:
                # Loading a model takes minutes, so the endpoint refusing the
                # connection is the NORMAL state for a while. Upstream let any
                # exception escape, which on our cluster meant a TLS error took
                # the allocation down; catching it is what makes the wait a wait.
                try:
                    response = session.get(VLLM_ENDPOINT, timeout=10)
                except requests.exceptions.RequestException as e:
                    attempts += 1
                    print(f"Attempt {attempts} | not up yet: {type(e).__name__}")
                    time.sleep(delay)
                    continue

                if response.ok:
                    print(f"Success | Status code: {response.status_code}")
                    print(f"{response.text}")
                    exit(0)

                attempts += 1
                print(f"Attempt {attempts} | Status code: {response.status_code}")
                time.sleep(delay)
        '
        EOF
        destination = "local/get_models.sh"
      }
    }

    task "open-webui" {

      driver = "docker"

      config {
        force_pull = false
        image      = "ghcr.io/open-webui/open-webui:v0.11.0"
        ports      = ["ui"]
      }

      env {
        OPENAI_API_KEY      = "${API_TOKEN}"
        # For a "both" deployment PAPI substitutes the allocation's own address
        # here rather than the public vLLM hostname — patch 0010, and see note 3
        # in the header. For a standalone UI it stays the endpoint the user gave.
        OPENAI_API_BASE_URL = "${API_ENDPOINT}"
        WEBUI_AUTH          = true
        # Without a fixed secret, every restart invalidates existing sessions and
        # logs the demo out mid-walkthrough.
        WEBUI_SECRET_KEY    = "${API_TOKEN}"
        # [CAIOS] Nothing here serves Ollama. Left on, Open WebUI probes
        # host.docker.internal:11434 on every model listing: a DNS lookup that
        # cannot succeed, a delay on the first page a demo audience sees, and a
        # red ERROR line in the logs that has nothing to do with anything.
        ENABLE_OLLAMA_API   = false
        # [CAIOS] The model dropdown should contain the model, and nothing else.
        # Open WebUI ships an "arena-model" placeholder for blind A/B comparison
        # of several models; with one model deployed it compares it with itself.
        # A researcher opening a private LLM should not have to work out which of
        # two entries is the one they deployed.
        ENABLE_EVALUATION_ARENA_MODELS = false
      }

      resources {
        # Shares rather than dedicated cores: reserving a third core would empty
        # the MHz pool the helper tasks draw from and the job would not place.
        cpu    = 1200
        memory = 4000
      }
    }

    task "create-admin" {
      # Open WebUI cannot be given an admin from configuration, so the account has
      # to be claimed over HTTP. If this does not run, the first visitor to the
      # URL becomes the administrator.

      lifecycle {
        hook    = "poststart"
        sidecar = false
      }

      driver = "docker"

      config {
        force_pull = false
        image      = "python:3.12-slim-bullseye"
        command    = "bash"
        args       = ["local/create_admin.sh"]
      }

      env {
        # [CAIOS] Same reasoning as check_vllm_startup: the allocation's own
        # address, over plain HTTP, inside the node.
        OPEN_WEBUI_URL = "http://${NOMAD_ADDR_ui}"
        NAME           = "${OWNER_NAME}"
        EMAIL          = "${OPEN_WEBUI_USERNAME}"
        PASSWORD       = "${OPEN_WEBUI_PASSWORD}"
      }

      resources {
        cpu    = 100
        memory = 300
      }

      template {
        data = <<-EOF
        #!/bin/bash

        export PYTHONUNBUFFERED=1
        pip install --quiet requests

        python -c '
        import os
        import time

        import requests

        base_url = os.environ["OPEN_WEBUI_URL"]

        data = {
            "name": os.environ["NAME"],
            "email": os.environ["EMAIL"],
            "password": os.environ["PASSWORD"],
            "profile_image_url": "/user.png",
        }

        # Open WebUI takes a while to warm up, and it downloads an embedding
        # model on first boot, so early attempts are expected to fail.
        deadline = time.time() + 900
        while time.time() < deadline:
            try:
                r = requests.post(f"{base_url}/api/v1/auths/signup", json=data, timeout=10)
            except requests.exceptions.RequestException as e:
                print(f"not up yet: {type(e).__name__}")
                time.sleep(2)
                continue

            if r.ok:
                print(f"Admin created | Status: {r.status_code}")
                break

            # 400 here usually means the account already exists, which is a
            # success for our purposes — this task must be safe to re-run.
            if r.status_code == 400 and "already" in r.text.lower():
                print("Admin already exists")
                break

            print(f"Error: status code {r.status_code} | {r.text[:200]}")
            time.sleep(2)
        else:
            raise SystemExit("timed out waiting for Open WebUI to accept the admin signup")
        '
        EOF
        destination = "local/create_admin.sh"
      }
    }

  }
}
