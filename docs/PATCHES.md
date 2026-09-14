# Patch layers

Applied in this order by `scripts/apply-patches.sh`. Order is a contract:
each layer assumes the ones before it are present.

## susfs/ — hiding infrastructure
- `50_add_susfs_in_gki-android14-6.1.patch`, `51_enhanced_susfs-android14-6.1.patch`
- Source: Super-Builders (which vendors simonpunk/susfs4ksu). Pinned by
  `SUSFS_REV` in versions.env; the source files these patches expect are copied
  in by sync.sh.

## zeromount/ — mount backend
- `60_zeromount-android14-6.1.patch` — the VFS `getname()` redirect engine and
  the `/dev/zeromount` control device. Source: Super-Builders, by ZeroMount's
  own author.
- `70_ksu_safety-wksu-6.1.patch` — KSU build guard that ships beside it.
- `fix-susfs-compat.sh` — reconciles susfs and zeromount, which touch
  overlapping code; run before the zeromount patch.

Why ZeroMount over NoMount: NoMount hijacks a directory's inode ops and keeps the
redirect in the dcache, so it is lost when that dentry is evicted (reproduced
with `drop_caches`), and manipulating it can panic this kernel. ZeroMount
redirects the path string at `getname()`, before any dcache lookup, so eviction
does not affect it.

## vpnhide/ — built-in VPN hiding
- One `<source>.c.patch` per kernel file vpnhide hooks (fs_namei, net_socket,
  ipv4/ipv6 addr/route/fib, dev_ioctl, rtnetlink, readdir, stat).
- Source: okhsunrog/vpnhide `builtin/versions/android14-6.1`, pinned by
  `VPNHIDE_REV`. Compiled in, not loaded as a `.ko` — the point of this build is
  to exercise that backend. The manager APK is built from the same commit.

## ksu/ — patch A (ours)
- `90_app_profile_manager_or_root.patch` — widens GET/SET_APP_PROFILE from
  only_manager to manager_or_root, the check every other policy command already
  carries. Verified to apply against KernelSU-Next `dev` with `git apply`.
