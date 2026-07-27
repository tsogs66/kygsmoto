#!/usr/bin/env bash
# Create a Proxmox LXC ready for KYGSMOTO (Docker + nesting).
# Run on the Proxmox HOST (root@pve), not inside a container.
#
# Usage:
#   ./deploy/create-lxc.sh              # defaults: CTID 210, DHCP
#   CTID=211 STORAGE=local-lvm BRIDGE=vmbr0 ./deploy/create-lxc.sh
#   ./deploy/create-lxc.sh --start-only # skip create, print enter/bootstrap hints
set -euo pipefail

CTID="${CTID:-210}"
HOSTNAME="${HOSTNAME:-kygsmoto}"
MEMORY="${MEMORY:-2048}"
CORES="${CORES:-2}"
DISK="${DISK:-16}"
STORAGE="${STORAGE:-local-lvm}"
BRIDGE="${BRIDGE:-vmbr0}"
TEMPLATE="${TEMPLATE:-local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst}"
IPCONFIG="${IPCONFIG:-ip=dhcp}"

if ! command -v pct >/dev/null 2>&1; then
  echo "ERROR: pct not found. Run this on the Proxmox host (root@pve)." >&2
  exit 1
fi

if [[ "${1:-}" == "--start-only" ]]; then
  pct start "$CTID" || true
else
  if pct status "$CTID" >/dev/null 2>&1; then
    echo "CT $CTID already exists. Skipping create."
  else
    echo "==> Creating CT $CTID ($HOSTNAME)"
    pct create "$CTID" "$TEMPLATE" \
      --hostname "$HOSTNAME" \
      --memory "$MEMORY" \
      --cores "$CORES" \
      --swap 512 \
      --rootfs "${STORAGE}:${DISK}" \
      --net0 "name=eth0,bridge=${BRIDGE},${IPCONFIG}" \
      --unprivileged 1 \
      --features nesting=1,keyctl=1 \
      --onboot 1 \
      --start 1
  fi
fi

cat <<EOF

==> CT $CTID ready.

Enter shell:
  pct enter $CTID

Set Console password (if needed; pct passwd may not exist on older PVE):
  pct exec $CTID -- passwd

Inside the CT, bootstrap KYGSMOTO:
  apt update && apt install -y docker.io git curl \\
    && systemctl enable --now docker \\
    && mkdir -p /usr/local/lib/docker/cli-plugins \\
    && curl -fsSL https://github.com/docker/compose/releases/download/v2.32.4/docker-compose-linux-x86_64 \\
         -o /usr/local/lib/docker/cli-plugins/docker-compose \\
    && chmod +x /usr/local/lib/docker/cli-plugins/docker-compose \\
    && cd ~ && rm -rf kygsmoto \\
    && git clone -b cursor/kygsmoto-sales-inventory-9004 https://github.com/tsogs66/kygsmoto.git \\
    && cd kygsmoto \\
    && docker compose up -d --build \\
    && echo "Open http://\$(hostname -I | awk '{print \$1}'):8000"

Full docs: deploy/PROXMOX.md
EOF
