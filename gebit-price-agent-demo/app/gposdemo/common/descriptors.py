"""Descriptor pools built at runtime from FileDescriptorSets (UC1-BUILD-SPEC 4.1).

No generated ``*_pb2`` code: message classes come from the pool
(``message_factory.GetMessageClass``), as in ``spikes/grpc-spike/gebitsim``.

One pool per API family, never merged: GEBIT (purchase + receipt, mounted at runtime
from ``GEBIT_DESCRIPTOR_SETS``, never in the repo or the image) and Showcase
(wws + loyalty, ``SHOWCASE_DESCRIPTOR_SET`` built from ``proto/``).
"""

from __future__ import annotations

from typing import Any

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from google.protobuf.message import Message

PURCHASE_SVC = "de.gebit.rp.purchase.purchase.v2.service.PurchaseTransactionService"
EVENT_PKG = "de.gebit.rp.purchase.purchase.v2.event"
WWS_SVC = "de.showcase.wws.v1.service.MerchandiseService"
WWS_EVENT_PKG = "de.showcase.wws.v1.event"
LOYALTY_SVC = "de.showcase.loyalty.v1.service.LoyaltyService"
TYPE_URL_PREFIX = "type.googleapis.com/"


def load_pool(paths: list[str]) -> descriptor_pool.DescriptorPool:
    """Merge one or more descriptor sets into a fresh (non-default) pool.

    * Dedup by file name; the same file in two sets must be byte-identical
      (``formatted_content.proto`` is in both GEBIT sets), else ``ValueError``.
    * Files are added in dependency order, not set order.
    * A fresh pool never clashes with ``google/protobuf/*.proto`` of the default pool.

    A ``KeyError`` means a set was built without ``--include_imports``.
    """
    if not paths:
        raise ValueError("no descriptor set given")
    files: dict[str, descriptor_pb2.FileDescriptorProto] = {}
    for path in paths:
        fds = descriptor_pb2.FileDescriptorSet()
        with open(path, "rb") as fh:
            fds.ParseFromString(fh.read())
        for fdp in fds.file:
            prev = files.get(fdp.name)
            if prev is not None and (prev.SerializeToString(deterministic=True)
                                     != fdp.SerializeToString(deterministic=True)):
                raise ValueError(f"conflicting definitions of {fdp.name} across descriptor sets")
            files[fdp.name] = fdp
    pool = descriptor_pool.DescriptorPool()
    added: set[str] = set()

    def add(name: str) -> None:
        if name in added:
            return
        fdp = files[name]
        for dep in fdp.dependency:
            add(dep)
        pool.Add(fdp)
        added.add(name)

    for name in files:
        add(name)
    return pool


class Types:
    """Lazy message-class cache on top of a pool."""

    def __init__(self, pool: descriptor_pool.DescriptorPool):
        self.pool = pool
        self._cache: dict[str, type[Message]] = {}

    def cls(self, full_name: str) -> type[Message]:
        """Message class of ``full_name`` (``KeyError`` if the pool has no such type)."""
        found = self._cache.get(full_name)
        if found is None:
            found = message_factory.GetMessageClass(self.pool.FindMessageTypeByName(full_name))
            self._cache[full_name] = found
        return found

    def new(self, full_name: str, **kw: Any) -> Message:
        """New message of ``full_name`` initialised with ``kw``."""
        return self.cls(full_name)(**kw)

    def event(self, name: str) -> Message:
        """New, empty GEBIT purchase event ``de.gebit.rp.purchase.purchase.v2.event.<name>``."""
        return self.cls(f"{EVENT_PKG}.{name}")()
