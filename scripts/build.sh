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
