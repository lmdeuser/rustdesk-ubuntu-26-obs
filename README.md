# RustDesk Ubuntu 26.04 LTS Packaging and OBS Distribution

Automated packaging scaffold, Open Build Service (OBS) remote build pipeline,
and APT client distribution for **RustDesk** targeting **Ubuntu 26.04 LTS
(`xUbuntu_26.04`, `amd64`)**.

Upstream `rustdesk/rustdesk` is treated strictly as read-only. All compilation
takes place inside OBS (`home:dwolfF:rustdesk:staging` before promotion to
`home:dwolfF:rustdesk`); no local compilation of RustDesk binaries is performed.

## Target Capabilities

- **Target platform:** Ubuntu 26.04 LTS (Resolute Raccoon), `amd64` only.
- **Native Wayland support:**
  - `scrap/wayland` screen capture via PipeWire (`libpipewire-0.3-dev`,
    `gstreamer1.0-pipewire`) and XDG Desktop Portals (`xdg-desktop-portal`).
  - Wayland keyboard shortcuts inhibit protocol generated via
    `wayland-protocols` (`keyboard-shortcuts-inhibit-unstable-v1`).
  - Unattended and login-screen DRM/KMS capture enabled via Cargo features
    `drm,drm-wake` and `libdrmtap` built with `-Dhelper=disabled -Degl=enabled`
    and installed under `/usr/lib/rustdesk/libdrmtap.so.0`.
- **Hardware video acceleration:**
  - `hwcodec` compiled with `RUSTDESK_SYSTEM_FFMPEG=1` against Ubuntu 26.04
    system FFmpeg 8 (`libavcodec62`, `libavformat62`, `libavutil`, `libva2`,
    `libvdpau1`, `libffmpeg-nvenc-dev`).

## Repository Layout

- `packaging/debian/` — Multi-tarball Debian `3.0 (quilt)` packaging
  (`control`, `rules`, `changelog`, `copyright`, `postinst`, `prerm`, `postrm`).
- `packaging/obs/` — OBS project metadata (`staging.xml`, `project.xml`,
  `prjconf`, `build.script`).
- `scripts/obs_publisher.py` — Upstream release watcher, source-set assembler,
  OBS staging uploader, build poller, production promoter, APT verifier, and
  packaging metadata Git sync tool.
- `scripts/retention.py` — Retains at most two marked local release source sets
  while protecting active builds and pruning stale artifacts in OBS checkouts.
- `scripts/install-client.sh` — Ubuntu 26.04 client bootstrapper that verifies
  the OBS repository signing key fingerprint, configures DEB822 APT sources,
  installs `rustdesk` with Wayland/VA-API runtime dependencies, and enables
  `rustdesk-autoupdate.timer`.
- `scripts/inspect_upstream.py`, `scripts/archive_source.py`,
  `scripts/fetch_pub_archives.py`, `scripts/fetch_pub_git.py`,
  `scripts/prepare_pub_cache.py` — Upstream inspection and offline cache helpers.
- `scripts/check_public_tree.py` — Pre-commit check rejecting secrets, private
  addresses, local home paths, and binary/tarball artifacts in Git.
- `systemd/` — Service and timer units for RustDesk daemon
  (`rustdesk.service`), client APT auto-updates
  (`rustdesk-autoupdate.service`, `rustdesk-autoupdate.timer`), and runner
  release watching (`rustdesk-obs-watcher.service`,
  `rustdesk-obs-watcher.timer`).
- `tests/` — Standard-library unit tests covering upstream inspection, source
  archiving, offline cache verification, retention pruning, and OBS publisher
  orchestration.

## Client Installation (Ubuntu 26.04 LTS, `amd64`)

Run as root on an Ubuntu 26.04 `amd64` workstation or desktop:

```bash
sudo ./scripts/install-client.sh
```

The installer validates `/etc/os-release` (`ubuntu` `26.04`) and architecture
(`amd64`), verifies the OBS repository key fingerprint
`C106E46DE7578257F4CD62C96AE35907289D3BDC`, installs the keyring into
`/usr/share/keyrings/rustdesk-obs.gpg`, configures
`/etc/apt/sources.list.d/rustdesk-obs.sources`, installs `rustdesk` together
with PipeWire/portal/VA-API runtime packages, and enables
`rustdesk-autoupdate.timer`.

## Automation Runner Usage

Always use a disk-backed temporary directory (`TMPDIR`), never `/tmp`:

```bash
export TMPDIR=/var/tmp/rustdesk/tmp
mkdir -p "$TMPDIR"

# Check for a new upstream RustDesk release
python3 -B scripts/obs_publisher.py --work-root /var/tmp/rustdesk --check-only

# Run full watch -> OBS staging build -> APT promotion -> retention pipeline
python3 -B scripts/obs_publisher.py --work-root /var/tmp/rustdesk --sync-git

# Run unit tests and public repository hygiene check
TMPDIR=/var/tmp/rustdesk/tests python3 -B -m unittest discover -s tests -v
python3 -B scripts/check_public_tree.py
```

References:
- [RustDesk upstream repository](https://github.com/rustdesk/rustdesk)
- [RustDesk Linux documentation](https://rustdesk.com/docs/en/client/linux/)
- [Open Build Service user guide](https://openbuildservice.org/help/manuals/obs-user-guide/cha-obs-architecture)
