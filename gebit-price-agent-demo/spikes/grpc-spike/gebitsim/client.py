"""Generic gRPC client for the GEBIT service, stubs created from the same runtime pool."""
from __future__ import annotations

import grpc
from google.protobuf import json_format

from .descriptors import PURCHASE_SVC, Types


class GebitClient:
    def __init__(self, channel: grpc.Channel, types: Types, service: str = PURCHASE_SVC):
        self.types = types
        svc = types.pool.FindServiceByName(service)
        self._stubs = {}
        self._req = {}
        for m in svc.methods:
            req_cls = types.cls(m.input_type.full_name)
            resp_cls = types.cls(m.output_type.full_name)
            self._req[m.name] = req_cls
            self._stubs[m.name] = channel.unary_unary(
                f"/{svc.full_name}/{m.name}",
                request_serializer=req_cls.SerializeToString,
                response_deserializer=resp_cls.FromString,
                _registered_method=True)

    def call(self, method: str, body: dict | None = None, timeout: float = 5.0, **kw):
        """body = proto3 JSON (camelCase or snake_case), like `grpcurl -d`."""
        req = self._req[method]()
        json_format.ParseDict(body or {}, req)
        return self._stubs[method](req, timeout=timeout, **kw)
