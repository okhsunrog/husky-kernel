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

## Left to the first real run
These depend on the exact synced tree and are pinned down on first build:
- **vpnhide source copy**: which translation units from `vpnhide/builtin` to
  drop into `common/` alongside the `.c.patch` grafts, and the Kconfig/Makefile
  entry to compile them in. Resolved from `vpnhide/builtin/build.py`.
- **defconfig fragment**: the `CONFIG_KSU*`, `CONFIG_KSU_SUSFS*`, and ZeroMount
  CONFIGs to enable, assembled the way Super-Builders' assemble-defconfig does.
- **ospatch pin**: versions.env tracks the nearest published GKI month; confirm
  the exact branch the device's 6.1.157 came from at sync time.

## First-build strategy
Bring the layers up incrementally, not all at once:
1. GKI + KernelSU-Next + SUSFS + **ZeroMount** only — build, flash, confirm it
   boots and that the ZeroMount redirect survives `drop_caches` (the NoMount
   failure that started this).
2. Add **vpnhide built-in** — confirm the backend works without the LKM.
3. Add **patch A** — confirm ksud reads/writes profiles as root.

A bootloop then points at the layer just added.

## Known blocker: SUSFS patches vs the real GKI tree

Super-Builders (unmaintained since April 2026) ships the SUSFS/ZeroMount kernel
patches, and they were generated against a GKI tree whose vendor hooks differ
from what android.googlesource.com actually publishes for android14-6.1-2025-12
(= 6.1.157, our pin). Concretely: `50_add_susfs`'s first `fs/namespace.c` hunk
inserts the SUSFS extern block right where stock has `#include
<trace/hooks/blk.h>`, so the anchor does not match and `patch -F5 --fuzz=5`
cannot place it. 8 of 9 hunks in that file apply; one does not.

This is not a version mismatch with the device (the pin is the device's exact
kernel) -- it is the patch being cut against a slightly different vendor set. It
is fixable by adapting the SUSFS patches to the published tree, hunk by hunk, in
the forks (okhsunrog/Super-Builders, okhsunrog/zeromount). That adaptation is
the next work item and is deliberately not rushed at the tail of a long session.

Options if the adaptation proves broad: take SUSFS from a maintained source
(WildKernels' own susfs patches, or simonpunk/susfs4ksu directly) and reconcile
ZeroMount against it -- weighed against NoMount (whose maintainer is active and
whose bug is now precisely localised) and OverlayFS+umount+susfs.
