# husky-kernel

Personal Pixel 8 Pro kernel: GKI android14-6.1, KernelSU-Next, SUSFS,
ZeroMount VFS driver and vpnhide built-in. The integration follows the
WildKernels approach; the GKI source and every component are pinned explicitly.

The driver, manager APK and `ksud` come from one commit of
[`okhsunrog/KernelSU-Next`, `dev-susfs`](https://github.com/okhsunrog/KernelSU-Next/tree/dev-susfs).
That branch follows `pershoot/dev-susfs`, with four local changes:
working dependency URLs, root access to app profiles, JSON profile CLI, and
support for larger signing certificates without growing the kernel stack.
There is no manager-UID impersonation in the CLI.

## Build

Requires `uv`, Git, AOSP `repo`, Rust with `cargo-ndk` and the Android arm64
target, Android SDK/NDKs and JDK 21. Host paths and public manager identity are
in `versions.env`; AOSP project revisions are in `manifests/aosp.xml`.

```sh
uv sync --locked
uv run scripts/forge.py adopt build
uv run scripts/forge.py sync build
uv run scripts/forge.py release build
```

`adopt` preserves old KSU sources and tracked kernel/Kleaf edits before marking
the build tree as disposable. Keep development work in separate repositories.
Run `sync` only when setting up or deliberately changing pins. Ordinary release
builds do not advance branches or invoke remote setup scripts.

The release directory contains the kernel Image, device-restricted AnyKernel3
ZIP, signed spoofed manager APK, `ksud`, vpnhide built-in companion ZIP, actual
kernel configuration, source pins and SHA-256 checksums. Building never flashes
or reboots a device.

See [MAINTENANCE](docs/MAINTENANCE.md) for the update workflow and ownership of changes,
and [BUILDING](docs/BUILDING.md) for installation, recovery and updating, and
[PATCHES](docs/PATCHES.md) for layer ownership. Cheap recipe regression checks
run in CI; kernel builds and hardware verification run locally.

## License

Original build tooling and documentation in this repository are available under
the [MIT License](LICENSE). Third-party code and patches retain their respective
upstream licenses. This does not relicense Linux, KernelSU-Next, SUSFS, ZeroMount,
vpnhide or AnyKernel3, or the kernel binaries built from them.
