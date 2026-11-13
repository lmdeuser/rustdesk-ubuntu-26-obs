#!/usr/bin/env bash
set -euo pipefail

readonly expected_fingerprint=C106E46DE7578257F4CD62C96AE35907289D3BDC
readonly repository=https://download.opensuse.org/repositories/home:/dwolfF:/rustdesk/xUbuntu_26.04
readonly repository_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)

if [[ $EUID -ne 0 ]]; then
    echo 'Run this installer as root.' >&2
    exit 1
fi
# shellcheck source=/dev/null
. /etc/os-release
if [[ ${ID:-} != ubuntu || ${VERSION_ID:-} != 26.04 ]]; then
    echo 'Only Ubuntu 26.04 is supported.' >&2
    exit 1
fi
if [[ $(dpkg --print-architecture) != amd64 ]]; then
    echo 'Only amd64 is supported by the current OBS project.' >&2
    exit 1
fi
for command in curl gpg apt-get systemctl; do
    command -v "$command" >/dev/null || { echo "Missing required command: $command" >&2; exit 1; }
done
for unit in rustdesk-autoupdate.service rustdesk-autoupdate.timer; do
    [[ -f $repository_dir/systemd/$unit ]] || { echo "Missing unit: $unit" >&2; exit 1; }
done

workdir=$(mktemp -d /var/cache/rustdesk-obs-install.XXXXXXXX)
trap 'rm -rf -- "$workdir"' EXIT
chmod 700 "$workdir"
export GNUPGHOME="$workdir/gnupg"
mkdir -m 700 "$GNUPGHOME"
# Verify publication and key before changing the system's APT configuration.
curl --fail --silent --show-error --location "$repository/Release" -o "$workdir/Release"
curl --fail --silent --show-error --location "$repository/Release.key" -o "$workdir/key.asc"
gpg --batch --with-colons --show-keys "$workdir/key.asc" > "$workdir/key-info"
key_count=$(awk -F: '$1 == "pub" {count++} END {print count+0}' "$workdir/key-info")
fingerprint=$(awk -F: '$1 == "fpr" {print $10; exit}' "$workdir/key-info")
if [[ $key_count != 1 || $fingerprint != "$expected_fingerprint" ]]; then
    echo 'OBS signing key fingerprint does not match.' >&2
    exit 1
fi
gpg --batch --yes --dearmor --output "$workdir/rustdesk-obs.gpg" "$workdir/key.asc"
install -d -m 0755 /etc/apt/keyrings
install -m 0644 "$workdir/rustdesk-obs.gpg" /etc/apt/keyrings/rustdesk-obs.gpg
printf 'deb [signed-by=/etc/apt/keyrings/rustdesk-obs.gpg] %s/ /\n' "$repository" > /etc/apt/sources.list.d/rustdesk-obs.list
export DEBIAN_FRONTEND=noninteractive
apt-get -o Dpkg::Lock::Timeout=120 update
apt-get -o Dpkg::Lock::Timeout=120 install -y rustdesk
install -m 0644 "$repository_dir/systemd/rustdesk-autoupdate.service" /etc/systemd/system/
install -m 0644 "$repository_dir/systemd/rustdesk-autoupdate.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now rustdesk-autoupdate.timer
