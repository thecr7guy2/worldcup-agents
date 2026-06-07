#!/usr/bin/env bash
#
# Render + install the World Cup Agents systemd timers.
#
#   deploy/install.sh                  install to /etc/systemd/system + enable
#   deploy/install.sh --render DIR     just write the substituted units to DIR
#
# Run it as YOUR normal user (NOT `sudo deploy/install.sh`) — it calls sudo only for the
# install steps that need root. Under sudo the whole script runs as root, so `uv` and $HOME
# resolve to root's (/root/.local/bin/uv, which doesn't exist) and the units come out broken.
#
# The units carry __REPO__ / __USER__ / __UV__ tokens; this script fills them from the
# current checkout, the invoking user, and the resolved `uv` path.
set -euo pipefail

# Guard the footgun: sudo from a normal account. (Logged in directly as root — no SUDO_USER
# — is fine: uv/HOME then legitimately resolve as root.)
if [[ ${EUID} -eq 0 && -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
  echo "ERROR: don't run this under sudo. Run it as ${SUDO_USER}; it elevates internally" >&2
  echo "       only where root is needed. (Under sudo, uv resolves to /root and the units" >&2
  echo "       would point at a uv that doesn't exist.)" >&2
  exit 1
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
RUN_USER="$(id -un)"
UV="$(command -v uv || true)"
[[ -z "$UV" ]] && UV="$HOME/.local/bin/uv"   # PATH is often stripped for service users

UNITS=(wc-tick.service wc-tick.timer wc-odds.service wc-odds.timer)

render() {
  local dest="$1"
  mkdir -p "$dest"
  for u in "${UNITS[@]}"; do
    sed -e "s#__REPO__#${REPO}#g" \
        -e "s#__USER__#${RUN_USER}#g" \
        -e "s#__UV__#${UV}#g" \
        "$HERE/$u" >"$dest/$u"
  done
  echo "Rendered ${#UNITS[@]} unit(s) to $dest (user=$RUN_USER, repo=$REPO, uv=$UV)"
}

if [[ "${1:-}" == "--render" ]]; then
  render "${2:?usage: install.sh --render DIR}"
  exit 0
fi

if [[ ! -x "$UV" ]]; then
  echo "ERROR: uv not found at '$UV'. Install uv or pass it on PATH." >&2
  exit 1
fi

TARGET=/etc/systemd/system
TMP="$(mktemp -d)"
render "$TMP"
echo "Installing to $TARGET ..."
sudo cp "$TMP"/wc-tick.service "$TMP"/wc-tick.timer \
        "$TMP"/wc-odds.service "$TMP"/wc-odds.timer "$TARGET/"
sudo systemctl daemon-reload
sudo systemctl enable --now wc-tick.timer wc-odds.timer
echo
echo "Done. Verify with:"
echo "  systemctl list-timers 'wc-*'"
echo "  journalctl -u wc-tick.service -n 20 --no-pager"
