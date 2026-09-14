import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from device import Device
from forge import sha


class DeviceSafetyTests(unittest.TestCase):
    def fixture(self, root):
        image = root / "boot-before.img"
        image.write_bytes(b"boot image")
        info = {"serial": "test", "slot": "_a", "fingerprint": "build", "boot_sha256": sha(image)}
        (root / "backup.json").write_text(json.dumps(info))
        device = Device("test")
        device.validate = Mock(return_value="_a")
        device.adb = Mock(return_value="build")
        device.root = Mock(return_value=str(image.stat().st_size))
        device.backup = Mock(side_effect=AssertionError("must reject before backup/write"))
        return device, info

    def test_rollback_rejects_wrong_slot_device_build_or_corruption(self):
        for field, value in [("slot", "_b"), ("serial", "other"), ("fingerprint", "old-build"), ("boot_sha256", "0" * 64)]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                device, info = self.fixture(root)
                info[field] = value
                (root / "backup.json").write_text(json.dumps(info))
                with self.assertRaises(RuntimeError):
                    device.rollback(root)
                device.backup.assert_not_called()
                self.assertFalse(any("dd " in str(call) for call in device.root.call_args_list))

    def test_flash_rejects_incomplete_manifest_before_device_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "SHA256SUMS").write_text("")
            device = Device("test")
            device.backup = Mock()
            with self.assertRaisesRegex(RuntimeError, "omits"):
                device.flash(root)
            device.backup.assert_not_called()

    def test_rollback_checks_upload_and_partition_before_writing(self):
        for changed in [False, True]:
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                device, info = self.fixture(root)
                current = root / "current"
                current.mkdir()
                (current / "backup.json").write_text(json.dumps({"stage": "/data/local/tmp/test", "boot_sha256": "current"}))
                device.backup = Mock(return_value=current)
                responses = [str((root / "boot-before.img").stat().st_size), info["boot_sha256"],
                             "changed" if changed else "current", "", info["boot_sha256"]]
                device.root = Mock(side_effect=responses)
                if changed:
                    with self.assertRaisesRegex(RuntimeError, "changed after backup"):
                        device.rollback(root)
                else:
                    device.rollback(root)
                writes = [call for call in device.root.call_args_list if "dd " in str(call)]
                self.assertEqual(len(writes), 0 if changed else 1)
