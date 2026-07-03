# GCP VM Setup

Infrastructure-level setup for the VM that runs Dify + this OTel bridge.
Application deployment steps live in [RUNBOOK.md](RUNBOOK.md).

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

Do **not** create a firewall rule for `4317`/`4318`/`13133`. GCP firewalls
deny inbound traffic by default, so simply not opening these ports keeps
the Collector unreachable from the internet — even though
`examples/docker-compose/docker-compose.yaml` publishes them to the host
for local `curl`/debugging convenience.

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
