# Project Instructions

- Upstream `rustdesk/rustdesk` is strictly read-only. Never push to or modify upstream repositories.
- Compile RustDesk exclusively in Open Build Service (`home:dwolfF:rustdesk:staging` before promotion to `home:dwolfF:rustdesk`). Never compile RustDesk binaries or Flutter/Rust/C/C++ targets locally on developer workstations or runners.
- Target exclusively **Ubuntu 26.04 LTS (`xUbuntu_26.04`, `amd64`)** with:
  - Native Wayland support (`scrap/wayland` + PipeWire/GStreamer/XDG desktop portals + Wayland shortcuts inhibit + `libdrmtap` DRM/KMS via `--features drm,drm-wake`).
  - Hardware video acceleration (`hwcodec` linked against Ubuntu 26.04 system FFmpeg 8 / VA-API / VDPAU / NVENC headers).
- Never use `/tmp` for temporary build caches, archives, or tests. Always use a dedicated disk-backed `TMPDIR` (e.g. `/var/tmp/rustdesk`).
- Never commit secrets, credentials, private IP addresses, local usernames, local hostnames, `.deb`/`.dsc`/`.tar.*` build artifacts, or local runner state to Git. Always run `scripts/check_public_tree.py` before committing or pushing.
- Keep all repository files, scripts, systemd units, packaging metadata, comments, and documentation strictly in English.
- Keep `home:dwolfF:rustdesk` and `home:dwolfF:rustdesk:staging` separate. Only promote packages that succeed cleanly in staging and pass artifact verification.
- Enforce source-set retention (`scripts/retention.py`) keeping at most two local marked release directories while protecting active builds and keeping OBS working trees free of stale tarballs.
