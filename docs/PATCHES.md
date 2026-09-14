# Integration layers

Applied to the pinned stock GKI tree by `scripts/forge.py prepare`:

1. Wire the pinned KSU fork through `drivers/kernelsu`.
2. Copy the pinned SUSFS sources and apply its `50_add_susfs` patch between the
   local vendor-header prepare/restore transformations.
3. Apply the vendored ZeroMount VFS driver patch after the compatibility helper.
   The unused Wild_KSU-specific `70_ksu_safety` patch is not carried.
4. Run the pinned vpnhide `builtin/scripts/apply.sh` integrator. This vendors
   shared/generated headers, adds the in-tree driver and applies its call-site
   patches. No loadable vpnhide object is required.
5. Configure the public manager certificate/package and regenerate defconfig.

The app-profile root permission is committed in the KSU fork and checked by
the recipe. There is no second copy under `patches/ksu`.

The ZeroMount patch comes from Super-Builders; its actual bytes are versioned
here. SUSFS and vpnhide integration inputs are pinned by repository commit.
Fuzzy patching is retained for these upstream patch formats, with failures
propagated rather than suppressed. Review offsets/context during upgrades.

`CONFIG_MODULE_SIG_PROTECT` is disabled so Google-signed stock modules are not
rejected for exporting protected symbols. `CONFIG_MODVERSIONS` remains enabled;
matching a cosmetic `uname` suffix is not a replacement for KMI/symbol-CRC
compatibility. The release gate checks the final configuration.
