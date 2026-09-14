#!/usr/bin/env bash
# Normalise vendor-hook includes so the SUSFS patch anchors, then restore them.
#
# simonpunk's 50_add_susfs patch is cut against a GKI tree that lacks a couple of
# Android vendor-hook includes present in the published android14-6.1 sources
# (trace/hooks/blk.h in namespace.c, trace/hooks/fs.h in super.c, and two in
# proc/base.c). Their extra lines shift the patch's context so it will not apply.
# This is exactly what WildKernels' susfs-patches / susfs-revert-patches actions
# do: remove those includes before the patch, add them back after.
#
#   fake-patch.sh prepare <common>   # before applying 50_add_susfs
#   fake-patch.sh restore <common>   # after
set -euo pipefail

phase="${1:?prepare|restore}"
COMMON="${2:?<common-dir>}"
cd "$COMMON"

case "$phase" in
  prepare)
    sed -i '/^#include <trace\/events\/oom.h>$/a #include <trace/hooks/sched.h>' fs/proc/base.c
    sed -i '/^#include <linux\/cpufreq_times.h>$/a #include <linux/dma-buf.h>' fs/proc/base.c
    sed -i '/^#include <trace\/hooks\/blk.h>$/d' fs/namespace.c
    sed -i '/^#include <trace\/hooks\/fs.h>$/,+1 d' fs/super.c
    ;;
  restore)
    sed -i '/^#include <trace\/hooks\/sched.h>$/d' fs/proc/base.c
    sed -i '/^#include <linux\/dma-buf.h>$/d' fs/proc/base.c
    sed -i '/^#include "internal.h"$/a #include <trace/hooks/blk.h>' fs/namespace.c
    sed -i '/^#include "internal.h"$/a #include <trace/hooks/fs.h>' fs/super.c
    ;;
  *) echo "usage: fake-patch.sh prepare|restore <common>" >&2; exit 1 ;;
esac
