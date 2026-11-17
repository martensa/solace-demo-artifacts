"""Generic gRPC server for GEBIT PurchaseTransactionService, built from descriptors at runtime.

  GEBIT_DESCRIPTOR_SETS=/descriptors/purchase-api-2.50.0.pb:/descriptors/receipt-api-2.13.0.pb \
  python -m gebitsim.server --port 50051 --events /tmp/events.jsonl
"""
from __future__ import annotations

import argparse
import logging
import time
from concurrent import futures

import grpc
from grpc_health.v1 import health, health_pb2, health_pb2_grpc
from grpc_reflection.v1alpha import reflection, reflection_pb2

from .descriptors import PURCHASE_SVC, Types, default_paths, load_pool
from .events import JsonlSink
from .sim import Simulator

log = logging.getLogger("gebitsim")
REFLECTION_V1 = "grpc.reflection.v1.ServerReflection"


def _unimplemented(name):
    def fn(req, context):
        context.abort(grpc.StatusCode.UNIMPLEMENTED, f"{name} is not simulated")
    return fn


def service_handler(types: Types, impl) -> tuple[grpc.GenericRpcHandler, dict]:
    """One handler for ALL methods of the service, (de)serialisers from the pool."""
    svc = types.pool.FindServiceByName(PURCHASE_SVC)
    handlers, implemented = {}, []
    for m in svc.methods:
        req_cls = types.cls(m.input_type.full_name)
        resp_cls = types.cls(m.output_type.full_name)
        fn = getattr(impl, m.name, None)
        if fn is not None:
            implemented.append(m.name)
        handlers[m.name] = grpc.unary_unary_rpc_method_handler(
            fn or _unimplemented(m.name),
            request_deserializer=req_cls.FromString,
            response_serializer=resp_cls.SerializeToString)
    return grpc.method_handlers_generic_handler(svc.full_name, handlers), {
        "methods": len(svc.methods), "implemented": implemented}


def build_server(pool_paths: list[str], port: int, events_path: str | None, workers: int = 16):
    t0 = time.perf_counter()
    pool = load_pool(pool_paths)
    # reflection + health live in the default pool; add their files to OUR pool so that
    # `grpcurl describe grpc.health.v1.Health` also resolves (both protos have no imports).
    for fd in (reflection_pb2.DESCRIPTOR, health_pb2.DESCRIPTOR):
        pool.AddSerializedFile(fd.serialized_pb)
    types = Types(pool)
    t_pool = time.perf_counter() - t0

    sim = Simulator(types, JsonlSink(events_path))
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=workers))
    handler, info = service_handler(types, sim)
    server.add_generic_rpc_handlers((handler,))

    # server reflection against the runtime pool (v1alpha from grpcio-reflection) ...
    names = [PURCHASE_SVC, health.SERVICE_NAME, reflection.SERVICE_NAME, REFLECTION_V1]
    servicer = reflection.ReflectionServicer(names, pool=pool)
    reflection_pb2_grpc_add(servicer, server)
    # ... plus grpc.reflection.v1 (wire-identical messages, only the service name differs)
    v1 = grpc.stream_stream_rpc_method_handler(
        servicer.ServerReflectionInfo,
        request_deserializer=reflection_pb2.ServerReflectionRequest.FromString,
        response_serializer=reflection_pb2.ServerReflectionResponse.SerializeToString)
    server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler(
        REFLECTION_V1, {"ServerReflectionInfo": v1}),))

    hs = health.HealthServicer()
    hs.set(PURCHASE_SVC, health_pb2.HealthCheckResponse.SERVING)
    hs.set("", health_pb2.HealthCheckResponse.SERVING)
    health_pb2_grpc.add_HealthServicer_to_server(hs, server)

    bound = server.add_insecure_port(f"[::]:{port}")
    info.update(pool_load_s=round(t_pool, 4), port=bound)
    return server, sim, info


def reflection_pb2_grpc_add(servicer, server):
    from grpc_reflection.v1alpha import reflection_pb2_grpc
    reflection_pb2_grpc.add_ServerReflectionServicer_to_server(servicer, server)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=50051)
    ap.add_argument("--events", default=None)
    ap.add_argument("--descriptors", default=None, help="os.pathsep-separated .pb files")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    paths = a.descriptors.split(":") if a.descriptors else default_paths()
    server, _, info = build_server(paths, a.port, a.events)
    server.start()
    log.info("serving %s", info)
    server.wait_for_termination()


if __name__ == "__main__":
    main()
