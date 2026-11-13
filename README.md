# RustDesk Ubuntu OBS packaging investigation

This repository is an initial packaging project. It does not yet build,
publish, install, or update RustDesk. It is not production-ready.

Run `python3 scripts/inspect_upstream.py` to inspect the latest official GitHub
release and its Cargo features. Run `python3 -m unittest discover -s tests`
for the local tests. No local compilation is involved.

`scripts/retention.py` can preview or remove old, explicitly marked local
source sets. It is not connected to a publisher and does not prune OBS
revision history. Use an absolute dedicated cache path; the default is a dry
run, and `--apply` removes marked version directories beyond the newest two.
Only use it when no other process is writing those source sets.

## Open engineering work

The requested top-level `wayland` Cargo feature is absent in RustDesk 1.5.3.
The root manifest instead enables `scrap/wayland` through its dependency on
`scrap`; this is not proof of complete runtime support. Upstream Linux
documentation describes restrictions on Wayland and the login screen. Hardware encoding, decoding, DMA-BUF, portal integration, and login
screen access must be independently implemented or verified for each target
before any support claim. A system service cannot assume a user's Wayland or
D-Bus session variables are available to root.

The official release source archive does not include Git submodule contents.
A reproducible OBS source bundle must include the exact submodule revisions and
all required offline dependencies, and must comply with their licenses. An OBS
package's revision history is separate from its current source file list;
removing old files does not prove historical source storage was removed.

The OBS projects `home:dwolfF:rustdesk` and
`home:dwolfF:rustdesk:staging` exist with publication disabled. Signing,
GitHub synchronization, and the runner have not yet been verified. Do not
enable an unattended publisher or installer until these prerequisites and the
upstream build and runtime behavior are verified.

References: [RustDesk 1.5.3 manifest](https://github.com/rustdesk/rustdesk/blob/1.5.3/Cargo.toml),
[RustDesk Linux documentation](https://rustdesk.com/docs/en/client/linux/),
and [OBS architecture](https://openbuildservice.org/help/manuals/obs-user-guide/cha-obs-architecture).
