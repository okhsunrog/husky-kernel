#!/usr/bin/env python3
"""Explicit device actions, separate from building. Requires an adb serial."""
import argparse
import datetime
import json
from pathlib import Path
import shlex
import subprocess
import zipfile

from forge import ROOT, read_config, require, sha, write


class Device:
    def __init__(self, serial):
        self.serial = serial
        self.c = read_config()

    def adb(self, *args, capture=True):
        return subprocess.run(["adb", "-s", self.serial, *map(str, args)], check=True,
                              text=True, stdout=subprocess.PIPE if capture else None).stdout

    def root(self, command):
        return self.adb("shell", "su", "-c", shlex.quote("set -e; " + command))

    def validate(self):
        require(self.adb("shell", "getprop", "ro.product.device").strip() == "husky", "Not a Pixel 8 Pro")
        require("uid=0(root)" in self.root("id"), "Root shell unavailable")
        slot = self.adb("shell", "getprop", "ro.boot.slot_suffix").strip()
        require(slot in ["_a", "_b"], "Unrecognised boot slot")
        return slot

    def backup(self):
        slot = self.validate()
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dest = ROOT / "dist" / ("backup-" + stamp)
        dest.mkdir(parents=True, mode=0o700)
        stage = "/data/local/tmp/husky-" + stamp
        self.adb("shell", "mkdir", "-m", "700", stage)
        self.root(f"dd if=/dev/block/by-name/boot{slot} of={stage}/boot-before.img bs=1048576")
        self.adb("pull", stage + "/boot-before.img", dest / "boot-before.img", capture=False)
        require(sha(dest / "boot-before.img") == self.root("sha256sum " + stage + "/boot-before.img").split()[0], "Boot backup checksum mismatch")
        # Preserve module state and config before migrating the vpnhide backend.
        self.root(f"tar -czf {stage}/modules-before.tar.gz -C /data/adb modules; "
                  f"if [ -f /data/system/vpnhide_config.json ]; then cp /data/system/vpnhide_config.json {stage}/vpnhide_config.json; fi")
        self.adb("pull", stage + "/modules-before.tar.gz", dest / "modules-before.tar.gz", capture=False)
        if self.root("if [ -f /data/system/vpnhide_config.json ]; then echo yes; fi").strip() == "yes":
            write(dest / "vpnhide_config.json", self.root("cat /data/system/vpnhide_config.json"))
            (dest / "vpnhide_config.json").chmod(0o600)
        apk_path = self.adb("shell", "pm", "path", "com.github.capntrips.kernelflasher").strip().removeprefix("package:")
        require(apk_path.startswith("/data/app/") and "\n" not in apk_path, "Cannot locate kernelflasher APK")
        self.adb("pull", apk_path, dest / "kernelflasher.apk", capture=False)
        with zipfile.ZipFile(dest / "kernelflasher.apk") as apk:
            binary = dest / "magiskboot"
            binary.write_bytes(apk.read("lib/arm64-v8a/libmagiskboot.so"))
            binary.chmod(0o755)
        info = {"serial": self.serial, "slot": slot, "stage": stage,
                "boot_sha256": sha(dest / "boot-before.img"),
                "fingerprint": self.adb("shell", "getprop", "ro.build.fingerprint").strip()}
        write(dest / "backup.json", json.dumps(info, indent=2) + "\n")
        print("Backup:", dest)
        return dest

    def flash(self, release):
        release = Path(release).resolve()
        for line in (release / "SHA256SUMS").read_text().splitlines():
            digest, name = line.split("  ", 1)
            path = release / name
            require(path.resolve().parent == release, "Invalid release manifest path")
            require(sha(path) == digest, "Release checksum mismatch: " + name)
        pins = read_config(release / "versions.env")
        require(pins == self.c, "Release pins differ from checkout")
        backup = self.backup()
        info = json.loads((backup / "backup.json").read_text())
        stage, slot = info["stage"], info["slot"]
        # This package must exist when the new kernel first scans for a manager.
        self.adb("install", "-r", release / "KernelSU-Next-husky.apk", capture=False)
        self.adb("push", backup / "magiskboot", stage + "/magiskboot", capture=False)
        self.adb("push", release / "Image", stage + "/Image", capture=False)
        print(self.root(f"cd {stage}; chmod 755 magiskboot; ./magiskboot unpack boot-before.img; "
                        "cp Image kernel; ./magiskboot repack boot-before.img boot-new.img; "
                        "mkdir verify; cd verify; ../magiskboot unpack ../boot-new.img"))
        extracted = self.root(f"sha256sum {stage}/verify/kernel").split()[0]
        require(extracted == sha(release / "Image"), "Repacked boot contains a different kernel")
        self.adb("pull", stage + "/boot-new.img", backup / "boot-new.img", capture=False)
        size = (backup / "boot-new.img").stat().st_size
        capacity = int(self.root(f"blockdev --getsize64 /dev/block/by-name/boot{slot}").strip())
        require(size <= capacity, "Repacked image exceeds boot partition")
        require(self.validate() == slot, "Boot slot changed during preparation")
        require(self.root(f"sha256sum /dev/block/by-name/boot{slot}").split()[0] == info["boot_sha256"], "Boot partition changed after backup")
        print(self.root(f"dd if={stage}/boot-new.img of=/dev/block/by-name/boot{slot} bs=1048576 conv=fsync"))
        readback = self.root(f"head -c {size} /dev/block/by-name/boot{slot} | sha256sum").split()[0]
        require(readback == sha(backup / "boot-new.img"), "Flashed boot failed readback verification")
        print("Boot written and verified. Backup:", backup)
        print("Reboot explicitly with: adb -s", self.serial, "reboot")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["backup", "flash"])
    parser.add_argument("--serial", required=True)
    parser.add_argument("--release", type=Path)
    args = parser.parse_args()
    device = Device(args.serial)
    if args.command == "flash":
        require(args.release is not None, "--release is required")
        device.flash(args.release)
    else:
        device.backup()


if __name__ == "__main__":
    main()
