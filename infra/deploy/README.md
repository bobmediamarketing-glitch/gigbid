# Deploying GigBid on a VM

The whole stack (web, API, worker, MCP servers, GigSim, Postgres, Redis, Qdrant, Ollama) runs on one VM with
Docker, behind Caddy for automatic HTTPS. You need a Linux VM with **4 GB of RAM or more** and ports 80 and 443
reachable.

## 1. Get a VM (pick one)

| Provider | Cost | Notes |
|---|---|---|
| **Azure for Students** | free $100 credit, **no credit card**, renews yearly | Sign up with your university email. Create a *B2s* (2 vCPU / 4 GB) Ubuntu 24.04 VM |
| **DigitalOcean via the GitHub Student Developer Pack** | free credit for students | A 4 GB "Basic" droplet, Ubuntu 24.04 |
| **Oracle Cloud Always Free** | free indefinitely (card needed for verification) | *VM.Standard.A1.Flex* (ARM) with 2–4 OCPU / 12–24 GB, Ubuntu 24.04. Also add an ingress rule for TCP 80/443 in the VCN's Security List |
| Hetzner / any VPS | about €4–8 a month | CX22 or similar, Ubuntu 24.04 |

While creating it:
1. Choose **Ubuntu 24.04** (22.04 also works).
2. Add your **SSH public key**, or let the provider create a key pair and download it.
3. In the provider's network / firewall settings, **allow inbound TCP 22, 80 and 443**.

## 2. Run the setup script (about 10 minutes)

SSH in, using the address and username your provider shows (`ubuntu`, `azureuser` or `root`):
```bash
ssh ubuntu@<your-vm-ip>
```
Then:
```bash
git clone https://github.com/bobmediamarketing-glitch/gigbid.git && cd gigbid
```
```bash
GROQ_API_KEY=<your key> bash infra/deploy/setup_vm.sh
```

The script:
- installs Docker
- opens 80/443 on the VM's own firewall
- generates every secret into `infra/.env` (readable only by you, never committed)
- builds and starts the stack with HTTPS
- creates the **reviewer account** preloaded with the AI/ML persona, then queues a few jobs so the inbox has content

At the end it prints the public URL (`https://<ip>.sslip.io`, a free hostname that needs no DNS setup) and
the reviewer login. **Put the login only in the private Google Classroom comment.**

To use your own domain, point an A record at the VM, then run the script with `DOMAIN=gigbid.yourdomain.com`.

## 3. Keep it live until grades are released

* Every service has `restart: unless-stopped`, so a reboot or crash brings everything back by itself.
* To update after a new commit, run `git pull && bash infra/deploy/setup_vm.sh` (it keeps the secrets).
* To read logs: `docker compose -f infra/docker-compose.yml --profile tls logs -f api worker`
* To back up: `docker compose -f infra/docker-compose.yml exec postgres pg_dump -U gigbid gigbid > backup.sql`

If the VM has only 4 GB of RAM, don't pull the Ollama models (`--profile models`): the open profile on Groq
needs no local model memory. See [docs/RUNBOOK.md](../../docs/RUNBOOK.md) for troubleshooting.
