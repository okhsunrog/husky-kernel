import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ZeroMountReaddirTests(unittest.TestCase):
    def test_production_directory_cursor_and_actor(self):
        # Compile the actual source added by the maintained kernel patch, not
        # a Python reimplementation of its position handling.
        patch = (ROOT / "patches/local/10_zeromount-readdir.patch").read_text()
        section = patch.split("+++ b/fs/zeromount_readdir.c\n", 1)[1]
        source = (
            "\n".join(
                line[1:]
                for line in section.splitlines()
                if line.startswith("+") and not line.startswith("+++")
            )
            + "\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "zeromount_readdir.c").write_text(source)
            includes = root / "linux"
            includes.mkdir()
            for name in ["fs", "compat", "sched", "zeromount"]:
                (includes / f"{name}.h").write_text("/* Host test shim is in the harness. */\n")
            binary = root / "readdir-test"
            subprocess.run(
                [
                    os.environ.get("CC", "cc"),
                    "-std=c11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-fsanitize=address,undefined",
                    "-fno-omit-frame-pointer",
                    "-g",
                    "-I",
                    str(root),
                    str(ROOT / "tests/zeromount_readdir_test.c"),
                    "-o",
                    str(binary),
                ],
                check=True,
            )
            subprocess.run([str(binary)], check=True)
