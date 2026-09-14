#!/usr/bin/env bash
# Fetch the GKI source and every component into a build tree.
#
# This mirrors what WildKernels' download-kernel + root-setup + susfs actions do,
# reduced to the one device this repo targets. The AOSP prebuilt toolchain comes
# down with `repo sync`; nothing here uses the host clang for the kernel itself.
#
# Idempotent: re-running against an existing tree re-syncs rather than starting
# over. Pass a fresh directory for a clean build.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/versions.env"

WORK="${1:?usage: sync.sh <build-dir>}"
mkdir -p "$WORK"
cd "$WORK"

# --- 1. GKI kernel source (brings the AOSP toolchain with it) --------------
# init is idempotent and cheap; running it every time keeps the manifest branch
# in step with GKI_BRANCH even on a re-sync.
echo "==> repo init: common-$GKI_BRANCH"
repo init --depth=1 -u https://android.googlesource.com/kernel/manifest \
    -b "common-$GKI_BRANCH"
echo "==> repo sync"
repo sync -c --no-clone-bundle --no-tags --force-sync -j"$(nproc)"

# --- 2. KernelSU-Next driver ----------------------------------------------
# Its own installer drops the driver into the tree and wires the Kconfig/Makefile.
# It looks for drivers/ in the current directory, which in a GKI tree is common/,
# not the workspace root -- so it runs from there.
echo "==> KernelSU-Next ($KSU_NEXT_REF)"
( cd common && curl -LSs \
    "https://raw.githubusercontent.com/KernelSU-Next/KernelSU-Next/$KSU_NEXT_REF/kernel/setup.sh" \
    | bash -s "$KSU_NEXT_REF" )

# --- 3. SUSFS (simonpunk/susfs4ksu, the WildKernels way) ------------------
# Clone susfs4ksu and copy its kernel_patches sources into the tree; the patch
# itself (kernel_patches/50_add_susfs...) is applied later by apply-patches.sh,
# between fake-patch prepare/restore.
if [ ! -d susfs4ksu ]; then
    git clone --depth=1 -b "$SUSFS_BRANCH" "$SUSFS_REPO" susfs4ksu
fi
cp susfs4ksu/kernel_patches/fs/* common/fs/ 2>/dev/null || true
cp susfs4ksu/kernel_patches/include/linux/* common/include/linux/ 2>/dev/null || true

# --- 4. vpnhide built-in source -------------------------------------------
# Cloned so its built-in translation units are available to graft in. The
# branch tip is the pin (VPNHIDE_REV); we check it rather than fetch a short
# sha, which git refuses.
if [ ! -d vpnhide ]; then
    git clone --depth=1 -b "$VPNHIDE_REF" "$VPNHIDE_REPO" vpnhide
fi
HAVE=$(git -C vpnhide rev-parse --short HEAD)
[ "$HAVE" = "$VPNHIDE_REV" ] || echo "  ! vpnhide is at $HAVE, versions.env pins $VPNHIDE_REV"
# The exact set of source files to copy is resolved from vpnhide/builtin on the
# first real run; see docs/BUILDING.md.

# --- 5. Commit this as the patch base -------------------------------------
# KernelSU-Next's setup edits tracked files (drivers/Kconfig, drivers/Makefile),
# and susfs4ksu's sources are copied in. apply-patches resets common to a clean
# state before every run; without committing here that reset would strip the KSU
# integration back to stock GKI and CONFIG_KSU would vanish. Committing makes
# GKI + KSU + susfs sources the base the reset returns to.
echo "==> commit patch base (GKI + KernelSU-Next + susfs sources)"
git -C common add -A
git -C common -c user.name=husky-kernel -c user.email=build@localhost \
    commit -q -m "husky-kernel patch base: KernelSU-Next + susfs sources" || true

echo "==> synced into $WORK"
echo "    next: scripts/apply-patches.sh $WORK"
