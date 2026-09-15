"""Checked source transformations for husky's Android 14 / Linux 6.1 layers.

These are deliberately not a generic compatibility fixer for arbitrary kernels.
Unknown source shapes fail before this layer writes any file.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def commit_changes(common: Path, originals: dict[str, str], changes: dict[str, str]) -> list[dict]:
    # Validate all inputs before writing the first file. The managed build tree
    # is disposable; prepare can be rerun after I/O failure.
    for name, original in originals.items():
        if (common / name).read_text() != original:
            raise RuntimeError(f"Layer input changed: {name}")
    result = []
    for name, updated in changes.items():
        (common / name).write_text(updated)
        result.append(
            {
                "file": name,
                "before_sha256": hashlib.sha256(originals[name].encode()).hexdigest(),
                "after_sha256": hashlib.sha256(updated.encode()).hexdigest(),
            }
        )
    return result


def vendor_headers(common: Path, phase: str) -> list[dict]:
    """Normalize the two vendor headers around the pinned SUSFS patch."""
    if phase not in {"prepare", "restore"}:
        raise ValueError(f"Unknown vendor-header phase: {phase}")
    sources = {
        "fs/namespace.c": "#include <trace/hooks/blk.h>\n",
        "fs/super.c": "#include <trace/hooks/fs.h>\n",
    }
    originals = {name: (common / name).read_text() for name in sources}
    changes = {}
    for name, header in sources.items():
        text = originals[name]
        if phase == "prepare":
            # The former sed command deleted the following line in super.c
            # unconditionally. Require that line to be blank instead.
            anchor = header + ("\n" if name == "fs/super.c" else "")
            changes[name] = replace_once(text, anchor, "", name)
        else:
            if header in text:
                raise RuntimeError(f"Vendor header unexpectedly present during restore: {name}")
            anchor = '#include "internal.h"\n'
            changes[name] = replace_once(text, anchor, anchor + header, name)
    return commit_changes(common, originals, changes)


def susfs_compatibility(common: Path) -> list[dict]:
    """Apply the needed 6.1 label fix; reject obsolete compatibility shapes."""
    makefile = (common / "Makefile").read_text()
    if not (
        re.search(r"^VERSION\s*=\s*6$", makefile, re.M)
        and re.search(r"^PATCHLEVEL\s*=\s*1$", makefile, re.M)
    ):
        raise RuntimeError("SUSFS compatibility rules require Linux 6.1")
    names = [
        "fs/proc/task_mmu.c",
        "fs/notify/fdinfo.c",
        "fs/susfs.c",
        "include/linux/fs.h",
    ]
    originals = {name: (common / name).read_text() for name in names}
    fdinfo = originals["fs/notify/fdinfo.c"]
    if "u32 mask = mark->mask & IN_ALL_EVENTS;" in fdinfo:
        raise RuntimeError("Unexpected legacy inotify mask declaration")
    if re.search(r"^\s*out_seq_printf:\s*$", fdinfo, re.M):
        raise RuntimeError("Unexpected SUSFS label without a statement")
    if "inotify_mark_user_mask(mark)" in fdinfo:
        sources = "\n".join(
            p.read_text() for p in (common / "fs/notify").rglob("*") if p.suffix in {".c", ".h"}
        )
        if not re.search(r"(?:static[^\n]*|^u32 )inotify_mark_user_mask", sources, re.M):
            raise RuntimeError(
                "inotify_mark_user_mask definition missing; review the new kernel API"
            )
    if (
        "i_uid_into_mnt" in originals["fs/susfs.c"]
        and "i_user_ns" not in originals["include/linux/fs.h"]
    ):
        raise RuntimeError("SUSFS inode UID API differs from the supported 6.1 tree")
    name = "fs/proc/task_mmu.c"
    text = originals[name]
    already = "show_pad: __attribute__((__unused__));\n"
    if already in text:
        return []
    updated = replace_once(text, "show_pad:\n", already, name)
    return commit_changes(common, originals, {name: updated})
