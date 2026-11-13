import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from layers import susfs_compatibility


class LayerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def put(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def compatibility_fixture(self):
        self.put("Makefile", "VERSION = 6\nPATCHLEVEL = 1\n")
        self.put("fs/proc/task_mmu.c", "show_pad:\n\tshow_map_pad_vma();\n")
        self.put("fs/notify/fdinfo.c", "inotify_mark_user_mask(mark);\n")
        self.put(
            "fs/notify/inotify/inotify.h", "static inline __u32 inotify_mark_user_mask(void);\n"
        )
        self.put("fs/susfs.c", "i_uid_into_mnt();\n")
        self.put("include/linux/fs.h", "i_user_ns();\n")

    def test_compatibility_is_idempotent_and_finds_header_definitions(self):
        self.compatibility_fixture()
        changes = susfs_compatibility(self.root)
        self.assertEqual(len(changes), 1)
        self.assertIn("__unused__", (self.root / "fs/proc/task_mmu.c").read_text())
        self.assertEqual(susfs_compatibility(self.root), [])

    def test_unknown_api_fails_before_changing_label(self):
        self.compatibility_fixture()
        (self.root / "fs/notify/inotify/inotify.h").unlink()
        with self.assertRaisesRegex(RuntimeError, "definition missing"):
            susfs_compatibility(self.root)
        self.assertNotIn("__unused__", (self.root / "fs/proc/task_mmu.c").read_text())
