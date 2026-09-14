#!/usr/bin/env bash
# Apply every patch layer to a synced GKI tree, in order, from a clean state.
#
# The order is the contract: SUSFS lays the hiding infrastructure, ZeroMount
# builds its VFS redirect on top (and needs SUSFS present -- fix-susfs-compat
# reconciles the two), vpnhide adds its hooks, and patch A widens the KSU
# app-profile permission. Each layer is applied with `git apply`, which fails
# loudly rather than half-applying, so a reject stops the build instead of
# producing a silently-wrong kernel.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/versions.env"

KERNEL="${1:?usage: apply-patches.sh <kernel-source-dir>}"
P="$ROOT/patches"

cd "$KERNEL"
git -C common rev-parse HEAD >/dev/null 2>&1 || {
    echo "error: $KERNEL/common is not a git tree -- run sync.sh first" >&2
    exit 1
}

apply() {
    local label="$1" patch="$2"
    echo "==> $label: $(basename "$patch")"
    git -C common apply --recount "$patch"
}

# 1. SUSFS -----------------------------------------------------------------
apply susfs "$P/susfs/50_add_susfs_in_gki-android14-6.1.patch"
apply susfs "$P/susfs/51_enhanced_susfs-android14-6.1.patch"

# 2. ZeroMount (needs SUSFS in place) --------------------------------------
bash "$P/zeromount/fix-susfs-compat.sh" "$KERNEL/common" || true
apply zeromount "$P/zeromount/60_zeromount-android14-6.1.patch"
apply zeromount "$P/zeromount/70_ksu_safety-wksu-6.1.patch"

# 3. vpnhide built-in (one patch per touched source file) ------------------
for patch in "$P"/vpnhide/*.c.patch; do
    apply vpnhide "$patch"
done

# 4. Patch A: root may read/write app profiles -----------------------------
apply ksu "$P/ksu/90_app_profile_manager_or_root.patch"

echo "==> all layers applied"
