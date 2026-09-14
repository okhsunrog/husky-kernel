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
