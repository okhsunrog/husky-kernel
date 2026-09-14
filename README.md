# husky-kernel

A reproducible custom kernel for the Pixel 8 Pro (`husky`), GKI android14-6.1.

Google's GKI source, plus four layers on top:

- **KernelSU-Next** — the root manager (kernel-based `su`, app profiles, modules).
- **SUSFS** — hiding infrastructure (path/mount/kstat/uname spoofing).
- **ZeroMount** — mountless module loading via VFS `getname()` redirection.
  Replaces NoMount, whose redirect is lost when the directory dentry is evicted
  from the dcache (and which can panic this kernel on `drop_caches`).
- **vpnhide (built-in)** — kernel-level VPN hiding, compiled in rather than
  loaded as an LKM.
- **Patch A** — lets root read and write KernelSU-Next app profiles, so tooling
  need not impersonate the manager.

Everything is pinned in [`versions.env`](versions.env); that file is the only
place an input version lives.

## Build

Toolchain comes with the source — nothing to install but `repo`, `git`, and a
bazel-capable host (all already present on the build machine). The AOSP prebuilt
clang arrives with `repo sync`; the host clang is not used for the kernel.

```bash
scripts/sync.sh          build/          # GKI + KSU-Next + SUSFS + vpnhide sources
scripts/apply-patches.sh build/          # SUSFS → ZeroMount → vpnhide → patch A
scripts/build.sh         build/          # bazel (kleaf), thin LTO → Image
```

See [docs/BUILDING.md](docs/BUILDING.md) for flashing and the details each
script leaves to the first real run.

## Layout

```
versions.env            every pinned version, and nothing else
patches/
  susfs/                50_add_susfs, 51_enhanced_susfs   (from Super-Builders)
  zeromount/            60_zeromount, 70_ksu_safety, fix-susfs-compat
  vpnhide/              one .c.patch per kernel source vpnhide hooks
  ksu/                  90_app_profile_manager_or_root    (patch A, ours)
scripts/                sync / apply-patches / build
docs/                   BUILDING, PATCHES
```

## Status

Scaffolding stage. The pins and patches are in place and patch A is verified to
apply against KernelSU-Next `dev`; the first full sync+build has not run yet.
