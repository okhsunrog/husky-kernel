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
# Canonicalise to an absolute path: pfuzzy cd's into $COMMON before reading a
# patch, so any relative patch path (e.g. the susfs one built from $COMMON)
# would resolve against the wrong dir. Absolute here keeps every path stable.
KERNEL="$(cd "${1:?usage: apply-patches.sh <build-dir>}" && pwd)"
COMMON="$KERNEL/common"
KSU="$COMMON/KernelSU-Next"
P="$ROOT/patches"

[ -f "$COMMON/Makefile" ] || { echo "error: no kernel at $COMMON -- run sync.sh" >&2; exit 1; }

# Start from the clean patch base. patch -p1 half-applies and skips on a dirty
# tree, so a re-run resets first. sync.sh committed the base (GKI + KernelSU-Next
# + susfs sources), so reset --hard returns there -- KSU integration and susfs.c
# included, stock namespace.c/base.c restored. What the patch layers create is
# untracked, so reset --hard leaves it behind; `patch` then refuses to recreate
# an existing new file (zeromount.c, zeromount.h). Clear those and any rejects
# explicitly. vpnhide's outputs (security/vpnhide/, include/linux/vpnhide.h) are
# cleared by its own apply.sh (rm -rf + overwriting cp), so they need no line.
echo "==> reset $COMMON to the patch base"
git -C "$COMMON" reset -q --hard HEAD
rm -f "$COMMON/fs/zeromount.c" "$COMMON/include/linux/zeromount.h"
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
# Only the 60_ VFS-redirect patch. The 70_ksu_safety-wksu patch that ships beside
# it targets Wild_KSU's kernel/supercalls.c (single-file supercall table) and
# adds an optional CMD_SUSFS_ADD_SUS_KSTAT_REDIRECT handler. Our KSU is
# pershoot/KernelSU-Next dev-susfs, whose supercalls live in
# kernel/supercall/dispatch.c and whose susfs is integrated in-tree; the patch
# has nothing to anchor to, and we do not enable that susfs sub-feature anyway.
# It was silently skipped in the first build too. Dropped, not carried dead.
bash "$P/zeromount/fix-susfs-compat.sh" "$COMMON" 2>/dev/null || true
pfuzzy zeromount "$COMMON" "$P/zeromount/60_zeromount-android14-6.1.patch"

# 3. vpnhide built-in (upstream's own integrator) --------------------------
# vpnhide ships builtin/scripts/apply.sh, which is the canonical way to graft
# the in-tree backend: it copies the driver into security/vpnhide/, vendors the
# shared logic + generated tables from kmod/, installs include/linux/vpnhide.h,
# wires security/{Kconfig,Makefile}, and applies the 13 per-version call-site
# patches (builtin/versions/android14-6.1) with the same `patch -p1 --fuzz=3`
# used above. Delegating keeps one source of truth in the pinned clone rather
# than a hand-copied duplicate, and tracks the backend as it evolves. The
# reset --hard above reverted the call-site files and unwired Kconfig/Makefile;
# apply.sh rm -rf's security/vpnhide and re-copies, so a re-run is clean.
VPNHIDE="$KERNEL/vpnhide"
[ -x "$VPNHIDE/builtin/scripts/apply.sh" ] \
    || { echo "error: no vpnhide clone at $VPNHIDE -- run sync.sh" >&2; exit 1; }
echo "==> vpnhide: builtin/scripts/apply.sh (android14-6.1)"
bash "$VPNHIDE/builtin/scripts/apply.sh" "$COMMON" android14-6.1

# 4. Patch A: root may read/write app profiles (git apply -- see header) ----
# KernelSU-Next is a nested git repo (its own .git), so the common reset above
# does not touch its working tree -- patch A would still be applied from a prior
# run and `git apply` would then reject it. Reset the nested repo to its pristine
# HEAD (setup.sh's clone of pershoot dev-susfs, susfs already in-tree; patch A is
# the only thing we add) so the apply is clean and idempotent.
echo "==> ksu: reset KernelSU-Next to pristine, then patch A"
git -C "$KSU" reset -q --hard HEAD
git -C "$KSU" apply --recount "$P"/ksu/90_app_profile_manager_or_root.patch

echo "==> all layers applied"
