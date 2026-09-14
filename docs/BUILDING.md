# Build, update and install

## Source ownership

`versions.env` pins the full component commits. `manifests/aosp.xml` pins all
AOSP projects, including compiler and build tools. Branch names are fetch hints,
not versions. Keep the common project revision in both files consistent.

`build/` is generated and may be reset by `prepare`. `adopt` is a one-time
explicit opt-in: it archives the previous nested KernelSU tree and tracked
common/Kleaf diffs under `build/backups/`. Never develop source changes there.

`~/code/KernelSU-Next` is the maintained KSU fork. Its default branch is
`dev-susfs`; upstream `dev` and the old topic branches remain available.
Update the small local commit series over a reviewed pershoot revision, push
it, then change `KSU_NEXT_REV`. The app-profile permission belongs in that fork,
not in a second husky patch.

## Commands

Initial setup or deliberate pin update:

```sh
uv run --no-project scripts/forge.py adopt build
scripts/sync.sh build
```

Build a complete release using those sources:

```sh
scripts/release.sh build
```

Individual stages are also available:

```sh
scripts/apply-patches.sh build
scripts/build.sh build
uv run --no-project scripts/forge.py manager build
uv run --no-project scripts/forge.py builtin build
uv run --no-project scripts/forge.py package build
```

`kernel` regenerates defconfig and the cosmetic SCM suffix from pristine inputs
every time. It pins TMPDIR inside the captured Kleaf environment, preventing an
old host-private temporary directory from breaking sandboxed compiler actions.
Only the kernel target is built; the phone retains its stock dlkm partitions.
Manager/userspace build artifacts are excluded from Kleaf's kernel source
filegroup so an APK rebuild does not invalidate the kernel or fill its cache.
Packaging rejects missing kernel features, an Image without the trusted
certificate, changed inputs, a mismatching APK version/package/signature, or an
APK without arm64 `ksud`.

KSU's version calculation uses the pinned `KSU_VERSION_BASE_REV` through the
build checkout's `origin/dev` ref. Keep the full Git history and tags. The
release's source SHA identifies local changes even when its upstream-compatible
KSU versionCode stays the same.

## Manager signing

`MANAGER_PACKAGE` is stable across releases; do not run the upstream random
`spoof` script on the build tree. The recipe rewrites tracked text and relocates
AIDL, leaving binary assets untouched. Subsequent APKs update the same app.

`MANAGER_CERT` contains only the size and SHA-256 of the public DER certificate.
The existing signing properties file and private key stay outside Git. Gradle
receives signing properties in its process environment; no password is copied
into generated configuration or passed in command-line arguments.

The kernel checks both package and certificate. This matters because the same
key also signs other personal apps, which must not become the root manager.
The APK must include a valid v2 signature. The two upstream certificates remain
in the list, but their other package names do not pass the package restriction.
The KSU fork accepts certificates up to 4096 bytes using a bounded heap buffer;
the original 1024-byte stack buffer rejected this key's 1288-byte certificate.
Preparation checks the configured certificate length against the driver limit.

## Installation and rollback

The flashing command requires an explicit serial and release directory:

```sh
uv run --no-project scripts/device.py flash --serial 3B241FDJG003LP --release /absolute/path/to/dist/release
adb -s 3B241FDJG003LP reboot
```

It checks device/slot and release checksums; saves the current boot image,
modules and vpnhide configuration; installs the new manager; repacks boot with
magiskboot from the installed kernelflasher APK; verifies the extracted kernel;
writes only the current boot slot; and verifies the written bytes. It does not
reboot automatically. Backups live in `dist/backup-<UTC>/` and record the slot.

After boot, confirm the new manager is recognised before changing modules.
Install `vpnhide-builtin.zip`, remove `vpnhide_kmod` through KernelSU, then reboot
again. The companion ZIP contains no `.ko`; it delivers the existing app config
to the in-tree backend. Confirm `/proc/vpnhide_ctl` reports `backend 0x4` and
`/data/adb/vpnhide_builtin/load_status` reports a live backend.

ZeroMount also needs its userspace metamodule; `/dev/zeromount` alone does not
load module files. Remove NoMount and reboot before installing another
metamodule or modules: KernelSU blocks installation while its custom installer
has pending changes. Install the ZeroMount release ZIP through the manager,
then reboot and verify the selected engine and active rules. KernelSU may
require physical volume-down confirmation for this module; do not bypass it.
The inspected `v2.0.216-dev` ZIP has SHA-256
`12f9fde9edde5317b86e3672b4b20981eaa16581d8e736ef781b7a628b1bd30f`;
its detection command reports driver v1 and SUSFS v2.3.0 on this kernel.

For rollback while Android/root is available, restore the saved `boot-before.img`
to the recorded boot slot and reboot. If Android cannot start, restore that
image from bootloader fastboot (`fastboot flash boot_a <backup>` for an `_a`
backup, or `boot_b` for `_b`). Do not substitute a slot from an older session.
Keep the previous manager until migration is verified; it remains useful when
booting the previous kernel.

## Validation

```sh
uv run --no-project python -m unittest discover -s tests -v
shellcheck scripts/*.sh
```

Hardware acceptance covers manager recognition, root access, profile JSON
read/write/read, WiFi/BT module loading, vpnhide backend identity and native
hiding. A successful build alone does not establish hardware correctness.
Installing the ZeroMount metamodule does not convert custom NoMount-specific
module layouts. Verify their resulting file redirects separately; redesigning
imsforge is outside the kernel build recipe.
