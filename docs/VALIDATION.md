# Pixel 8 Pro validation

## Python workflow release, 2026-09-15

Installed release `20260915T001956Z-fe8ce79b2439` in slot `_a`, including the
signed manager APK. The release was built with the Python orchestration and
vpnhide integrator pinned to merged commit `64530f6555a9d997f80db8b55341e461955bd0c2`.
Backup: `dist/backup-20260915T011758Z` (private; do not publish).

After reboot, the full boot partition and repacked image both had SHA-256
`a26f11b1054e4e943b0f1803bb485495496475fb3f47450e4744609d086b61e1`.
Android completed boot, root worked, the manager package was installed, and
`ksud profile get '$'` returned JSON through the direct root ioctl.

SUSFS intentionally changed `uname -r` to its configured spoofed value.
`/proc/version` retained the expected `-ge4470993d947-ab15260412` suffix.
The verification command now reads that banner instead of `uname`, and rejects
companion status belonging to an earlier boot. The banner check is not an
Image identity check; the boot hash above provides separate flash evidence.

The companion status matched the current boot ID and reported `runtime=builtin`,
`loaded=1`. Its installed activator, post-fs-data and service scripts matched
the release ZIP byte-for-byte, so no companion reinstall was needed.
The control node reported backend `0x4`, error `0x0`, and nonzero per-UID counters.
ZeroMount reported scenario `Full`, an active engine and one active VFS rule
redirecting `/product/etc/CarrierSettings/others.pb` to the imsforge replacement.

WiFi connected and Android reported validated internet access. WiFi and Bluetooth
kernel modules were loaded. The available dmesg contained no panic, Oops,
unknown-symbol or module-version mismatch messages. Bluetooth pairing, calling,
audio, suspend and a new controlled VPN hiding probe were not exercised during
this installation. Earlier tests below are separate evidence, not repeated tests
of this release.

## Previous release, 2026-09-14

Release: `20260914T191818Z-fe8ce79b2439`, KSU fork
`fe8ce79b24392530d197a26280a0dafadbad1e0f`, boot slot `_a`.

The repacked boot Image matched the release Image. Flash readback matched the
repacked boot image. Android booted with root available. The kernel logged the
configured manager certificate match (1288 bytes) and crowned the stable
manager package. Its UI reported `Working`, `BUILT-IN (GKI2)`, kernel and manager
`33276-4`, Hybrid hooks and SUSFS `v2.3.0 (GKI)`.

The installed `ksud` reads app profiles as JSON directly as root. A default
non-root profile read/set-same/read round trip passed without UID impersonation.

The user removed NoMount and vpnhide_kmod in the manager; their directories
disappeared after reboot. The canonical vpnhide configuration SHA-256 stayed
unchanged across removal. The built-in companion installed successfully.

ZeroMount `v2.0.216-dev` detected scenario `Full`, driver `v1`, and SUSFS `v2.3.0`.
Its release ZIP SHA-256 matched the GitHub release asset digest recorded in
BUILDING.md. Installation completed after physical volume-down confirmation.
After reboot, `sys.boot_completed=1`, the manager still reported `Working`, and
its metamodule status reported `Installed` without the old NoMount label.
ZeroMount reported `engine_active: Some(true)` and `engine: active rules: 2`.
The imsforge module used `strategy=Vfs rules=2/2`. The visible
`/product/etc/CarrierSettings/others.pb` SHA-256 matched its module replacement.
This checks file delivery, not carrier registration or IMS calling.

The vpnhide companion reported `runtime=builtin`, `loaded=1`, and
`detail=in-tree backend live`; the control node reported `backend 0x4` and
`error 0x0`. No vpnhide loadable module was present. The native probe created a
temporary, unrouted TUN interface. Root and an unconfigured control UID could
query its hardware address; the configured target UID received `ENODEV` and
did not enumerate it. Android also omitted the unaddressed interface from the
control UID's enumeration, so that observation alone is not attributed to
vpnhide. The probe removed the interface automatically. This is a UID-scoped
native test, not a complete VPN application or leak test.

The installed CLI repeated the profile round trip successfully on the final
boot. WiFi and Bluetooth kernel modules loaded; the captured dmesg contained no
kernel panic, Oops, unknown-symbol or module-version mismatch errors. Radio
connectivity, audio and suspend were not exhaustively exercised.

Host validation: three recipe regression tests, shellcheck, Python compilation,
and Git whitespace checks passed. The native vpnhide probe compiled for Android
arm64 with `-Wall -Wextra -Werror`.

The original pre-migration boot image remains locally at
`dist/backup-20260914T190950Z/boot-before.img`, SHA-256
`19705286447a1e61d5ecd2f536754d6256b5dddc37284029108286a1a9a996e2`.
Backups contain private module/configuration state and must not be published.
