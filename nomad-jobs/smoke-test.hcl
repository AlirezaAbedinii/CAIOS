/*
CAIOS Stage 1 gate: prove a job can be scheduled AND reached over HTTPS at its
own subdomain, before PAPI exists to blame.

  # NOTE the value: "deployments.<ip>.sslip.io", WITHOUT the "pacs-" prefix.
  # The service tag below prepends ${meta.domain}- itself (meta.domain is "pacs"),
  # so including it here produces smoke.pacs-pacs-deployments... and a 404 from
  # Traefik. This must match lb.domain in configs/papi/main.yaml exactly.
  export BASE_DOMAIN=deployments.<CAIOS_EDGE_IP>.sslip.io

  sed "s|BASE_DOMAIN_PLACEHOLDER|$BASE_DOMAIN|" nomad-jobs/smoke-test.hcl \
    | nomad job run -

Then open:  https://smoke.pacs-$BASE_DOMAIN

This job deliberately mirrors the constraints in PAPI's own templates
(etc/modules/nomad.hcl). If this job schedules and answers, a real deployment
will too — and if it does not, the failure is in the cluster, not in PAPI.
Debugging PAPI on top of a broken ingress is the most reliable way to lose
three days.

Clean up:  nomad job stop -purge -namespace caios caios-smoke-test
*/

job "caios-smoke-test" {
  namespace = "caios"
  type      = "service"
  # Must be "global". Every PAPI job template hardcodes it, and ai4-ansible's
  # default of "ai4os" would make this job unschedulable in a way that reads as
  # "no nodes available".
  region = "global"

  # ---- The three constraints every PAPI deployment carries. ----------------

  # Set to "ready" only by ai4-nomad_tests. Ships as "test" from Ansible.
  # This is the single most common reason a deployment queues forever.
  constraint {
    attribute = "${meta.status}"
    operator  = "regexp"
    value     = "ready"
  }

  # Keeps user workloads off the Traefik node and the servers.
  constraint {
    attribute = "${meta.type}"
    operator  = "="
    value     = "compute"
  }

  # Nodes only serve namespaces they are tagged with.
  constraint {
    attribute = "${meta.namespace}"
    operator  = "regexp"
    value     = "caios"
  }

  # Prefer a CPU node so the smoke test never displaces GPU work.
  affinity {
    attribute = "${meta.tags}"
    operator  = "regexp"
    value     = "cpu"
    weight    = 100
  }

  reschedule {
    attempts  = 0
    unlimited = false
  }

  group "usergroup" {

    network {
      port "ui" {
        to = 80
      }
    }

    # Traefik discovers this through Consul and routes on the Host header.
    # Note the hostname shape: <name>.<meta.domain>-<base domain>. The join
    # between meta.domain and the base domain is a HYPHEN, not a dot — so the
    # wildcard certificate must cover *.pacs-deployments.<ip>.sslip.io.
    service {
      name = "caios-smoke-test-ui"
      port = "ui"
      tags = [
        "traefik.enable=true",
        "traefik.http.routers.caios-smoke-test.tls=true",
        "traefik.http.routers.caios-smoke-test.rule=Host(`smoke.${meta.domain}-BASE_DOMAIN_PLACEHOLDER`)",
      ]
    }

    task "server" {
      driver = "docker"

      config {
        image = "nginxdemos/hello:plain-text"
        ports = ["ui"]
      }

      resources {
        cpu    = 100
        memory = 128
      }
    }
  }
}
