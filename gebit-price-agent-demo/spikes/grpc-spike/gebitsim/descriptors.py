"""Build a DescriptorPool at runtime from GEBIT FileDescriptorSet (.pb) files.

No generated *_pb2 stubs: the .pb files are mounted at runtime (ConfigMap /
volume) and the message classes are created from the pool.
"""
from __future__ import annotations

import os
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

PURCHASE_SVC = "de.gebit.rp.purchase.purchase.v2.service.PurchaseTransactionService"
EVENT_PKG = "de.gebit.rp.purchase.purchase.v2.event"
TYPE_URL_PREFIX = "type.googleapis.com/"


def load_pool(paths: list[str]) -> descriptor_pool.DescriptorPool:
    """Merge one or more descriptor sets into a fresh (non-default) pool.

    - Dedup by file name; the same file in two sets must be byte-identical
      (formatted_content.proto is in both purchase and receipt sets).
    - Add in dependency order (topological), not set order, so merged sets work.
    - A fresh pool avoids clashing with google/protobuf/*.proto already in the
      default pool of this process.
    """
    files: dict[str, descriptor_pb2.FileDescriptorProto] = {}
    for p in paths:
        fds = descriptor_pb2.FileDescriptorSet()
        with open(p, "rb") as fh:
            fds.ParseFromString(fh.read())
        for f in fds.file:
            prev = files.get(f.name)
            if prev is not None and prev.SerializeToString(deterministic=True) != f.SerializeToString(deterministic=True):
                raise ValueError(f"conflicting definitions of {f.name} across descriptor sets")
            files[f.name] = f
    pool = descriptor_pool.DescriptorPool()
    added: set[str] = set()

    def add(name: str) -> None:
        if name in added:
            return
        fdp = files[name]  # KeyError => set was built without --include_imports
        for dep in fdp.dependency:
            add(dep)
        pool.Add(fdp)
        added.add(name)

    for name in files:
        add(name)
    return pool


def default_paths() -> list[str]:
    return [p for p in os.environ.get("GEBIT_DESCRIPTOR_SETS", "").split(os.pathsep) if p]


class Types:
    """Lazy message-class cache on top of a pool."""

    def __init__(self, pool: descriptor_pool.DescriptorPool):
        self.pool = pool
        self._cache: dict[str, type] = {}

    def cls(self, full_name: str):
        c = self._cache.get(full_name)
        if c is None:
            c = message_factory.GetMessageClass(self.pool.FindMessageTypeByName(full_name))
            self._cache[full_name] = c
        return c

    def new(self, full_name: str, **kw):
        return self.cls(full_name)(**kw)

    def event(self, name: str):
        return self.cls(f"{EVENT_PKG}.{name}")()
