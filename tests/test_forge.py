import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

SPEC = importlib.util.spec_from_file_location("forge", Path(__file__).resolve().parents[1] / "scripts/forge.py")
forge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(forge)


class BuildRecipeTests(unittest.TestCase):
    def test_local_series_preserves_order_and_records_added_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obj = forge.Forge(root / "work")
            obj.common.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(obj.common)], check=True)
            obj.report = {"steps": []}
            local = root / "patches/local"
            forge.write(local / "series", "# deliberate order\n20-add.patch\n10-change.patch\n")
            forge.write(local / "20-add.patch", "--- /dev/null\n+++ b/feature.c\n@@ -0,0 +1 @@\n+first\n")
            forge.write(local / "10-change.patch", "--- a/feature.c\n+++ b/feature.c\n@@ -1 +1 @@\n-first\n+second\n")
            with patch.object(forge, "ROOT", root):
                obj.local_patches()
            self.assertEqual((obj.common / "feature.c").read_text(), "second\n")
            self.assertIn("feature.c", (obj.work / ".husky-local-files.json").read_text())
            self.assertEqual([s["name"] for s in obj.report["steps"]], ["local: 20-add.patch", "local: 10-change.patch"])

    def test_added_sources_and_staged_changes_affect_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", tmp], check=True)
            forge.write(root / "tracked.c", "before\n")
            subprocess.run(["git", "-C", tmp, "add", "."], check=True)
            subprocess.run(["git", "-C", tmp, "-c", "user.name=test", "-c", "user.email=test@localhost",
                            "-c", "commit.gpgSign=false", "commit", "-qm", "fixture"], check=True)
            initial = forge.repo_identity(root)
            forge.write(root / "tracked.c", "after\n")
            subprocess.run(["git", "-C", tmp, "add", "."], check=True)
            staged = forge.repo_identity(root)
            self.assertNotEqual(initial, staged)
            forge.write(root / "new-driver.c", "first\n")
            added = forge.repo_identity(root)
            self.assertNotEqual(staged, added)
            forge.write(root / "new-driver.c", "second\n")
            self.assertNotEqual(added, forge.repo_identity(root))

    def test_failed_vpnhide_integration_leaves_kernel_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obj = forge.Forge(root)
            obj.report = {"steps": []}
            forge.write(obj.common / "security/Kconfig", "original\n")
            forge.write(obj.common / "security/Makefile", "original\n")
            forge.write(obj.common / "net/socket.c", "original\n")
            source = root / "vpnhide/builtin"
            forge.write(source / "versions/android14-6.1/01.patch",
                        "--- a/net/socket.c\n+++ b/net/socket.c\n@@ -1 +1 @@\n-original\n+changed\n")
            forge.write(source / "scripts/apply.sh", 'echo changed > "$1/net/socket.c"\necho "failure with offset 4"\nexit 1\n')
            with self.assertRaisesRegex(RuntimeError, "staged integration failed"):
                obj.integrate_vpnhide()
            self.assertEqual((obj.common / "net/socket.c").read_text(), "original\n")
            self.assertEqual(obj.report["steps"][0]["exit_code"], 1)
            self.assertEqual(obj.report["steps"][0]["adjustments"], ["failure with offset 4"])

    def test_vpnhide_rejects_patch_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obj = forge.Forge(root)
            forge.write(root / "vpnhide/builtin/versions/android14-6.1/01.patch",
                        "--- a/../../outside\n+++ b/../../outside\n")
            with self.assertRaisesRegex(RuntimeError, "Unsafe patch path"):
                obj.integrate_vpnhide()

    def test_every_manifest_project_has_an_immutable_revision(self):
        config = forge.read_config()
        projects = ET.parse(forge.ROOT / "manifests/aosp.xml").getroot().findall("project")
        self.assertGreater(len(projects), 10)
        for project in projects:
            self.assertRegex(project.attrib["revision"], r"^[0-9a-f]{40}$")
            self.assertIn("path", project.attrib)
        self.assertEqual(next(p.attrib["revision"] for p in projects if p.attrib["path"] == "common"), config["GKI_REV"])

    def test_unmanaged_tree_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "Unmanaged"):
                forge.Forge(tmp).owned()

    def test_configuration_updates_replace_previous_generated_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            common = root / "work/common"
            kleaf = root / "work/build/kernel"
            for repo in [common, kleaf]:
                repo.mkdir(parents=True)
                subprocess.run(["git", "init", "-q", str(repo)], check=True)
            forge.write(common / "arch/arm64/configs/gki_defconfig", "CONFIG_BASE=y\n")
            forge.write(common / "build.config.gki", "POST_DEFCONFIG_CMDS=check_defconfig\n")
            forge.write(kleaf / "kleaf/impl/stamp.bzl", "echo '-maybe-dirty'\n")
            forge.write(kleaf / "kleaf/common_kernels.bzl", 'exclude = [\n                "BUILD.bazel",\n]\n')
            for repo in [common, kleaf]:
                subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
                subprocess.run(["git", "-C", str(repo), "-c", "user.name=test", "-c", "user.email=test@localhost",
                                "-c", "commit.gpgSign=false", "commit", "-qm", "fixture"], check=True)
            obj = forge.Forge(root / "work")
            obj.c["GKI_REV"] = forge.git(common, "rev-parse", "HEAD")
            with patch.object(forge, "ROOT", root):
                forge.write(root / "configs/husky.fragment", "CONFIG_FIRST=y\n")
                obj.c["STOCK_SCMVERSION"] = "-first"
                obj.configure()
                forge.write(root / "configs/husky.fragment", "CONFIG_SECOND=y\n")
                obj.c["STOCK_SCMVERSION"] = "-second"
                obj.configure()
                config = (common / "arch/arm64/configs/gki_defconfig").read_text()
                self.assertNotIn("CONFIG_FIRST", config)
                self.assertEqual(config.count("CONFIG_SECOND=y"), 1)
                self.assertEqual((kleaf / "kleaf/impl/stamp.bzl").read_text(), "echo '-second'\n")
                self.assertIn("export TMPDIR=/tmp", (common / "build.config.gki").read_text())
                self.assertEqual((kleaf / "kleaf/common_kernels.bzl").read_text().count('"KernelSU-Next/manager/**"'), 1)


if __name__ == "__main__":
    unittest.main()
