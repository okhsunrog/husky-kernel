#!/usr/bin/env bash
# Apply every patch layer to a synced GKI tree, in order, from a clean state.
#
# Order is a contract: SUSFS lays the hiding infrastructure, ZeroMount builds its
# VFS redirect on top (and needs SUSFS present), vpnhide adds its hooks, and
# patch A widens the KSU app-profile permission.
#
# Two tools, on purpose. The SUSFS/ZeroMount/vpnhide patches are distributed for
# `patch -p1` (fuzzy, offset-tolerant) the way WildKernels and Super-Builders
# apply them; `git apply` rejects their diff shape. Patch A is the reverse: it
# replaces the same one line in two adjacent table entries, which `patch`
# collapses into a single change -- `git apply` applies both. Each layer uses
# the tool that gets it right.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KERNEL="${1:?usage: apply-patches.sh <build-dir>}"
COMMON="$KERNEL/common"
KSU="$COMMON/KernelSU-Next"
P="$ROOT/patches"

[ -f "$COMMON/Makefile" ] || { echo "error: no kernel at $COMMON -- run sync.sh" >&2; exit 1; }

# Start from the clean patch base. patch -p1 half-applies and skips on a dirty
# tree, so a re-run resets first. sync.sh committed the base (GKI + KernelSU-Next
# + susfs sources), so reset --hard returns there -- KSU integration and susfs.c
# included, stock namespace.c/base.c restored. Only zeromount.c is untracked (the
# zeromount patch creates it), so it and any rejects are cleared explicitly.
echo "==> reset $COMMON to the patch base"
git -C "$COMMON" reset -q --hard HEAD
rm -f "$COMMON/fs/zeromount.c"
find "$COMMON" -name '*.rej' -delete 2>/dev/null || true

pfuzzy() { # label, dir, patch  -- apply with patch -p1
    echo "==> $1: $(basename "$3")"
    ( cd "$2" && patch -p1 -F3 --no-backup-if-mismatch < "$3" )
}

# 1. SUSFS (from susfs4ksu, applied between fake-patch prepare/restore) ------
# sync.sh has already copied susfs4ksu's sources into the tree.
echo "==> susfs: fake-patch prepare"
bash "$P/susfs/fake-patch.sh" prepare "$COMMON"
pfuzzy susfs "$COMMON" "$COMMON/../susfs4ksu/kernel_patches/50_add_susfs_in_gki-android14-6.1.patch"
echo "==> susfs: fake-patch restore"
bash "$P/susfs/fake-patch.sh" restore "$COMMON"

# 2. ZeroMount (needs SUSFS in place) --------------------------------------
bash "$P/zeromount/fix-susfs-compat.sh" "$COMMON" 2>/dev/null || true
pfuzzy zeromount "$COMMON" "$P/zeromount/60_zeromount-android14-6.1.patch"
pfuzzy zeromount "$COMMON" "$P/zeromount/70_ksu_safety-wksu-6.1.patch"

# 3. vpnhide built-in (one patch per touched source file) ------------------
for patch in "$P"/vpnhide/*.c.patch; do
    pfuzzy vpnhide "$COMMON" "$patch"
done

# 4. Patch A: root may read/write app profiles (git apply -- see header) ----
echo "==> ksu: $(basename "$P"/ksu/90_*.patch)"
git -C "$KSU" apply --recount "$P"/ksu/90_app_profile_manager_or_root.patch

echo "==> all layers applied"
