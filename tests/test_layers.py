import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from layers import susfs_compatibility, vendor_headers


class LayerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.put("fs/namespace.c", '#include "internal.h"\n#include <trace/hooks/blk.h>\n')
        self.put("fs/super.c", '#include "internal.h"\n#include <trace/hooks/fs.h>\n\nbody\n')

    def put(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_vendor_headers_are_restored_once(self):
        vendor_headers(self.root, "prepare")
        self.assertNotIn("trace/hooks", (self.root / "fs/super.c").read_text())
        vendor_headers(self.root, "restore")
        self.assertEqual((self.root / "fs/super.c").read_text().count("trace/hooks/fs.h"), 1)
        with self.assertRaisesRegex(RuntimeError, "unexpectedly present"):
            vendor_headers(self.root, "restore")

    def test_nonblank_line_after_vendor_header_is_not_deleted(self):
        self.put("fs/super.c", '#include "internal.h"\n#include <trace/hooks/fs.h>\nimportant();\n')
        original = (self.root / "fs/namespace.c").read_text()
        with self.assertRaisesRegex(RuntimeError, "expected one anchor"):
            vendor_headers(self.root, "prepare")
        self.assertEqual((self.root / "fs/namespace.c").read_text(), original)
        self.assertIn("important();", (self.root / "fs/super.c").read_text())

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
