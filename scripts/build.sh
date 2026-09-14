#!/usr/bin/env bash
# Build the kernel image with bazel (kleaf), the way android14-6.1 is built.
#
# Same invocation WildKernels use: check_defconfig disabled so our added CONFIGs
# pass validation, thin LTO, the disk cache kept under the build dir. The clang
# is the AOSP prebuilt that came down with `repo sync`, not the host's.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/versions.env"

WORK="${1:?usage: build.sh <build-dir>}"
cd "$WORK"

[ -f common/BUILD.bazel ] || {
    echo "error: no kleaf tree at $WORK/common -- run sync.sh first" >&2
    exit 1
}

# Drop the savedefconfig check. kleaf runs POST_DEFCONFIG_CMDS from
# build.config.gki, which is "check_defconfig" -- it fails the build unless the
# final .config round-trips to exactly the committed gki_defconfig, which our
# added CONFIGs cannot. WildKernels remove it the same way. This edits a file in
# the synced GKI tree, not a source we keep; a re-sync restores it.
sed -i 's/\bcheck_defconfig\b//' common/build.config.gki

# Pin the scmversion tail so UTS_RELEASE reads as the stock vendor string
# instead of kleaf's unstamped "-maybe-dirty" placeholder (stamp.bzl echoes it
# when built without --config=stamp, as we are). This is cosmetic, not the
# WiFi/BT fix: with CONFIG_MODVERSIONS=y the kernel skips the release-string part
# of a module's vermagic and gates on symbol CRCs instead, so the scm tail does
# not decide whether stock modules load (disabling MODULE_SIG_PROTECT in the
# fragment does). We still pin it so `uname -r` matches stock and no "-maybe-dirty"
# leaks out. Edits a file in the synced kleaf tree, not a source we keep.
STAMP_BZL=build/kernel/kleaf/impl/stamp.bzl
if [ -n "${STOCK_SCMVERSION:-}" ] && grep -q "echo '-maybe-dirty'" "$STAMP_BZL"; then
    echo "==> pinning scmversion tail to $STOCK_SCMVERSION"
    sed -i "s|echo '-maybe-dirty'|echo '$STOCK_SCMVERSION'|" "$STAMP_BZL"
fi

# The GKI protected-exports gate (which refuses the device's stock modules -- see
# CONFIG_MODULE_SIG_PROTECT in configs/husky.fragment) is disabled through that
# Kconfig, not by editing the kleaf BUILD.bazel: removing the list there does not
# invalidate kleaf's incremental build cache, so the compiled-in list survived a
# rebuild. A defconfig change is Kbuild-tracked and rebuilds reliably.

# Merge our fragment into gki_defconfig so the patched-in subsystems are built.
# reset --hard in apply-patches restores gki_defconfig to stock, so a fresh
# apply+build always starts from a clean base and appends once. Guarded anyway.
DEFCONFIG=common/arch/arm64/configs/gki_defconfig
if ! grep -q '^CONFIG_KSU=y' "$DEFCONFIG"; then
    echo "==> merging configs/husky.fragment into gki_defconfig"
    { echo; cat "$ROOT/configs/husky.fragment"; } >> "$DEFCONFIG"
fi

echo "==> bazel build //common:kernel_aarch64_dist  (LTO=$LTO_MODE)"
tools/bazel build \
    --config=fast \
    --lto="$LTO_MODE" \
    --disk_cache="$WORK/.bazel-cache" \
    //common:kernel_aarch64_dist

IMAGE=""
for c in bazel-bin/common/kernel_aarch64/Image out/dist/Image; do
    [ -f "$c" ] && IMAGE="$c" && break
done
[ -n "$IMAGE" ] || { echo "error: build finished but no Image found" >&2; exit 1; }

echo "==> Image: $WORK/$IMAGE"
echo "    package with AnyKernel3 to flash (see docs/BUILDING.md)"
