#!/bin/sh
set -eu

PYTHON_URL='https://github.com/astral-sh/python-build-standalone/releases/download/20250115/cpython-3.9.21%2B20250115-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz'
PYTHON_SHA256='523782aa11424af5248e0f2d4c677e6a24e2d3f34cc9df9a3b7c5efb0a2475a3'
LINPHONE_URL='https://download.linphone.org/releases/linphone-python/5.4/linux-x86_64/linphone-5.4.0.post12%2Bgit.6dde746d-cp39-cp39-linux_x86_64.whl'
LINPHONE_SHA256='418363a4e50d8f62835ba7193a98dfce2fcc276e05c922a91695c5a1e193fe20'
# SPDX publishes an immutable copy of the GPL text on GitHub, which is more
# reliably reachable from GitHub Actions than gnu.org.
GPL_URL='https://raw.githubusercontent.com/spdx/license-list-data/v3.28.0/text/GPL-3.0-only.txt'
GPL_SHA256='fb981668c18a279e285fc4d83fba1e836cc84dd4daa73c9697d3cfd2d8aca6e0'
ASSET='bticino-c100x-linphone-0.1.0-linux-amd64.tar.gz'

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM
mkdir -p "$WORK/package/bin" "$WORK/package/lib"

download() {
  curl -fsSL --retry 5 --retry-all-errors --connect-timeout 30 --max-time 900 "$1" -o "$2"
}

download "$PYTHON_URL" "$WORK/python.tar.gz"
printf '%s  %s\n' "$PYTHON_SHA256" "$WORK/python.tar.gz" | sha256sum -c -
tar -xzf "$WORK/python.tar.gz" -C "$WORK"
mv "$WORK/python" "$WORK/package/python"

download "$LINPHONE_URL" "$WORK/linphone.whl"
printf '%s  %s\n' "$LINPHONE_SHA256" "$WORK/linphone.whl" | sha256sum -c -
python3 -m zipfile -e "$WORK/linphone.whl" "$WORK/wheel"
cp -a "$WORK/wheel"/*.data/purelib/linphone "$WORK/package/lib/"

cp "$ROOT/runtime/helper.py" "$WORK/package/helper.py"
cp "$ROOT/runtime/bin/bticino-c100x-linphone" "$WORK/package/bin/"
cp "$ROOT/runtime/LICENSE" "$ROOT/runtime/README.md" "$WORK/package/"
download "$GPL_URL" "$WORK/package/COPYING.GPLv3"
printf '%s  %s\n' "$GPL_SHA256" "$WORK/package/COPYING.GPLv3" | sha256sum -c -
chmod 0755 "$WORK/package/bin/bticino-c100x-linphone" "$WORK/package/helper.py"
python3 "$ROOT/runtime/package.py" "$WORK/package" "$ROOT/$ASSET"
sha256sum "$ROOT/$ASSET" > "$ROOT/$ASSET.sha256"
