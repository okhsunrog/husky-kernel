# Maintaining the husky build

The recipe repository owns integration and pins. `build/` is disposable output;
source development belongs in the component's repository or in `patches/local/`.

| Change | Where to maintain it | Next step |
|---|---|---|
| Kernel configuration | `configs/husky.fragment` | `prepare`, then build |
| Small kernel patch or built-in driver | Files under `patches/local/`, listed in `series` | `prepare`, inspect the resulting diff |
| KernelSU driver, ksud or manager | The KSU fork's `dev-susfs` branch | Update `KSU_NEXT_REV`, sync and rebuild the complete release |
| vpnhide behavior or integration rules | vpnhide's own repository | Merge its change, pin the full SHA, sync and inspect its review bundle |
| SUSFS version | `SUSFS_REV` | Check the patch report and `scripts/layers.py` assumptions |
| GKI base or compiler | `versions.env` and `manifests/aosp.xml` together | Sync, review every layer, rebuild and validate on the device |
| AnyKernel installation logic | `configs/anykernel.sh` | Repackage only after inspecting the installer changes |
| Root-manager ZIP/metamodule | The module's own project | Install separately; it is not a kernel patch |

`patches/local/series` is ordered and uses paths relative to that directory.
Comments and blank lines are allowed. Patches use `-p1` and zero fuzz; include
new source files and their Kconfig/Makefile wiring in the patch. These patches
run after vpnhide, so a local patch changing the same functions needs review
against the final source as well as the vpnhide bundle.

External loadable `.ko` modules require matching KMI, configuration and symbol
CRCs. This recipe does not provide a general external-module build command or
rebuild the phone's vendor dlkm partitions. A KernelSU module ZIP and a kernel
object are different integration tasks.

## Update one or more pinned components

After reviewing the component commits and editing the full SHA pins:

```sh
uv sync --locked
uv run scripts/forge.py sync build
uv run scripts/forge.py doctor build
uv run scripts/forge.py prepare build
```

Inspect `build/patch-report.json`. Its `vpnhide_review` field locates the detailed
bundle (`report.md`, `report.json`, `vpnhide.patch`, `before/`, `after/`). Check
all SUSFS/ZeroMount offsets and fuzz, and any vpnhide strategy other than
`exact_rule`. Exact textual placement and a successful patch round trip do not
prove cleanup, locking, UID context or error-path correctness.

Then build the complete set from those prepared inputs:

```sh
uv run scripts/forge.py kernel build
uv run scripts/forge.py manager build
uv run scripts/forge.py builtin build
uv run scripts/forge.py package build
```

`uv run scripts/forge.py release build` is the combined prepare/build/package
command. It does not stop for interactive review. The release path is printed
and saved in `build/.husky-release`; generated artifacts stay out of Git.
A per-tree lock rejects overlapping CLI operations.

Do not copy fixes into `build/common` as the maintained solution: a subsequent
prepare resets it. After a failed prepare, fix the source recipe and rerun it.
After source/config changes, rebuild before packaging; the input fingerprint
rejects stale Images. The vpnhide adapter has no legacy shell fallback.

## Install and validate

Builds do not flash or reboot a device. Use the explicit serial/release commands
in [BUILDING.md](BUILDING.md#installation-and-rollback). After reboot, run the
read-only `device.py verify` command and perform the hardware checks recorded
in [VALIDATION.md](VALIDATION.md). Keep the previous boot backup and manager
available until the new kernel has been checked.
