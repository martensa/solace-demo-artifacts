"""Build the Showcase descriptor set from ``proto/**`` (UC1-BUILD-SPEC 12.2).

``python -m gposdemo.common.protoc [--out PATH]`` writes ``build/descriptors/showcase.pb``
(default) with the same protoc call as the image stage::

    cd proto && protoc -I . --include_imports --descriptor_set_out=<out> \\
        $(find de -name '*.proto' | sort)

It needs ``grpcio-tools`` (``requirements-dev.txt``); the image builds the set in its
own stage. GEBIT protos are never part of this set.
"""

from __future__ import annotations

import argparse
import os
import sys
from importlib import resources
from pathlib import Path

from .config import local_showcase_set, repo_root


def proto_root() -> Path:
    """``<demo root>/proto`` (include root: imports start with ``de/showcase/...``)."""
    return repo_root() / "proto"


def proto_files(root: Path) -> list[str]:
    """All ``.proto`` files under ``root/de``, relative to ``root``, sorted like ``sort``."""
    return sorted(str(p.relative_to(root)) for p in (root / "de").rglob("*.proto"))


def build_descriptor_set(out: Path, root: Path | None = None) -> Path:
    """Compile every proto under ``root`` (default :func:`proto_root`) into ``out``."""
    from grpc_tools import protoc

    root = root or proto_root()
    files = proto_files(root)
    if not files:
        raise FileNotFoundError(f"no .proto files under {root / 'de'}")
    out.parent.mkdir(parents=True, exist_ok=True)
    well_known = resources.files("grpc_tools") / "_proto"
    # write next to the target and rename: parallel test sessions never read a torn file
    tmp = out.with_name(f".{out.name}.{os.getpid()}.tmp")
    args = ["grpc_tools.protoc", f"-I{root}", f"-I{well_known}", "--include_imports",
            f"--descriptor_set_out={tmp}", *(str(root / f) for f in files)]
    try:
        if protoc.main(args) != 0:
            raise RuntimeError(f"protoc failed for {root}")
        os.replace(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)
    return out


def ensure_local(out: Path | None = None) -> Path:
    """Build the local set when it is missing or older than any proto file; return it."""
    out = out or local_showcase_set()
    root = proto_root()
    newest = max(p.stat().st_mtime for p in (root / "de").rglob("*.proto"))
    if not out.exists() or out.stat().st_mtime < newest:
        build_descriptor_set(out, root)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Showcase descriptor set.")
    parser.add_argument("--out", type=Path, default=local_showcase_set(),
                        help="output file (default: build/descriptors/showcase.pb)")
    args = parser.parse_args(argv)
    path = build_descriptor_set(args.out)
    print(f"wrote {path} ({path.stat().st_size} bytes, {len(proto_files(proto_root()))} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
