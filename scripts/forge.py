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
import tempfile
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


def file_identity(path):
    """Include symlink destinations and executable bits, without following links."""
    if path.is_symlink():
        return ["link", os.readlink(path)]
    if not path.exists():
        return ["missing"]
    return ["file", path.stat().st_mode & 0o777, sha(path)]


def repo_identity(path, scope=None, exclude=()):
    # HEAD-relative diff includes staged edits. Untracked integration sources
    # are absent from git diff, but participate in the kernel build.
    args = ["--", scope] if scope else []
    diff = git(path, "diff", "HEAD", "--binary", *args)
    names = git(path, "ls-files", "--others", "--exclude-standard", "-z", *args)
    extra = {}
    for name in filter(None, names.split("\0")):
        if not any(name == p or name.startswith(p + "/") for p in exclude):
            target = path / name
            if not target.is_dir() or target.is_symlink():
                extra[name] = file_identity(target)
    return {"head": git(path, "rev-parse", "HEAD"), "diff": diff, "added": extra}


class Forge:
    def __init__(self, work):
        self.work = Path(work).resolve()
        self.c = read_config()
        self.common = self.work / "common"
        self.ksu = self.common / "KernelSU-Next"

    def recipe_identity(self):
        inputs = [ROOT / "versions.env"]
        for folder in ["scripts", "configs", "patches", "manifests"]:
            inputs.extend(p for p in (ROOT / folder).rglob("*")
                          if p.is_file() and "__pycache__" not in p.parts)
        values = {str(p.relative_to(ROOT)): file_identity(p) for p in sorted(inputs)}
        return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()

    def logged(self, label, *args, cwd=None):
        result = subprocess.run([str(a) for a in args], cwd=cwd, text=True,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, env={**os.environ, "LC_ALL": "C"})
        print(result.stdout, end="", flush=True)
        self.report["steps"].append({"name": label, "exit_code": result.returncode,
                                     "output": result.stdout,
                                     "adjustments": [s for s in result.stdout.splitlines()
                                                     if re.search(r"\b(offset|fuzz)\b", s)]})
        write(self.work / "patch-report.json", json.dumps(self.report, indent=2) + "\n")
        require(result.returncode == 0, f"{label} failed; see {self.work / 'patch-report.json'}")

    def integrate_vpnhide(self):
        """Run the existing integrator on a small staging tree before copying outputs."""
        source = self.work / "vpnhide"
        kmi = re.match(r"android\d+-\d+\.\d+", self.c["GKI_BRANCH"])[0]
        integrator = source / "builtin/scripts/integrate.py"
        if integrator.is_file():
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            review = self.work / "vpnhide-reviews" / stamp
            self.report["vpnhide_review"] = str(review)
            self.logged("vpnhide Python integration", "uv", "run", integrator, "apply",
                        "--kernel", self.common, "--kmi", kmi, "--output", review)
            return
        # Compatibility with existing pinned releases. Drop this adapter once
        # versions.env advances to the Python integrator's published revision.
        patches = sorted((source / "builtin/versions" / kmi).glob("*.patch"))
        require(patches, f"No vpnhide patches for {kmi}")
        paths = {"security/Kconfig", "security/Makefile"}
        for patch in patches:
            targets = re.findall(r"^(?:---|\+\+\+) ([^\t\n]+)", patch.read_text(), re.M)
            require(targets, f"No file headers in {patch}")
            for name in targets:
                # Fail closed if a future format introduces renames, new files,
                # quoted paths or traversal: update this adapter deliberately.
                require(name.startswith(("a/", "b/")), f"Unsupported patch path: {name}")
                name = name[2:]
                require(not Path(name).is_absolute() and ".." not in Path(name).parts
                        and not any(c.isspace() for c in name), f"Unsafe patch path: {name}")
                paths.add(name)
        with tempfile.TemporaryDirectory(prefix="husky-vpnhide-") as temp:
            stage = Path(temp)
            for name in paths:
                src = self.common / name
                require(src.is_file() and not src.is_symlink(), f"Missing regular patch input: {name}")
                (stage / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, stage / name)
            (stage / "include/linux").mkdir(parents=True, exist_ok=True)
            self.logged("vpnhide staged integration", "bash", source / "builtin/scripts/apply.sh", stage, kmi)
            # No kernel source is modified if any patch fails in staging.
            for path in stage.rglob("*"):
                if path.is_file():
                    target = self.common / path.relative_to(stage)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)

    def local_patches(self):
        series = ROOT / "patches/local/series"
        seen = set()
        for line in series.read_text().splitlines():
            name = line.split("#", 1)[0].strip()
            if not name:
                continue
            path = (series.parent / name).resolve()
            require(path.is_relative_to(series.parent.resolve()) and path.is_file(),
                    f"Invalid local patch: {name}")
            require(path not in seen, f"Duplicate local patch: {name}")
            seen.add(path)
            # Remember added files even when a later hunk fails, so the next
            # prepare can remove generated additions from a previous series.
            inventory = self.work / ".husky-local-files.json"
            added = set(json.loads(inventory.read_text())) if inventory.exists() else set()
            for added_name in re.findall(r"^--- /dev/null\n\+\+\+ b/([^\t\n]+)", path.read_text(), re.M):
                require(not Path(added_name).is_absolute() and ".." not in Path(added_name).parts,
                        "Unsafe added patch path")
                require(not git(self.common, "ls-files", "--", added_name), "Added patch file is already tracked")
                require(not (self.common / added_name).exists(), "Added patch file already exists: " + added_name)
                added.add(added_name)
            write(inventory, json.dumps(sorted(added)))
            self.logged("local: " + name, "patch", "--batch", "--forward", "-p1", "-F0",
                        "--no-backup-if-mismatch", "-i", path, cwd=self.common)

    def doctor(self):
        """Read-only preflight; failures are collected instead of stopping early."""
        failures = []

        def check(label, action):
            try:
                action()
                print("OK  " + label)
            except (RuntimeError, OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
                failures.append(label)
                print(f"FAIL {label}: {error}")

        for tool in ["git", "repo", "uv", "bash", "patch", "cargo", "rustup", "adb"]:
            check(tool, lambda tool=tool: require(shutil.which(tool), "not on PATH"))
        check("cargo-ndk", lambda: run("cargo", "ndk", "--version", capture=True))
        check("Rust Android target", lambda: require("aarch64-linux-android" in run(
            "rustup", "target", "list", "--installed", capture=True), "install aarch64-linux-android"))
        sdk = Path(self.c["ANDROID_HOME"])
        paths = [Path(self.c["JAVA_HOME"]) / "bin/java", Path(self.c["JAVA_HOME"]) / "bin/keytool",
                 sdk / "build-tools" / self.c["BUILD_TOOLS_VERSION"] / "apksigner"]
        paths.extend(sdk / "ndk" / self.c[key] / "toolchains/llvm/prebuilt/linux-x86_64/bin/clang"
                     for key in ["NDK_VERSION", "MANAGER_NDK_VERSION"])
        for path in paths:
            check(str(path), lambda path=path: require(path.is_file() and os.access(path, os.X_OK), "missing executable"))
        check("managed tree", self.owned)
        check("pinned source revisions", self.verify_sources)
        check("signing identity", self.signing_properties)
        free = shutil.disk_usage(self.work if self.work.exists() else ROOT).free // (1024 ** 3)
        print(f"INFO free space: {free} GiB (allow at least 30 GiB for a fresh build/cache)")
        require(not failures, "Preflight failed: " + ", ".join(failures))

    def signing_properties(self):
        props = {}
        for line in Path(self.c["SIGNING_PROPERTIES"]).read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                props[key] = value
        env = {**os.environ, "SIGNING_PASSWORD": props["password"]}
        cert = subprocess.check_output([str(Path(self.c["JAVA_HOME"]) / "bin/keytool"), "-exportcert", "-keystore",
                                        props["storeFile"], "-alias", props["keyAlias"], "-storepass:env", "SIGNING_PASSWORD"], env=env)
        require(hex(len(cert)) + ":" + hashlib.sha256(cert).hexdigest() == self.c["MANAGER_CERT"],
                "Signing certificate differs from kernel trust")
        return props

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
        projects = ET.parse(ROOT / "manifests/aosp.xml").getroot().findall("project")
        require(next(p.attrib["revision"] for p in projects if p.attrib["path"] == "common") == self.c["GKI_REV"],
                "GKI_REV differs from the AOSP manifest")
        for key, value in self.c.items():
            if key.endswith("_REV"):
                require(re.fullmatch(r"[0-9a-f]{40}", value), f"{key} must be a full commit SHA")
        for p in projects:
            require(git(self.work / p.attrib["path"], "rev-parse", "HEAD") == p.attrib["revision"],
                    f"AOSP revision mismatch: {p.attrib['path']}")
        for path, key in [(self.ksu, "KSU_NEXT_REV"), (self.work / "susfs4ksu", "SUSFS_REV"),
                          (self.work / "vpnhide", "VPNHIDE_REV"), (self.work / "anykernel", "ANYKERNEL_REV")]:
            require(git(path, "rev-parse", "HEAD") == self.c[key], f"Revision mismatch: {path}")
            if path != self.ksu:
                require(not git(path, "status", "--porcelain", "--untracked-files=normal"),
                        f"Modified component inputs: {path}; preserve edits in its development checkout")

    def prepare(self):
        self.owned()
        (self.work / ".husky-prepared.json").unlink(missing_ok=True)
        self.report = {"pins": self.c, "recipe": self.recipe_identity(), "steps": []}
        run("git", "-C", self.common, "reset", "--hard", self.c["GKI_REV"])
        self.verify_sources()
        inventory = self.work / ".husky-local-files.json"
        if inventory.exists():
            for name in json.loads(inventory.read_text()):
                path = self.common / name
                require(path.resolve().is_relative_to(self.common) and not git(self.common, "ls-files", "--", name),
                        "Unsafe generated file inventory: " + name)
                path.unlink(missing_ok=True)
            inventory.unlink()
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
        self.logged("susfs prepare", "bash", ROOT / "patches/susfs/fake-patch.sh", "prepare", self.common)
        self.logged("susfs patch", "patch", "--batch", "-p1", "-F3", "--no-backup-if-mismatch", "-i",
            self.work / "susfs4ksu/kernel_patches/50_add_susfs_in_gki-android14-6.1.patch", cwd=self.common)
        self.logged("susfs restore", "bash", ROOT / "patches/susfs/fake-patch.sh", "restore", self.common)
        sublevel = re.search(r"^SUBLEVEL = (\d+)$", (self.common / "Makefile").read_text(), re.M)
        require(sublevel, "Cannot determine kernel sublevel")
        self.logged("zeromount compatibility", "bash", ROOT / "patches/zeromount/fix-susfs-compat.sh", self.common, sublevel[1], "android14", "6.1", ROOT / "patches")
        self.logged("zeromount patch", "patch", "--batch", "-p1", "-F3", "--no-backup-if-mismatch", "-i",
            ROOT / "patches/zeromount/60_zeromount-android14-6.1.patch", cwd=self.common)
        self.integrate_vpnhide()
        self.local_patches()
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
        write(self.work / ".husky-recipe", self.recipe_identity())

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
        recipe = self.work / ".husky-recipe"
        require(recipe.exists() and recipe.read_text() == self.recipe_identity(), "Recipe changed: run prepare")

    def kernel(self):
        self.prepared()
        self.configure()
        identity = self.kernel_identity()
        run(self.work / "tools/bazel", "build", "--config=fast", "--lto=" + self.c["LTO_MODE"],
            "--action_env=TMPDIR=/tmp", "--disk_cache=" + str(self.work / ".bazel-cache"),
            "//common:kernel_aarch64", cwd=self.work, env={**os.environ, "TMPDIR": "/tmp"})
        require((self.work / "bazel-bin/common/kernel_aarch64/Image").exists(), "No kernel Image produced")
        self.verify_kernel()
        require(identity == self.kernel_identity(), "Kernel inputs changed during build")
        write(self.work / ".husky-kernel.json", json.dumps({"identity": identity, "image": sha(self.work / "bazel-bin/common/kernel_aarch64/Image")}))

    def kernel_identity(self):
        sources = {"config": self.c, "recipe": self.recipe_identity(),
                   "common": repo_identity(self.common, exclude=("KernelSU-Next",)),
                   "ksu": repo_identity(self.ksu, scope="kernel"),
                   "kleaf": repo_identity(self.work / "build/kernel")}
        # Some copied C/H files match Git ignore rules; explicitly cover the
        # integration destinations too, including generated shared headers.
        integrated = [self.common / "fs/zeromount.c", self.common / "include/linux/zeromount.h",
                      self.common / "include/linux/vpnhide.h", self.common / "drivers/kernelsu"]
        integrated.extend(p for p in (self.common / "security/vpnhide").rglob("*") if p.is_file())
        for folder in ["fs", "include/linux"]:
            integrated.extend(self.common / folder / p.name
                              for p in (self.work / "susfs4ksu/kernel_patches" / folder).iterdir())
        sources["integrated"] = {str(p.relative_to(self.common)): file_identity(p) for p in integrated}
        return hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()

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
        props = self.signing_properties()
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
        shutil.copy2(self.work / "patch-report.json", dest / "patch-report.json")
        shutil.copy2(stamp_file, dest / "kernel-inputs.json")
        report = json.loads((self.work / "patch-report.json").read_text())
        if review := report.get("vpnhide_review"):
            with zipfile.ZipFile(dest / "vpnhide-review.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(Path(review).rglob("*")):
                    if path.is_file():
                        archive.write(path, path.relative_to(review))
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
    parser.add_argument("command", choices=["doctor", "adopt", "sync", "sync-components", "prepare", "kernel", "manager", "builtin", "verify-apk", "verify-kernel", "package", "release"])
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
