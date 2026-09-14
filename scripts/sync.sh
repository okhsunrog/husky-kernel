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
if [ ! -d common ]; then
    echo "==> repo init: common-$GKI_BRANCH"
    repo init --depth=1 -u https://android.googlesource.com/kernel/manifest \
        -b "common-$GKI_BRANCH"
fi
echo "==> repo sync"
repo sync -c --no-clone-bundle --no-tags -j"$(nproc)"

# --- 2. KernelSU-Next driver ----------------------------------------------
# Its own installer drops the driver into the tree and wires the Kconfig/Makefile.
echo "==> KernelSU-Next ($KSU_NEXT_REF)"
curl -LSs "https://raw.githubusercontent.com/KernelSU-Next/KernelSU-Next/$KSU_NEXT_REF/kernel/setup.sh" \
    | bash -s "$KSU_NEXT_REF"

# --- 3. SUSFS source files -------------------------------------------------
# The patches (applied later) expect these files already present in the tree.
if [ ! -d susfs4ksu ]; then
    git clone --depth=1 -b "$SUSFS_BRANCH" "$SUSFS_REPO" susfs4ksu
fi
git -C susfs4ksu fetch --depth=1 origin "$SUSFS_REV" && git -C susfs4ksu checkout -q "$SUSFS_REV"
cp susfs4ksu/kernel_patches/fs/* common/fs/ 2>/dev/null || true
cp susfs4ksu/kernel_patches/include/linux/* common/include/linux/ 2>/dev/null || true

# --- 4. vpnhide built-in source -------------------------------------------
# The .c.patch files graft vpnhide's hooks into existing kernel sources; its own
# translation units are copied in alongside them.
if [ ! -d vpnhide ]; then
    git clone --depth=1 -b "$VPNHIDE_REF" "$VPNHIDE_REPO" vpnhide
fi
git -C vpnhide fetch --depth=1 origin "$VPNHIDE_REV" && git -C vpnhide checkout -q "$VPNHIDE_REV"
# The exact set of source files to copy is resolved from vpnhide/builtin on the
# first real run; see docs/BUILDING.md.

echo "==> synced into $WORK"
echo "    next: scripts/apply-patches.sh $WORK"
