# Patch layers

Applied in this order by `scripts/apply-patches.sh`. Order is a contract:
each layer assumes the ones before it are present.

## susfs/ — hiding infrastructure
- `50_add_susfs_in_gki-android14-6.1.patch`, from the cloned susfs4ksu tree.
- Source: simonpunk/susfs4ksu directly (`SUSFS_REPO`/`SUSFS_BRANCH` in
  versions.env), the way WildKernels use it. sync.sh copies its
  `kernel_patches/{fs,include}` sources into the tree; apply-patches applies the
  `50_add_susfs` patch between `patches/susfs/fake-patch.sh prepare` and
  `restore`, which normalise two vendor-hook includes the patch's context
  expects to be absent.

## zeromount/ — mount backend
- `60_zeromount-android14-6.1.patch` — the VFS `getname()` redirect engine and
  the `/dev/zeromount` control device. Source: Super-Builders, by ZeroMount's
  own author.
- `fix-susfs-compat.sh` — reconciles susfs and zeromount, which touch
  overlapping code; run before the zeromount patch.
- The `70_ksu_safety-wksu` patch that ships beside 60_ is **not** used: it
  targets Wild_KSU's `kernel/supercalls.c` and an optional
  `SUS_KSTAT_REDIRECT` handler, neither of which exists in our KSU
  (pershoot/KernelSU-Next dev-susfs, susfs integrated in-tree under
  `kernel/supercall/`). It was skipped in the first build too.

Why ZeroMount over NoMount: NoMount hijacks a directory's inode ops and keeps the
redirect in the dcache, so it is lost when that dentry is evicted (reproduced
with `drop_caches`), and manipulating it can panic this kernel. ZeroMount
redirects the path string at `getname()`, before any dcache lookup, so eviction
does not affect it.

## vpnhide — built-in VPN hiding (delegated to upstream's integrator)
- Not vendored here. sync.sh clones okhsunrog/vpnhide at `VPNHIDE_REV`, and
  apply-patches.sh calls its own `builtin/scripts/apply.sh <common> android14-6.1`.
  That script copies the `security/vpnhide/` driver, vendors the shared logic +
  generated tables from `kmod/`, installs `include/linux/vpnhide.h`, wires
  `security/{Kconfig,Makefile}`, and applies the 13 per-version call-site patches
  (fs_namei, net_socket, ipv4/ipv6 addr/route/fib, dev_ioctl, rtnetlink, readdir,
  stat) with `patch -p1 --fuzz=3`.
- Enabled by `CONFIG_VPNHIDE=y` + `CONFIG_VPNHIDE_FS_HIDING=y` in
  `configs/husky.fragment`. Compiled in, not loaded as a `.ko` — the point of
  this build is to exercise that backend. The manager APK is built from the same
  commit.

## ksu/ — patch A (ours)
- `90_app_profile_manager_or_root.patch` — widens GET/SET_APP_PROFILE from
  only_manager to manager_or_root, the check every other policy command already
  carries. Verified to apply against KernelSU-Next `dev` with `git apply`.
