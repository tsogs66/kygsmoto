# KYGSMOTO on Proxmox LXC

Complete guide from creating the container through opening the app in a browser.

> Run `pct …` commands on the **Proxmox host** (`root@pve`).  
> Run `apt` / `docker` / `git` commands **inside** the LXC (`root@kygsmoto`).

---

## 1. Create the LXC (one-liner on PVE host)

Adjust CTID, template name, storage, and bridge to match your node:

```bash
pct create 210 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --hostname kygsmoto \
  --memory 2048 \
  --cores 2 \
  --swap 512 \
  --rootfs local-lvm:16 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --unprivileged 1 \
  --features nesting=1,keyctl=1 \
  --onboot 1 \
  --start 1
```

Notes:

- List templates: `pveam available | grep debian-12`
- Download if needed: `pveam download local debian-12-standard_12.7-1_amd64.tar.zst`
- `nesting=1,keyctl=1` is required for Docker inside an unprivileged LXC
- Change `210` if that CTID is already used (`pct list`)

---

## 2. Enter the container

From the **PVE host** shell (Datacenter → **pve** → **Shell**, or SSH to PVE):

```bash
pct enter 210
```

This logs you in as `root` without a Console password.

### Optional: set Console login password

Some Proxmox versions do **not** have `pct passwd`. Use:

```bash
# on PVE host
pct exec 210 -- passwd
```

Or inside the CT after `pct enter 210`:

```bash
passwd
```

Then in **Proxmox UI → 210 (kygsmoto) → Console**:

| Field | Value |
| --- | --- |
| Login | `root` |
| Password | whatever you set with `passwd` |

---

## 3. Install Docker + Git + Compose (inside LXC)

Debian Bookworm does **not** provide `docker-compose-v2` (Ubuntu-only package name). Use this:

```bash
apt update && apt install -y docker.io git curl \
  && systemctl enable --now docker \
  && mkdir -p /usr/local/lib/docker/cli-plugins \
  && curl -fsSL https://github.com/docker/compose/releases/download/v2.32.4/docker-compose-linux-x86_64 \
       -o /usr/local/lib/docker/cli-plugins/docker-compose \
  && chmod +x /usr/local/lib/docker/cli-plugins/docker-compose \
  && docker --version && docker compose version
```

Verify Docker works:

```bash
docker run --rm hello-world
```

If that fails with permission / cgroup errors, confirm the CT has `nesting=1` and `keyctl=1`:

```bash
# on PVE host
pct set 210 --features nesting=1,keyctl=1
pct reboot 210
```

---

## 4. Clone and start KYGSMOTO (inside LXC)

Use the feature branch that contains `Dockerfile` + `docker-compose.yml` (until merged to `main`):

```bash
cd ~ && rm -rf kygsmoto \
  && git clone -b cursor/kygsmoto-sales-inventory-9004 https://github.com/tsogs66/kygsmoto.git \
  && cd kygsmoto \
  && docker compose up -d --build
```

After merge to `main`, you can use:

```bash
git clone https://github.com/tsogs66/kygsmoto.git
cd kygsmoto
docker compose up -d --build
```

Check status:

```bash
docker compose ps
docker compose logs -f --tail=100
```

---

## 5. Open the app

Inside the LXC:

```bash
hostname -I
```

Then on any device on the same LAN:

```text
http://<lxc-ip>:8000
```

API docs: `http://<lxc-ip>:8000/docs`

### App login credentials

**There are none.** KYGSMOTO currently has no authentication — the UI opens directly.

Do not confuse:

| Prompt | What it is | Credentials |
| --- | --- | --- |
| `kygsmoto login:` (Proxmox Console) | Linux CT root shell | `root` + password from `passwd` |
| Browser `http://ip:8000` | KYGSMOTO web app | No login |

---

## 6. Import the KYGS Excel workbook (optional, one-off)

The app keeps its own database — the volume `kygsmoto_data` is the shop's record.
The workbook is **not** shipped inside the image, and nothing at runtime depends
on it. Import one only if you are seeding a fresh database from the old
spreadsheet.

The simplest route is the app itself:

```
Sales File Import  →  Upload .xlsm
```

To import from the command line instead, mount the workbook in and point the
script at it:

```bash
docker compose run --rm \
  -v "$PWD/KYGS APRIL 2025.xlsm:/tmp/kygs.xlsm:ro" \
  kygsmoto python scripts/import_kygs.py /tmp/kygs.xlsm
```

After the first import the spreadsheet is no longer needed. Back up the volume,
not the workbook:

```bash
docker run --rm -v kygsmoto_kygsmoto_data:/d -v "$PWD":/b alpine \
  cp /d/kygsmoto.db /b/kygsmoto-$(date +%F).db
```

## 7. Autoupdate from GitHub

Pull latest code and rebuild containers:

```bash
cd ~/kygsmoto
chmod +x deploy/autoupdate.sh
./deploy/autoupdate.sh --branch cursor/kygsmoto-sales-inventory-9004
# after merge to main:
# ./deploy/autoupdate.sh --branch main
```

Daily cron (03:00):

```bash
crontab -e
# add:
0 3 * * * /root/kygsmoto/deploy/autoupdate.sh --branch cursor/kygsmoto-sales-inventory-9004 >> /var/log/kygsmoto-autoupdate.log 2>&1
```

---

## 8. Useful maintenance commands

```bash
# inside LXC, in ~/kygsmoto
docker compose pull          # if using published images later
docker compose up -d --build # rebuild after git pull
./deploy/autoupdate.sh       # pull + rebuild in one step
docker compose down          # stop
docker compose logs -f       # follow logs

# on PVE host
pct status 210
pct shutdown 210
pct start 210
pct enter 210
```

---

## 9. Full copy-paste bootstrap (create already done)

If CT `210` already exists and you are inside it (`pct enter 210`):

```bash
apt update && apt install -y docker.io git curl \
  && systemctl enable --now docker \
  && mkdir -p /usr/local/lib/docker/cli-plugins \
  && curl -fsSL https://github.com/docker/compose/releases/download/v2.32.4/docker-compose-linux-x86_64 \
       -o /usr/local/lib/docker/cli-plugins/docker-compose \
  && chmod +x /usr/local/lib/docker/cli-plugins/docker-compose \
  && cd ~ && rm -rf kygsmoto \
  && git clone -b cursor/kygsmoto-sales-inventory-9004 https://github.com/tsogs66/kygsmoto.git \
  && cd kygsmoto \
  && docker compose up -d --build \
  && echo "Open http://$(hostname -I | awk '{print $1}'):8000"
```

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Unable to locate package docker-compose-v2` | Expected on Debian — install Compose plugin via `curl` (section 3) |
| `git: command not found` | `apt install -y git` |
| `Can't find a suitable configuration file` | Wrong branch or wrong directory — clone `-b cursor/kygsmoto-sales-inventory-9004` and `cd kygsmoto` |
| `pct passwd` unknown command | Use `pct exec 210 -- passwd` instead |
| `pct: command not found` | You are inside the CT — run `pct` only on `root@pve` |
| Docker fails in unprivileged CT | `pct set 210 --features nesting=1,keyctl=1` then reboot |
| Browser can’t connect | Check `docker compose ps`, firewall, and that you use the **LXC** IP not the PVE host IP |

Also see: [ANDROID.md](ANDROID.md) · [windows-start.bat](windows-start.bat) · [autoupdate.sh](autoupdate.sh) · [lxc-install.sh](lxc-install.sh)
