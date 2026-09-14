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

# Let our extra CONFIGs through defconfig validation.
grep -q 'check_defconfig = "disabled"' common/BUILD.bazel ||
    sed -i '/name = "kernel_aarch64",/a\    check_defconfig = "disabled",' common/BUILD.bazel

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
