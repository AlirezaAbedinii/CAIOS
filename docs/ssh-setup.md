# SSH access for the cluster

Ansible runs from `caios_server` and needs to reach the other four nodes without
a password. This is the one step nobody else can do for you, because it needs a
credential that only you currently hold.

Ten minutes, once.

---

## Why it cannot be done from here

`caios_server` has no private key — only `~/.ssh/authorized_keys`, which is the
list of keys allowed *in*. It holds two entries, both yours
(`macbookpro@2arian3` and `alireza.abedini78@…`).

So this node can accept your connections but cannot initiate any of its own. The
only thing that can currently prove identity to the other four nodes is the
private key on your laptop.

---

## What already exists

A dedicated cluster keypair has been generated here:

```
~/.ssh/caios_cluster        private — stays on this node, never leaves it
~/.ssh/caios_cluster.pub    public  — this is what goes on the other nodes
```

The public half:

```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMrpt3N+WgLpGTTzkOy7exfF8OzqlW1bdwWEgPG3RU9J caios-cluster-20260812
```

Fingerprint `SHA256:nPSwaYbyEj7G+CO3A5b6E9uDG80ucu3ZcOPDiLoHy6A`.

**Why a separate key rather than copying yours here:** your personal key opens
every machine you have access to, including things unrelated to this project.
Putting it on a shared node means anyone with root there — or anyone who later
gets a shell there — inherits all of that. A dedicated key is scoped to this
cluster and can be revoked by deleting four lines, without touching your own
access.

---

## Option A — agent forwarding (recommended)

Your laptop keeps the private key; it is *used* remotely without being *copied*
remotely. Nothing sensitive is written to any node.

**Step 1 — on your laptop**, make sure the key is loaded:

```bash
ssh-add -l
```

If it says "no identities", add it (adjust the filename):

```bash
ssh-add ~/.ssh/id_rsa
```

**Step 2 — connect with forwarding on** (note the `-A`). If you normally hop
through the jumpserver, add `-A` to both hops:

```bash
ssh -A ubuntu@192.168.104.181
```

**Step 3 — on `caios_server`, confirm the agent arrived:**

```bash
ssh-add -l
```

It should list your key. If it says "Could not open a connection", forwarding did
not happen — see Option B.

**Step 4 — install the cluster key on the other four nodes:**

```bash
for ip in 192.168.104.105 192.168.104.20 192.168.104.145 192.168.104.7; do
  ssh-copy-id -i ~/.ssh/caios_cluster.pub -o StrictHostKeyChecking=accept-new ubuntu@$ip
done
```

`ssh-copy-id` appends the key to each node's `authorized_keys`. It is safe to run
twice — it will not duplicate an entry.

**Step 5 — verify** (this is the real test; run it *without* the agent if you
can, to prove the cluster key works on its own):

```bash
bash /mnt/CAIOS/scripts/check-ssh.sh
```

---

## Option A-Windows — `ssh-copy-id` does not exist on Windows

Windows ships OpenSSH's client (`ssh`, `ssh-keygen`) but **not `ssh-copy-id`** —
it is a shell script, and there is no `sh` to run it. `'ssh-copy-id' is not
recognized as an internal or external command` is what that looks like.

Do the same thing by hand. From **PowerShell or cmd on your laptop**, one line
per node — this appends the cluster key and removes duplicates, so it is safe to
run twice:

```
ssh ubuntu@192.168.104.188 "mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMrpt3N+WgLpGTTzkOy7exfF8OzqlW1bdwWEgPG3RU9J caios-cluster-20260812' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && sort -u -o ~/.ssh/authorized_keys ~/.ssh/authorized_keys"
```

The quoting matters: **double** quotes on the outside for Windows, **single**
quotes around the key for the remote shell. Swapping them breaks it.

If your laptop cannot reach `192.168.104.x` directly, run the same line from the
jumpserver, or use the OpenStack console in Horizon — that gives a shell on the
instance without SSH at all.

Then verify from `caios_server`:

```bash
bash /mnt/CAIOS/scripts/check-ssh.sh
```

---

## Option B — if agent forwarding is unavailable

Some jumpserver configurations disable it. In that case, install the public key
from your laptop instead.

**On your laptop**, paste the public key line into each node. Run this four
times, once per address:

```bash
ssh ubuntu@192.168.104.105 'mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMrpt3N+WgLpGTTzkOy7exfF8OzqlW1bdwWEgPG3RU9J caios-cluster-20260812" >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && sort -u -o ~/.ssh/authorized_keys ~/.ssh/authorized_keys'
```

Then repeat for `192.168.104.20`, `192.168.104.145`, `192.168.104.7`.

The `sort -u` at the end removes duplicates if you run it more than once.

If your laptop cannot reach those addresses directly either, the same command
works from the jumpserver — or use the OpenStack console in Horizon, which gives
a root shell on each instance without needing SSH at all.

Then verify from `caios_server`:

```bash
bash /mnt/CAIOS/scripts/check-ssh.sh
```

---

## What "verified" means

`scripts/check-ssh.sh` connects to each of the four nodes using **only** the
cluster key, with agent forwarding and password authentication disabled, so a
pass genuinely means Ansible will work unattended. It also reports each node's
disks, since that is the other Stage 1 prerequisite.

---

## After it works

Nothing else to configure. `ansible/ansible.cfg` already points at the inventory,
and the inventory addresses the nodes directly — no `ProxyJump`, because
`caios_server` is on the same subnet.

Confirm Ansible agrees:

```bash
cd /mnt/CAIOS/ansible && ansible all -m ping
```

Five `SUCCESS` lines means Stage 1 can start.

---

## Revoking access later

Delete the `caios-cluster-…` line from `~/.ssh/authorized_keys` on each node.
Your own access is unaffected, because it uses a different key.
