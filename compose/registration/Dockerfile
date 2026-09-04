# CAIOS registration approvals. ~300 lines of Python and four dependencies.
#
# Built rather than pip-installing at start: the platform is required to demo
# with the internet unplugged, so a container that fetches its own dependencies
# at boot is a container that fails on the day it matters most.
FROM python:3.12-slim

WORKDIR /srv

# Our own CA, so the service can verify Keycloak's certificate when
# CAIOS_SCHEME is https. Same approach as PAPI: append to the system bundle
# rather than replacing it, and point Python's requests/httpx at that bundle
# because they use certifi and not the system store.
#
# The file is mounted at run time, so this only prepares the machinery.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# 0.0.0.0 INSIDE the container, which is required for a port mapping to reach
# it. What keeps this off the public IP is the mapping itself:
# docker-compose.yml publishes it as 127.0.0.1:8090, so Caddy on the host is the
# only thing that can reach it — the same arrangement as PAPI.
CMD ["sh", "-c", "update-ca-certificates >/dev/null 2>&1 || true; exec uvicorn app:app --host 0.0.0.0 --port 8090"]
