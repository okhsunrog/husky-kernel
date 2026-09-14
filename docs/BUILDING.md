# Building husky-kernel

## Prerequisites (already on the build machine)
- `repo`, `git`, bazel-capable host, ~100+ GB free.
- No toolchain to install: the AOSP prebuilt clang comes down with `repo sync`.

## Steps
```bash
scripts/sync.sh          build/
scripts/apply-patches.sh build/
scripts/build.sh         build/
```
Output: `build/bazel-bin/common/kernel_aarch64/Image`.

## Flashing
Package the `Image` with AnyKernel3 into a flashable zip, or repack the boot
image. Flash via the KernelSU-Next / kernelflasher path already on the device.
Keep the current boot image to restore on a bootloop.

## Incremental strategy (a bootloop points at the layer just added)
1. GKI + KernelSU-Next + SUSFS + **ZeroMount** — **done**. Built, flashed, boots;
   root works (`context=u:r:ksu:s0`), `/dev/zeromount` present, susfs active in
   dmesg, and `drop_caches=2` does **not** panic (the NoMount failure that
   started this is gone).
2. **vpnhide built-in** — wired: `apply-patches.sh` delegates to vpnhide's own
   `builtin/scripts/apply.sh`, and `configs/husky.fragment` sets
   `CONFIG_VPNHIDE=y` + `CONFIG_VPNHIDE_FS_HIDING=y`. Rebuild + flash, then
   confirm the backend hides a VPN interface without the LKM loaded.
3. **patch A** — `patches/ksu/90_app_profile_manager_or_root.patch`, applied by
   apply-patches with `git apply`. Confirm ksud reads/writes app profiles as root.

## Notes settled during the first builds
- **SUSFS source**: taken from simonpunk/susfs4ksu directly (not Super-Builders,
  which is unmaintained). Its `50_add_susfs` is cut against a GKI without two
  vendor-hook includes present in android14-6.1-2025-12; `patches/susfs/
  fake-patch.sh` removes them before the patch and restores them after. This is
  how WildKernels apply it, and it builds and boots.
- **vpnhide integration**: not hand-vendored — delegated to the pinned clone's
  `builtin/scripts/apply.sh`, the upstream-canonical integrator. See
  `docs/PATCHES.md`.
- **GKI pin**: the monthly branches (`android14-6.1-YYYY-MM`) are empty stubs at
  their tips; `android14-6.1-2025-12` carries the real 6.1.157 tree, the device's
  kernel. See versions.env.
