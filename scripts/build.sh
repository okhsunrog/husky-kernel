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

# Pin the scmversion tail so UTS_RELEASE matches the stock vendor modules'
# vermagic (see STOCK_SCMVERSION in versions.env). Unstamped kleaf builds echo
# "-maybe-dirty" as the scmversion (stamp.bzl), which no prebuilt module
# accepts -- WiFi (bcmdhd) and BT then silently fail to load. We build unstamped
# (no --config=stamp), so replacing that one fallback string is enough; the rest
# of the release ("-android14-11") kleaf already composes correctly. This edits
# a file in the synced kleaf tree, not a source we keep; a re-sync restores it.
STAMP_BZL=build/kernel/kleaf/impl/stamp.bzl
if [ -n "${STOCK_SCMVERSION:-}" ] && grep -q "echo '-maybe-dirty'" "$STAMP_BZL"; then
    echo "==> pinning scmversion tail to $STOCK_SCMVERSION"
    sed -i "s|echo '-maybe-dirty'|echo '$STOCK_SCMVERSION'|" "$STAMP_BZL"
fi

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
