# GCP VM Setup

Infrastructure-level setup for the VM that runs Dify + this OTel bridge.
Application deployment steps live in [RUNBOOK.md](RUNBOOK.md).

> This guide covers **Google Cloud (GCE)**, the environment the bridge was
> tested on. GCP is not required — the stack is plain Docker Compose and runs on
> any cloud or on-prem host. On another provider, use this as a reference for
> sizing and firewall rules and substitute your platform's provisioning
> commands; the application deployment in [RUNBOOK.md](RUNBOOK.md) is
> provider-agnostic.

## VM specs

- Machine type: `e2-standard-4` (4 vCPU, 16 GB RAM) — Dify's own minimum
  recommendation for a Docker Compose self-host.
- Disk: 50 GB (pd-balanced or pd-ssd).
- Image: Ubuntu 22.04 LTS.
- Region/zone: `<REGION>`/`<ZONE>` — pick based on your org's standard location.

```bash
gcloud compute instances create <INSTANCE_NAME> \
  --zone=<ZONE> \
  --machine-type=e2-standard-4 \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=50GB \
  --boot-disk-type=pd-balanced
```

## Firewall rules

| Port(s)              | Exposure                  | Why |
|-----------------------|---------------------------|-----|
| `22` (SSH)             | Restrict to admin IP(s)  | VM access. |
| `80`, `443`            | Public (`0.0.0.0/0`)     | Dify web/nginx (HTTP/HTTPS). |
| `4317`, `4318`, `13133`| **Not exposed externally**| OTel Collector (gRPC, HTTP, health check). Only needed for container-to-container traffic on `dify-otel-net`; do not create a GCP firewall rule allowing external ingress to these ports. |
| `8088`                 | **Not exposed externally by default** | Local test port for the Dify workflow telemetry exporter. If you make this a real API entry point, put it behind your normal HTTPS/reverse-proxy/auth controls instead of opening it directly. |

```bash
gcloud compute firewall-rules create allow-http-https \
  --allow=tcp:80,tcp:443 \
  --target-tags=<VM_TAG> \
  --source-ranges=0.0.0.0/0

gcloud compute firewall-rules create allow-ssh-admin \
  --allow=tcp:22 \
  --target-tags=<VM_TAG> \
  --source-ranges=<ADMIN_IP>/32
```

Do **not** create a firewall rule for `4317`/`4318`/`13133` or `8088`. GCP firewalls
deny inbound traffic by default, so simply not opening these ports keeps
the Collector and workflow exporter unreachable from the internet — even
though the compose files publish them to the host for local `curl`/debugging
convenience.

## Install Docker, Compose, and git

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg git

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

sudo usermod -aG docker $USER
```

Log out/in (or `newgrp docker`) for the group change to take effect, then
verify:

```bash
docker --version
docker compose version
git --version
```

Once this is done, continue with [RUNBOOK.md](RUNBOOK.md) step 3 (Deploy).
