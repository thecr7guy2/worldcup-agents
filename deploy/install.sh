#!/usr/bin/env bash
#
# Render + install the World Cup Agents systemd timers.
#
#   deploy/install.sh                  install to /etc/systemd/system (uses sudo) + enable
#   deploy/install.sh --render DIR     just write the substituted units to DIR (no sudo)
#
# The units carry __REPO__ / __USER__ / __UV__ tokens; this script fills them from the
# current checkout, the invoking user, and the resolved `uv` path.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
RUN_USER="${SUDO_USER:-$(id -un)}"
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
