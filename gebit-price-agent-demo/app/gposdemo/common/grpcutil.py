"""Generic gRPC server and client on a runtime descriptor pool (UC1-BUILD-SPEC 4.1).

``serve`` registers *every* method of a service from the pool; methods that ``impl``
does not define answer ``UNIMPLEMENTED``. It adds health (``grpc.health.v1``) and
server reflection v1alpha plus v1 with two fixes from G0-07:

1. The upb pool of protobuf 7 cannot resolve method symbols in
   ``FindFileContainingSymbol`` (``KeyError``); reflection falls back to
   ``pool.FindMethodByName(name).containing_service.file``.
2. grpcio-reflection ships only the v1alpha proto; a v1 copy (same messages, package
   ``grpc.reflection.v1``) is added to the pool, so the v1 service can be described.

Errors (4.1, simplified for UC1): status message ``"<CODE>: <text>"`` and trailing
metadata ``gpos-error-code: <CODE>`` via :func:`abort`; codes in 4.5.
"""

from __future__ import annotations

import weakref
from collections.abc import Callable, Mapping, Sequence
from concurrent import futures
from typing import Any, NoReturn

import grpc
from google.protobuf import descriptor_pb2, descriptor_pool, json_format
from google.protobuf.descriptor import MethodDescriptor
from google.protobuf.message import Message
from grpc_health.v1 import health, health_pb2, health_pb2_grpc
from grpc_reflection.v1alpha import reflection, reflection_pb2, reflection_pb2_grpc

from .descriptors import Types

ERROR_CODE_KEY = "gpos-error-code"
REFLECTION_V1 = "grpc.reflection.v1.ServerReflection"
_V1ALPHA_PKG = "grpc.reflection.v1alpha"
_V1_PKG = "grpc.reflection.v1"
MAX_MESSAGE_BYTES = 4 * 1024 * 1024  # = ingress proxy-body-size 4m (G0-07 finding 3)

_bound_ports: weakref.WeakKeyDictionary[grpc.Server, int] = weakref.WeakKeyDictionary()


def abort(context: grpc.ServicerContext, code: grpc.StatusCode, error_code: str,
          text: str) -> NoReturn:
    """End the RPC with ``code``, message ``"<error_code>: <text>"`` and the trailing
    metadata ``gpos-error-code``. Never returns."""
    context.set_trailing_metadata(((ERROR_CODE_KEY, error_code),))
    context.abort(code, f"{error_code}: {text}")


def error_code(err: grpc.RpcError) -> str:
    """``gpos-error-code`` of a failed call (``""`` when the server sent none)."""
    trailing = err.trailing_metadata() if isinstance(err, grpc.Call) else None
    for key, value in trailing or ():
        if key == ERROR_CODE_KEY:
            return str(value)
    return ""


def _unimplemented(name: str) -> Callable[..., Any]:
    def handler(_request: Any, context: grpc.ServicerContext) -> NoReturn:
        context.abort(grpc.StatusCode.UNIMPLEMENTED, f"{name} is not implemented")

    return handler


def _method_handler(method: MethodDescriptor, types: Types, fn: Callable[..., Any]
                    ) -> grpc.RpcMethodHandler:
    req = types.cls(method.input_type.full_name)
    resp = types.cls(method.output_type.full_name)
    kind = {
        (False, False): grpc.unary_unary_rpc_method_handler,
        (False, True): grpc.unary_stream_rpc_method_handler,
        (True, False): grpc.stream_unary_rpc_method_handler,
        (True, True): grpc.stream_stream_rpc_method_handler,
    }[(method.client_streaming, method.server_streaming)]
    return kind(fn, request_deserializer=req.FromString,
                response_serializer=resp.SerializeToString)


def service_handler(pool: descriptor_pool.DescriptorPool, service_full_name: str,
                    impl: object) -> tuple[grpc.GenericRpcHandler, list[str]]:
    """Generic handler for all methods of the service; also returns the implemented names."""
    types = Types(pool)
    svc = pool.FindServiceByName(service_full_name)
    handlers: dict[str, grpc.RpcMethodHandler] = {}
    implemented: list[str] = []
    for method in svc.methods:
        fn = getattr(impl, method.name, None)
        if fn is not None:
            implemented.append(method.name)
        handlers[method.name] = _method_handler(method, types, fn or _unimplemented(method.name))
    return grpc.method_handlers_generic_handler(svc.full_name, handlers), implemented


def _rename_type(name: str) -> str:
    prefix = f".{_V1ALPHA_PKG}."
    return f".{_V1_PKG}." + name[len(prefix):] if name.startswith(prefix) else name


def reflection_v1_file() -> descriptor_pb2.FileDescriptorProto:
    """``grpc/reflection/v1/reflection.proto``: the v1alpha file under package v1."""
    fdp = descriptor_pb2.FileDescriptorProto()
    reflection_pb2.DESCRIPTOR.CopyToProto(fdp)
    fdp.name = "grpc/reflection/v1/reflection.proto"
    fdp.package = _V1_PKG
    fdp.ClearField("options")
    for msg in fdp.message_type:
        for fld in msg.field:
            if fld.HasField("type_name"):  # assigning "" would mark scalars as typed
                fld.type_name = _rename_type(fld.type_name)
    for svc in fdp.service:
        for method in svc.method:
            method.input_type = _rename_type(method.input_type)
            method.output_type = _rename_type(method.output_type)
    return fdp


def _add_file(pool: descriptor_pool.DescriptorPool, fdp: descriptor_pb2.FileDescriptorProto
              ) -> None:
    try:
        pool.FindFileByName(fdp.name)
    except KeyError:
        pool.Add(fdp)


def _add_infrastructure_files(pool: descriptor_pool.DescriptorPool) -> None:
    """Health and reflection protos into OUR pool, so reflection can describe them."""
    for module in (reflection_pb2, health_pb2):
        fdp = descriptor_pb2.FileDescriptorProto()
        module.DESCRIPTOR.CopyToProto(fdp)
        _add_file(pool, fdp)
    _add_file(pool, reflection_v1_file())


class FixedReflectionServicer(reflection.ReflectionServicer):
    """Reflection that also resolves ``Service.Method`` symbols (G0-07 finding 1)."""

    def _file_containing_symbol(self, request: Any, fully_qualified_name: str) -> Any:
        try:
            self._pool.FindFileContainingSymbol(fully_qualified_name)
        except KeyError:
            try:
                method = self._pool.FindMethodByName(fully_qualified_name)
            except KeyError:
                return super()._file_containing_symbol(request, fully_qualified_name)
            return self._file_by_filename(request, method.containing_service.file.name)
        return super()._file_containing_symbol(request, fully_qualified_name)


def _add_reflection(server: grpc.Server, pool: descriptor_pool.DescriptorPool,
                    service_names: Sequence[str]) -> None:
    servicer = FixedReflectionServicer(
        [*service_names, health.SERVICE_NAME, reflection.SERVICE_NAME, REFLECTION_V1], pool=pool)
    reflection_pb2_grpc.add_ServerReflectionServicer_to_server(servicer, server)
    v1 = grpc.stream_stream_rpc_method_handler(
        servicer.ServerReflectionInfo,
        request_deserializer=reflection_pb2.ServerReflectionRequest.FromString,
        response_serializer=reflection_pb2.ServerReflectionResponse.SerializeToString)
    server.add_generic_rpc_handlers(
        (grpc.method_handlers_generic_handler(REFLECTION_V1, {"ServerReflectionInfo": v1}),))


def _add_health(server: grpc.Server, service_full_name: str) -> None:
    servicer = health.HealthServicer()
    servicer.set("", health_pb2.HealthCheckResponse.SERVING)
    servicer.set(service_full_name, health_pb2.HealthCheckResponse.SERVING)
    health_pb2_grpc.add_HealthServicer_to_server(servicer, server)


def serve(pool: descriptor_pool.DescriptorPool, service_full_name: str, impl: object,
          port: int, workers: int = 16) -> grpc.Server:
    """Build and bind (h2c, ``[::]:port``) a server for ``service_full_name``.

    The server is returned **not started**: the service's ``start()`` calls
    ``server.start()``. ``port=0`` binds a free port; read it with :func:`bound_port`.
    """
    _add_infrastructure_files(pool)
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="grpc"),
        options=[("grpc.max_receive_message_length", MAX_MESSAGE_BYTES)])
    handler, _ = service_handler(pool, service_full_name, impl)
    server.add_generic_rpc_handlers((handler,))
    _add_reflection(server, pool, [service_full_name])
    _add_health(server, service_full_name)
    bound = server.add_insecure_port(f"[::]:{port}")
    if bound == 0:
        raise OSError(f"cannot bind gRPC port {port}")
    _bound_ports[server] = bound
    return server


def bound_port(server: grpc.Server) -> int:
    """Port a server from :func:`serve` is bound to (useful with ``port=0``)."""
    return _bound_ports[server]


class Client:
    """Client for one service of a runtime pool (stubs from the same descriptors)."""

    def __init__(self, pool: descriptor_pool.DescriptorPool, service_full_name: str,
                 target: str):
        self.types = Types(pool)
        self.pool = pool
        self.channel = grpc.insecure_channel(
            target, options=[("grpc.max_receive_message_length", MAX_MESSAGE_BYTES)])
        svc = pool.FindServiceByName(service_full_name)
        self._req: dict[str, type[Message]] = {}
        self._stubs: dict[str, grpc.UnaryUnaryMultiCallable] = {}
        for method in svc.methods:
            req = self.types.cls(method.input_type.full_name)
            resp = self.types.cls(method.output_type.full_name)
            self._req[method.name] = req
            self._stubs[method.name] = self.channel.unary_unary(
                f"/{svc.full_name}/{method.name}",
                request_serializer=req.SerializeToString,
                response_deserializer=resp.FromString,
                _registered_method=True)

    def request(self, method: str, body: Mapping[str, Any] | None = None) -> Message:
        """Request message of ``method`` from proto3 JSON (strict, unknown fields fail)."""
        msg = self._req[method]()
        json_format.ParseDict(dict(body or {}), msg, descriptor_pool=self.pool)
        return msg

    def call(self, method: str, body: Mapping[str, Any] | Message | None = None,
             timeout: float = 5.0, metadata: Sequence[tuple[str, str]] | None = None
             ) -> Message:
        """Call ``method``; ``body`` is proto3 JSON (camelCase or snake_case) or a message.

        Raises ``grpc.RpcError``; :func:`error_code` reads the ``gpos-error-code``.
        """
        req = body if isinstance(body, Message) else self.request(method, body)
        return self._stubs[method](req, timeout=timeout, metadata=metadata)

    def call_json(self, method: str, body: Mapping[str, Any] | None = None,
                  timeout: float = 5.0) -> dict[str, Any]:
        """Like :meth:`call`, answer as proto3 JSON dict (``MessageToDict`` defaults)."""
        return json_format.MessageToDict(self.call(method, body, timeout),
                                         descriptor_pool=self.pool)

    def close(self) -> None:
        """Close the channel."""
        self.channel.close()
