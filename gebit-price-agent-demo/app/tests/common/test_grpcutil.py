"""grpcutil: generic server roundtrip with a Showcase service, errors, health, reflection."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import grpc
import pytest
from google.protobuf import descriptor_pb2
from google.protobuf.descriptor_pool import DescriptorPool
from google.protobuf.message import Message
from grpc_health.v1 import health_pb2, health_pb2_grpc
from grpc_reflection.v1alpha import reflection_pb2

from gposdemo.common import grpcutil, money
from gposdemo.common.descriptors import WWS_SVC, Types


class FakeWws:
    """Two RPCs of MerchandiseService; everything else must answer UNIMPLEMENTED."""

    def __init__(self, types: Types):
        self.types = types

    def GetEffectivePrice(self, request: Any, _context: grpc.ServicerContext) -> Message:
        price = self.types.new("de.showcase.wws.v1.datatype.EffectivePrice",
                               article_number=request.article_number,
                               store_id=request.store_id, pct_shown=0)
        price.price.currency = "EUR"
        price.price.amount.scale, price.price.amount.int_val = 2, 999
        return price

    def RequestPriceChange(self, request: Any, context: grpc.ServicerContext) -> Message:
        regular = money.from_money(request.expected_regular_price)
        if money.from_money(request.new_price) >= regular:
            grpcutil.abort(context, grpc.StatusCode.INVALID_ARGUMENT, "WWS-010",
                           "keine Senkung")
        return self.types.new("de.showcase.wws.v1.datatype.PriceActionId",
                              action_id="PA-270216-0003", created=True)


@pytest.fixture(scope="module")
def wws_server(showcase_pool: DescriptorPool) -> Iterator[tuple[grpc.Server, int]]:
    server = grpcutil.serve(showcase_pool, WWS_SVC, FakeWws(Types(showcase_pool)), port=0,
                            workers=4)
    server.start()
    yield server, grpcutil.bound_port(server)
    server.stop(grace=None)


@pytest.fixture
def client(showcase_pool: DescriptorPool, wws_server: tuple[grpc.Server, int]
           ) -> Iterator[grpcutil.Client]:
    c = grpcutil.Client(showcase_pool, WWS_SVC, f"localhost:{wws_server[1]}")
    yield c
    c.close()


def test_roundtrip_json(client: grpcutil.Client) -> None:
    answer = client.call_json("GetEffectivePrice", {"articleNumber": "100001",
                                                    "store_id": "199"})
    assert answer == {"articleNumber": "100001", "storeId": "199",
                      "price": {"currency": "EUR", "amount": {"scale": 2, "intVal": "999"}}}
    msg = client.call("GetEffectivePrice", client.request("GetEffectivePrice",
                                                         {"articleNumber": "100004"}))
    assert money.from_money(msg.price) == Decimal("9.99")


def test_abort_sets_message_and_error_code(client: grpcutil.Client) -> None:
    body = {"articleNumber": "100001", "storeId": "199",
            "expectedRegularPrice": money.to_money(Decimal("9.99")),
            "newPrice": money.to_money(Decimal("9.99"))}
    with pytest.raises(grpc.RpcError) as info:
        client.call("RequestPriceChange", body)
    assert info.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert info.value.details() == "WWS-010: keine Senkung"
    assert grpcutil.error_code(info.value) == "WWS-010"
    lower = {**body, "newPrice": money.to_money(Decimal("7.99"))}
    ok = client.call_json("RequestPriceChange", lower)
    assert ok == {"actionId": "PA-270216-0003", "created": True}


def test_unimplemented_rpcs(client: grpcutil.Client) -> None:
    with pytest.raises(grpc.RpcError) as info:
        client.call("GetSeasonInfo", {"articleNumber": "100008"})
    assert info.value.code() == grpc.StatusCode.UNIMPLEMENTED
    assert grpcutil.error_code(info.value) == ""


def test_client_parses_strictly(client: grpcutil.Client) -> None:
    with pytest.raises(Exception, match="nope"):
        client.call("GetEffectivePrice", {"nope": 1})


def test_health(wws_server: tuple[grpc.Server, int]) -> None:
    with grpc.insecure_channel(f"localhost:{wws_server[1]}") as channel:
        stub = health_pb2_grpc.HealthStub(channel)
        for name in ("", WWS_SVC):
            reply = stub.Check(health_pb2.HealthCheckRequest(service=name), timeout=5)
            assert reply.status == health_pb2.HealthCheckResponse.SERVING


def _reflect(port: int, path: str, request: reflection_pb2.ServerReflectionRequest
             ) -> reflection_pb2.ServerReflectionResponse:
    with grpc.insecure_channel(f"localhost:{port}") as channel:
        call = channel.stream_stream(
            path, request_serializer=reflection_pb2.ServerReflectionRequest.SerializeToString,
            response_deserializer=reflection_pb2.ServerReflectionResponse.FromString)
        return next(iter(call(iter([request]), timeout=5)))


V1ALPHA = "/grpc.reflection.v1alpha.ServerReflection/ServerReflectionInfo"
V1 = "/grpc.reflection.v1.ServerReflection/ServerReflectionInfo"


@pytest.mark.parametrize("path", [V1ALPHA, V1])
def test_reflection_lists_services(wws_server: tuple[grpc.Server, int], path: str) -> None:
    reply = _reflect(wws_server[1], path, reflection_pb2.ServerReflectionRequest(list_services=""))
    names = {s.name for s in reply.list_services_response.service}
    assert names == {WWS_SVC, "grpc.health.v1.Health", "grpc.reflection.v1.ServerReflection",
                     "grpc.reflection.v1alpha.ServerReflection"}


@pytest.mark.parametrize(("symbol", "file"), [
    (f"{WWS_SVC}.GetEffectivePrice", "de/showcase/wws/v1/service/wws_service.proto"),  # fix 1
    (WWS_SVC, "de/showcase/wws/v1/service/wws_service.proto"),
    ("de.showcase.wws.v1.datatype.EffectivePrice",
     "de/showcase/wws/v1/datatype/wws_datatype.proto"),
    ("grpc.reflection.v1.ServerReflection", "grpc/reflection/v1/reflection.proto"),  # fix 2
    ("grpc.health.v1.Health", "grpc_health/v1/health.proto"),  # name in grpcio-health
])
def test_reflection_resolves_symbols(wws_server: tuple[grpc.Server, int], symbol: str,
                                     file: str) -> None:
    reply = _reflect(wws_server[1], V1,
                     reflection_pb2.ServerReflectionRequest(file_containing_symbol=symbol))
    assert reply.WhichOneof("message_response") == "file_descriptor_response", symbol
    files = [descriptor_pb2.FileDescriptorProto.FromString(raw).name
             for raw in reply.file_descriptor_response.file_descriptor_proto]
    assert files[0] == file


def test_unknown_symbol_is_not_found(wws_server: tuple[grpc.Server, int]) -> None:
    reply = _reflect(wws_server[1], V1ALPHA, reflection_pb2.ServerReflectionRequest(
        file_containing_symbol=f"{WWS_SVC}.Nope"))
    assert reply.error_response.error_code == grpc.StatusCode.NOT_FOUND.value[0]


def test_reflection_v1_file_renames_every_type() -> None:
    v1 = grpcutil.reflection_v1_file()
    assert v1.package == "grpc.reflection.v1"
    assert all(not f.type_name or f.type_name.startswith(".grpc.reflection.v1.")
               for m in v1.message_type for f in m.field)
    assert [m.input_type for m in v1.service[0].method] == [
        ".grpc.reflection.v1.ServerReflectionRequest"]
