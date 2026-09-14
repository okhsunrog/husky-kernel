#!/usr/bin/env bash
# Normalise vendor-hook includes so the SUSFS patch anchors, then restore them.
#
# simonpunk's 50_add_susfs patch is cut against a GKI tree that lacks a couple of
# Android vendor-hook includes present in the published android14-6.1 sources
# (trace/hooks/blk.h in namespace.c, trace/hooks/fs.h in super.c). Their extra
# lines shift the patch's context so it will not apply. WildKernels' susfs-patches
# actions remove those includes before the patch and add them back after; this
# does the same for the two files the patch actually needs it for.
#
# WildKernels also fake-patch fs/proc/base.c (adding dma-buf.h and sched.h), but
# that is for GKI trees whose base.c lacks those includes. The published
# android14-6.1-2025-12 base.c already carries them as vendor additions, so
# touching it here is wrong: the restore's `sed /.../d` deletes every occurrence,
# including the real ones, and the build then fails on undeclared dma_buf helpers.
# So base.c is left alone.
#
#   fake-patch.sh prepare <common>   # before applying 50_add_susfs
#   fake-patch.sh restore <common>   # after
set -euo pipefail

phase="${1:?prepare|restore}"
COMMON="${2:?<common-dir>}"
cd "$COMMON"

case "$phase" in
  prepare)
    sed -i '/^#include <trace\/hooks\/blk.h>$/d' fs/namespace.c
    sed -i '/^#include <trace\/hooks\/fs.h>$/,+1 d' fs/super.c
    ;;
  restore)
    sed -i '/^#include "internal.h"$/a #include <trace/hooks/blk.h>' fs/namespace.c
    sed -i '/^#include "internal.h"$/a #include <trace/hooks/fs.h>' fs/super.c
    ;;
  *) echo "usage: fake-patch.sh prepare|restore <common>" >&2; exit 1 ;;
esac
