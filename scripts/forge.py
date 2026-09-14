#!/usr/bin/env python3
"""Pinned husky builds; run with uv run --no-project scripts/forge.py."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def read_config(path=None):
    result = {}
    for line in (path or ROOT / "versions.env").read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            result[key.strip()] = shlex.split(value, comments=True)[0]
    return result


def run(*args, cwd=None, env=None, capture=False):
    return subprocess.run([str(a) for a in args], cwd=cwd, env=env, check=True,
                          text=True, stdout=subprocess.PIPE if capture else None).stdout


def git(path, *args):
    return run("git", "-C", path, *args, capture=True).strip()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class Forge:
    def __init__(self, work):
        self.work = Path(work).resolve()
        self.c = read_config()
        self.common = self.work / "common"
        self.ksu = self.common / "KernelSU-Next"

    def owned(self):
        marker = self.work / ".husky-managed.json"
        require(marker.exists() and json.loads(marker.read_text())["work"] == str(self.work),
                "Unmanaged build tree: run adopt once to preserve its source changes")

    def adopt(self):
        """Preserve existing source edits before declaring a tree disposable."""
        self.work.mkdir(parents=True, exist_ok=True)
        if (self.work / ".husky-managed.json").exists():
            self.owned()
            return
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = self.work / "backups" / stamp
        for label, path in [("common", self.common), ("kleaf", self.work / "build/kernel")]:
            if (path / ".git").exists():
                write(backup / (label + ".patch"), git(path, "diff", "--binary", "HEAD") + "\n")
                write(backup / (label + ".head"), git(path, "rev-parse", "HEAD") + "\n")
        if self.ksu.exists():
            backup.mkdir(parents=True, exist_ok=True)
            shutil.move(self.ksu, backup / "KernelSU-Next")
        write(self.work / ".husky-managed.json", json.dumps({"work": str(self.work), "backup": str(backup)}))
        print("Preserved old sources:", backup, flush=True)

    def component(self, path, url, rev, branch=None):
        require(re.fullmatch(r"[0-9a-f]{40}", rev), "A full commit SHA is required")
        if not (path / ".git").exists():
            run("git", "clone", url, path)
        require(not git(path, "status", "--porcelain", "--untracked-files=no"),
                f"Source edits in {path}; preserve them before syncing")
        run("git", "-C", path, "remote", "set-url", "origin", url)
        run("git", "-C", path, "fetch", "--tags", url, branch or rev)
        run("git", "-C", path, "checkout", "--detach", rev)
        require(git(path, "rev-parse", "HEAD") == rev, f"Wrong revision in {path}")

    def sync(self):
        self.owned()
        state = self.work / ".husky-prepared.json"
        if state.exists():
            previous = json.loads(state.read_text())
            run("git", "-C", self.common, "reset", "--hard", previous["GKI_REV"])
            run("git", "-C", self.ksu, "reset", "--hard", previous["KSU_NEXT_REV"])
            run("git", "-C", self.ksu, "clean", "-fd", "--", "manager")
            kleaf = self.work / "build/kernel"
            run("git", "-C", kleaf, "restore", "kleaf/impl/stamp.bzl", "kleaf/common_kernels.bzl")
            state.unlink()
        run("repo", "init", "--depth=1", "-u", "https://android.googlesource.com/kernel/manifest",
            "-b", self.c["GKI_MANIFEST_REV"], cwd=self.work)
        overrides = ET.Element("manifest")
        for p in ET.parse(ROOT / "manifests/aosp.xml").getroot().findall("project"):
            ET.SubElement(overrides, "extend-project", name=p.attrib["name"],
                          path=p.attrib["path"], revision=p.attrib["revision"])
        target = self.work / ".repo/local_manifests/husky.xml"
        target.parent.mkdir(parents=True, exist_ok=True)
        ET.ElementTree(overrides).write(target, encoding="unicode")
        run("repo", "sync", "-c", "--no-clone-bundle", "--no-tags", "-j8", cwd=self.work)
        self.sync_components()

    def sync_components(self):
        self.owned()
        self.component(self.ksu, self.c["KSU_NEXT_REPO"], self.c["KSU_NEXT_REV"], self.c["KSU_NEXT_REF"])
        for name, prefix, branch in [("susfs4ksu", "SUSFS", "SUSFS_BRANCH"),
                                     ("vpnhide", "VPNHIDE", "VPNHIDE_REF"),
                                     ("anykernel", "ANYKERNEL", None)]:
            self.component(self.work / name, self.c[prefix + "_REPO"], self.c[prefix + "_REV"],
                           self.c[branch] if branch else None)

    def verify_sources(self):
        for p in ET.parse(ROOT / "manifests/aosp.xml").getroot().findall("project"):
            require(git(self.work / p.attrib["path"], "rev-parse", "HEAD") == p.attrib["revision"],
                    f"AOSP revision mismatch: {p.attrib['path']}")
        for path, key in [(self.ksu, "KSU_NEXT_REV"), (self.work / "susfs4ksu", "SUSFS_REV"),
                          (self.work / "vpnhide", "VPNHIDE_REV"), (self.work / "anykernel", "ANYKERNEL_REV")]:
            require(git(path, "rev-parse", "HEAD") == self.c[key], f"Revision mismatch: {path}")

    def prepare(self):
        self.owned()
        run("git", "-C", self.common, "reset", "--hard", self.c["GKI_REV"])
        self.verify_sources()
        run("git", "-C", self.common, "clean", "-fd", "--", "fs/zeromount.c", "include/linux/zeromount.h",
            "include/linux/vpnhide.h", "security/vpnhide")
        run("git", "-C", self.ksu, "reset", "--hard", self.c["KSU_NEXT_REV"])
        run("git", "-C", self.ksu, "clean", "-fd", "--", "manager")
        run("git", "-C", self.ksu, "checkout", "-B", "dev-susfs", self.c["KSU_NEXT_REV"])
        run("git", "-C", self.ksu, "update-ref", "refs/remotes/origin/dev", self.c["KSU_VERSION_BASE_REV"])
        link = self.common / "drivers/kernelsu"
        if link.is_symlink():
            link.unlink()
        link.symlink_to("../KernelSU-Next/kernel")
        with (self.common / "drivers/Makefile").open("a") as out:
            out.write("\nobj-$(CONFIG_KSU) += kernelsu/\n")
        with (self.common / "drivers/Kconfig").open("a") as out:
            out.write('\nsource "drivers/kernelsu/Kconfig"\n')
        for folder in ["fs", "include/linux"]:
            for src in (self.work / "susfs4ksu/kernel_patches" / folder).iterdir():
                require(src.is_file(), f"Unexpected SUSFS source: {src}")
                shutil.copy2(src, self.common / folder / src.name)
        run("bash", ROOT / "patches/susfs/fake-patch.sh", "prepare", self.common)
        run("patch", "--batch", "-p1", "-F3", "--no-backup-if-mismatch", "-i",
            self.work / "susfs4ksu/kernel_patches/50_add_susfs_in_gki-android14-6.1.patch", cwd=self.common)
        run("bash", ROOT / "patches/susfs/fake-patch.sh", "restore", self.common)
        run("bash", ROOT / "patches/zeromount/fix-susfs-compat.sh", self.common, "157", "android14", "6.1", ROOT / "patches")
        run("patch", "--batch", "-p1", "-F3", "--no-backup-if-mismatch", "-i",
            ROOT / "patches/zeromount/60_zeromount-android14-6.1.patch", cwd=self.common)
        run("bash", self.work / "vpnhide/builtin/scripts/apply.sh", self.common, "android14-6.1")
        kbuild = self.ksu / "kernel/Kbuild"
        certificate_limit = re.search(r"#define CERT_MAX_LENGTH (\d+)", (self.ksu / "kernel/manager/apk_sign.c").read_text())
        require(certificate_limit and int(self.c["MANAGER_CERT"].split(":")[0], 16) <= int(certificate_limit[1]),
                "Manager certificate exceeds the driver's buffer limit")
        text, n = re.subn(r"^(KSU_NEXT_MANAGER_LIST := .+)$", r"\1," + self.c["MANAGER_CERT"], kbuild.read_text(), flags=re.M)
        require(n == 1, "Manager trust list changed upstream")
        write(kbuild, text.replace("ifdef KSU_MANAGER_PACKAGE", "KSU_MANAGER_PACKAGE := " + self.c["MANAGER_PACKAGE"] + "\nifdef KSU_MANAGER_PACKAGE"))
        dispatch = (self.ksu / "kernel/supercall/dispatch.c").read_text()
        for name in ["GET_APP_PROFILE", "SET_APP_PROFILE"]:
            require(re.search(r'\.name = "' + name + r'"[^}]+\.perm_check = manager_or_root', dispatch), "KSU lacks root profile permission")
        self.configure()
        write(self.work / ".husky-prepared.json", json.dumps(self.c, sort_keys=True))

    def configure(self):
        config = git(self.common, "show", self.c["GKI_REV"] + ":arch/arm64/configs/gki_defconfig")
        write(self.common / "arch/arm64/configs/gki_defconfig", config + "\n" + (ROOT / "configs/husky.fragment").read_text())
        original = git(self.common, "show", self.c["GKI_REV"] + ":build.config.gki")
        # _preserve_env captures this into downstream sandbox actions. Do not
        # inherit a host-private TMPDIR from an old Bazel server/cache entry.
        write(self.common / "build.config.gki", re.sub(r"\bcheck_defconfig\b", "", original) + "\nexport TMPDIR=/tmp\n")
        kleaf = self.work / "build/kernel"
        original = git(kleaf, "show", "HEAD:kleaf/impl/stamp.bzl")
        require("echo '-maybe-dirty'" in original, "Kleaf stamp implementation changed")
        write(kleaf / "kleaf/impl/stamp.bzl", original.replace("echo '-maybe-dirty'", "echo '" + self.c["STOCK_SCMVERSION"] + "'") + "\n")
        original = git(kleaf, "show", "HEAD:kleaf/common_kernels.bzl")
        anchor = '                "BUILD.bazel",'
        require(anchor in original, "Kleaf source filegroup changed")
        # Gradle/Cargo output beneath the nested checkout must not become
        # multi-gigabyte kernel inputs or invalidate every kernel action.
        write(kleaf / "kleaf/common_kernels.bzl", original.replace(anchor,
              '                "KernelSU-Next/manager/**",\n'
              '                "KernelSU-Next/userspace/**",\n' + anchor, 1) + "\n")

    def prepared(self):
        self.owned()
        self.verify_sources()
        state = self.work / ".husky-prepared.json"
        require(state.exists() and json.loads(state.read_text()) == self.c, "Pins changed: run prepare")

    def kernel(self):
        self.prepared()
        self.configure()
        identity = self.kernel_identity()
        run(self.work / "tools/bazel", "build", "--config=fast", "--lto=" + self.c["LTO_MODE"],
            "--action_env=TMPDIR=/tmp", "--disk_cache=" + str(self.work / ".bazel-cache"),
            "//common:kernel_aarch64", cwd=self.work, env={**os.environ, "TMPDIR": "/tmp"})
        require((self.work / "bazel-bin/common/kernel_aarch64/Image").exists(), "No kernel Image produced")
        self.verify_kernel()
        write(self.work / ".husky-kernel.json", json.dumps({"identity": identity, "image": sha(self.work / "bazel-bin/common/kernel_aarch64/Image")}))

    def kernel_identity(self):
        sources = [json.dumps(self.c, sort_keys=True), (ROOT / "configs/husky.fragment").read_text(),
                   git(self.common, "diff", "--binary"), git(self.ksu, "diff", "--binary", "--", "kernel"),
                   git(self.work / "build/kernel", "diff", "--binary")]
        return hashlib.sha256("\n".join(sources).encode()).hexdigest()

    def verify_kernel(self):
        config = self.work / "bazel-bin/common/kernel_aarch64_config/out_dir/.config"
        lines = set(config.read_text().splitlines())
        for key in ["KSU", "KSU_SUSFS", "ZEROMOUNT", "VPNHIDE", "VPNHIDE_FS_HIDING", "MODVERSIONS", "LTO_CLANG_THIN"]:
            require("CONFIG_" + key + "=y" in lines, "Missing built config: " + key)
        require("# CONFIG_MODULE_SIG_PROTECT is not set" in lines, "Stock modules would be blocked")
        kernel = (self.ksu / "kernel/Kbuild").read_text()
        require(self.c["MANAGER_CERT"] in kernel and self.c["MANAGER_PACKAGE"] in kernel, "Manager trust is missing")
        image = (self.work / "bazel-bin/common/kernel_aarch64/Image").read_bytes()
        require(self.c["MANAGER_CERT"].encode() in image, "Built Image does not contain the manager certificate")

    def builtin(self):
        self.prepared()
        env = os.environ.copy()
        ndk = str(Path(self.c["ANDROID_HOME"]) / "ndk" / self.c["NDK_VERSION"])
        env.update({key: ndk for key in ["NDK_HOME", "ANDROID_NDK_HOME", "ANDROID_NDK_ROOT"]})
        run("uv", "run", "--no-project", "builtin/build.py", "--out", self.work / "vpnhide-builtin.zip",
            cwd=self.work / "vpnhide", env=env)

    def manager(self):
        self.prepared()
        env = os.environ.copy()
        for key in ["JAVA_HOME", "ANDROID_HOME"]:
            env[key] = self.c[key]
        ndk = str(Path(self.c["ANDROID_HOME"]) / "ndk" / self.c["NDK_VERSION"])
        env.update({key: ndk for key in ["NDK_HOME", "ANDROID_NDK_HOME", "ANDROID_NDK_ROOT"]})
        run("cargo", "ndk", "-t", "arm64-v8a", "--platform", self.c["ANDROID_API"], "build", "--release", "--locked",
            cwd=self.ksu / "userspace/ksud", env=env)
        manager = self.ksu / "manager"
        generated_aidl = manager / "app/src/main/aidl" / self.c["MANAGER_PACKAGE"].replace(".", "/")
        if generated_aidl.exists():
            shutil.rmtree(generated_aidl)
        # Regenerate text from Git; binary assets and build artifacts are never rewritten.
        for name in git(self.ksu, "ls-files", "manager").splitlines():
            if (self.ksu / name).is_symlink():
                continue
            raw = subprocess.check_output(["git", "-C", str(self.ksu), "show", self.c["KSU_NEXT_REV"] + ":" + name])
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if "\0" in text:
                continue
            for a, b in [("com.rifsxd.ksunext", self.c["MANAGER_PACKAGE"]),
                         ("com/rifsxd/ksunext", self.c["MANAGER_PACKAGE"].replace(".", "/")),
                         ("com_rifsxd_ksunext", self.c["MANAGER_PACKAGE"].replace(".", "_"))]:
                text = text.replace(a, b)
            if name == "manager/app/build.gradle.kts":
                text = text.replace('versionName = rootProject.extra["managerVersionName"] as String', 'versionName = "${managerVersionName}-spoofed"')
            if name == "manager/gradle/libs.versions.toml":
                text = re.sub(r'^ndk = ".*"$', 'ndk = "' + self.c["MANAGER_NDK_VERSION"] + '"', text, flags=re.M)
            write(self.ksu / name, text)
        original_aidl = manager / "app/src/main/aidl/com/rifsxd/ksunext"
        generated_aidl.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(original_aidl, generated_aidl)
        binary = self.ksu / "userspace/ksud/target/aarch64-linux-android/release/ksud"
        libs = manager / "app/src/main/jniLibs/arm64-v8a"
        libs.mkdir(parents=True, exist_ok=True)
        shutil.copy2(binary, libs / "libksud.so")
        props = {}
        for line in Path(self.c["SIGNING_PROPERTIES"]).read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                props[key] = value
        env["SIGNING_PASSWORD"] = props["password"]
        cert = subprocess.check_output([str(Path(env["JAVA_HOME"]) / "bin/keytool"), "-exportcert", "-keystore",
                                        props["storeFile"], "-alias", props["keyAlias"], "-storepass:env", "SIGNING_PASSWORD"], env=env)
        require(hex(len(cert)) + ":" + hashlib.sha256(cert).hexdigest() == self.c["MANAGER_CERT"], "Signing certificate differs from kernel trust")
        for key, value in {"KEYSTORE_FILE": props["storeFile"], "KEYSTORE_PASSWORD": props["password"],
                           "KEY_ALIAS": props["keyAlias"], "KEY_PASSWORD": props["password"]}.items():
            env["ORG_GRADLE_PROJECT_" + key] = value
        run("./gradlew", "--no-daemon", "assembleRelease", cwd=manager, env=env)
        self.verify_apk()

    def verify_apk(self):
        outputs = self.ksu / "manager/app/build/outputs/apk/release"
        metadata = json.loads((outputs / "output-metadata.json").read_text())
        require(metadata["applicationId"] == self.c["MANAGER_PACKAGE"], "APK package mismatch")
        element = metadata["elements"][0]
        expected = 30000 + int(git(self.ksu, "rev-list", "--count", self.c["KSU_VERSION_BASE_REV"]))
        require(element["versionCode"] == expected, "APK version mismatch")
        require(element["versionName"].endswith("-spoofed"), "APK version missing spoof suffix")
        apk = outputs / element["outputFile"]
        tool = Path(self.c["ANDROID_HOME"]) / "build-tools" / self.c["BUILD_TOOLS_VERSION"] / "apksigner"
        env = os.environ.copy()
        env["JAVA_HOME"] = self.c["JAVA_HOME"]
        info = run(tool, "verify", "--verbose", "--print-certs", apk, env=env, capture=True)
        require("Verified using v2 scheme (APK Signature Scheme v2): true" in info, "APK lacks a valid v2 signature")
        for scheme in ["v3", "v3.1"]:
            require(f"Verified using {scheme} scheme (APK Signature Scheme {scheme}): false" in info,
                    "KSU's APK parser requires a v2-only signing block")
        require("Verified for SourceStamp: false" in info and "Number of signers: 1" in info,
                "Unsupported APK signing block layout")
        require(self.c["MANAGER_CERT"].split(":")[1] in info, "APK signed by wrong certificate")
        with zipfile.ZipFile(apk) as archive:
            require("lib/arm64-v8a/libksud.so" in archive.namelist(), "Missing arm64 ksud")
        print("Verified APK:", apk, flush=True)
        return apk

    def package(self):
        self.prepared()
        self.verify_kernel()
        stamp_file = self.work / ".husky-kernel.json"
        require(stamp_file.exists(), "Build the kernel before packaging")
        built = json.loads(stamp_file.read_text())
        require(built["identity"] == self.kernel_identity(), "Kernel inputs changed after build")
        require(built["image"] == sha(self.work / "bazel-bin/common/kernel_aarch64/Image"), "Kernel Image changed after verification")
        apk = self.verify_apk()
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dest = ROOT / "dist" / (stamp + "-" + self.c["KSU_NEXT_REV"][:12])
        dest.mkdir(parents=True)
        output = self.work / "bazel-bin/common/kernel_aarch64"
        for name in ["Image", "System.map", "Module.symvers"]:
            shutil.copy2(output / name, dest / name)
        shutil.copy2(apk, dest / "KernelSU-Next-husky.apk")
        shutil.copy2(self.ksu / "userspace/ksud/target/aarch64-linux-android/release/ksud", dest / "ksud")
        shutil.copy2(ROOT / "versions.env", dest / "versions.env")
        shutil.copy2(ROOT / "manifests/aosp.xml", dest / "aosp.xml")
        shutil.copy2(ROOT / "configs/husky.fragment", dest / "husky.fragment")
        shutil.copy2(self.work / "bazel-bin/common/kernel_aarch64_config/out_dir/.config", dest / "kernel.config")
        shutil.copy2(self.work / "vpnhide-builtin.zip", dest / "vpnhide-builtin.zip")
        with zipfile.ZipFile(dest / "husky-kernel.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
            ak = self.work / "anykernel"
            for name in git(ak, "ls-files").splitlines():
                if name.startswith(".git") or name == "anykernel.sh":
                    continue
                path = ak / name
                if path.is_file():
                    archive.write(path, name)
            archive.write(ROOT / "configs/anykernel.sh", "anykernel.sh")
            archive.write(dest / "Image", "Image")
        write(dest / "SHA256SUMS", "".join(sha(p) + "  " + p.name + "\n" for p in sorted(dest.iterdir()) if p.is_file()))
        write(self.work / ".husky-release", str(dest) + "\n")
        print("Release:", dest, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["adopt", "sync", "sync-components", "prepare", "kernel", "manager", "builtin", "verify-apk", "verify-kernel", "package", "release"])
    parser.add_argument("work", nargs="?", default=str(ROOT / "build"))
    args = parser.parse_args()
    forge = Forge(args.work)
    for command in (["prepare", "kernel", "manager", "builtin", "package"] if args.command == "release" else [args.command.replace("-", "_")]):
        getattr(forge, command)()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print("error:", error, file=sys.stderr)
        sys.exit(1)
