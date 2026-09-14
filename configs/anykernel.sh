#!/system/bin/sh
properties() { '
kernel.string=husky-kernel: KernelSU-Next + SUSFS + ZeroMount + vpnhide built-in
do.devicecheck=1
do.modules=0
do.systemless=0
do.cleanup=1
do.cleanuponabort=0
device.name1=husky
'; }
block=boot
is_slot_device=auto
ramdisk_compression=auto
patch_vbmeta_flag=auto
no_magisk_check=1
. tools/ak3-core.sh
split_boot
if [ -f "$SPLITIMG/ramdisk.cpio" ]; then
    unpack_ramdisk
    write_boot
else
    flash_boot
fi
