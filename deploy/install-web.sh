#!/usr/bin/env bash
#
# Render + install the systemd units for the showcase site (API + Next.js web).
#
#   deploy/install-web.sh                  install to /etc/systemd/system + enable
#   deploy/install-web.sh --render DIR     just write the substituted units to DIR
#
# Run it as YOUR normal user (NOT `sudo deploy/install-web.sh`) — it elevates with sudo
# internally only where root is needed. Under sudo, `uv`/`node`/$HOME resolve to root's and
# the rendered units would point at binaries that do not exist.
#
# Prerequisites on the server (one-time): Node 20+ and the production build:
#   cd web && npm ci && npm run build
#
# The units carry __REPO__ / __USER__ / __UV__ / __NPM__ / __NODE_DIR__ tokens; this script
# fills them from the current checkout, the invoking user, and the resolved tool paths.
set -euo pipefail

if [[ ${EUID} -eq 0 && -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
  echo "ERROR: don't run this under sudo. Run it as ${SUDO_USER}; it elevates internally" >&2
  echo "       only where root is needed." >&2
  exit 1
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
RUN_USER="$(id -un)"

UV="$(command -v uv || true)"; [[ -z "$UV" ]] && UV="$HOME/.local/bin/uv"
NPM="$(command -v npm || true)"; [[ -z "$NPM" ]] && NPM="$HOME/.local/bin/npm"
NODE="$(command -v node || true)"; [[ -z "$NODE" ]] && NODE="$HOME/.local/bin/node"
NODE_DIR="$(dirname "$NPM")"

UNITS=(wc-api.service wc-web.service)

render() {
  local dest="$1"
  mkdir -p "$dest"
  for u in "${UNITS[@]}"; do
    sed -e "s#__REPO__#${REPO}#g" \
        -e "s#__USER__#${RUN_USER}#g" \
        -e "s#__UV__#${UV}#g" \
        -e "s#__NPM__#${NPM}#g" \
        -e "s#__NODE_DIR__#${NODE_DIR}#g" \
        "$HERE/$u" >"$dest/$u"
  done
  echo "Rendered ${#UNITS[@]} unit(s) to $dest"
  echo "  user=$RUN_USER repo=$REPO"
  echo "  uv=$UV npm=$NPM node_dir=$NODE_DIR"
}

if [[ "${1:-}" == "--render" ]]; then
  render "${2:?usage: install-web.sh --render DIR}"
  exit 0
fi

[[ -x "$UV" ]]  || { echo "ERROR: uv not found at '$UV'." >&2; exit 1; }
[[ -x "$NPM" ]] || { echo "ERROR: npm not found at '$NPM'. Install Node 20+." >&2; exit 1; }
[[ -d "$REPO/web/.next" ]] || {
  echo "ERROR: $REPO/web/.next missing. Build first: (cd web && npm ci && npm run build)" >&2
  exit 1
}

TARGET=/etc/systemd/system
TMP="$(mktemp -d)"
render "$TMP"
echo "Installing to $TARGET ..."
sudo cp "$TMP"/wc-api.service "$TMP"/wc-web.service "$TARGET/"
sudo systemctl daemon-reload
sudo systemctl enable --now wc-api.service wc-web.service
echo
echo "Done. The site is on http://<server-ip>:3000  (API stays private on 127.0.0.1:8001)."
echo "Verify with:"
echo "  systemctl status wc-api.service wc-web.service --no-pager"
echo "  curl -s localhost:8001/api/health"
echo "  journalctl -u wc-web.service -n 20 --no-pager"
