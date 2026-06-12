from __future__ import annotations

import os
import pathlib


def golden_base_directory(
    module_file: pathlib.Path,
    golden_root: str,
    rootpath: pathlib.Path,
) -> pathlib.Path:
    """Directory used to resolve relative golden YAML paths."""
    if golden_root:
        root = pathlib.Path(golden_root)
        if not root.is_absolute():
            root = rootpath / root
        return root.resolve()
    return module_file.parent.resolve()


def resolve_golden_file(base: pathlib.Path, relative: os.PathLike[str]) -> pathlib.Path:
    return base / relative
