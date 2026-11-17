"""grpc.aio variant: generic handler + reflection in one asyncio loop (FastAPI-friendly)."""
import asyncio, sys, time
sys.path.insert(0, sys.argv[1])
import grpc
from grpc_reflection.v1alpha import reflection
from google.protobuf import json_format
from gebitsim.descriptors import PURCHASE_SVC, Types, load_pool

PB = sys.argv[2].split(":")
pool = load_pool(PB); T = Types(pool)
ext = pool.FindExtensionByName("de.gebit.rp.protobuf.options.async_message_set")
try:
    print("direct opts.Extensions[ext]:", pool.FindMessageTypeByName("de.gebit.rp.purchase.purchase.v2.event.PositionAdded").GetOptions().Extensions[ext])
except Exception as e:
    print("direct opts.Extensions[ext] fails:", type(e).__name__, str(e)[:100])

async def create(req, ctx):
    return T.new("de.gebit.rp.purchase.purchase.v2.datatype.PurchaseTransactionId", purchase_transaction_id="tx-" + req.location)

async def main():
    svc = pool.FindServiceByName(PURCHASE_SVC)
    m = svc.methods_by_name["CreatePurchaseTransaction"]
    Req, Resp = T.cls(m.input_type.full_name), T.cls(m.output_type.full_name)
    server = grpc.aio.server()
    server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler(PURCHASE_SVC, {
        m.name: grpc.unary_unary_rpc_method_handler(create, request_deserializer=Req.FromString, response_serializer=Resp.SerializeToString)}),))
    reflection.enable_server_reflection([PURCHASE_SVC, reflection.SERVICE_NAME], server, pool=pool)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as ch:
        stub = ch.unary_unary(f"/{PURCHASE_SVC}/{m.name}", request_serializer=Req.SerializeToString, response_deserializer=Resp.FromString)
        r = Req(); json_format.ParseDict({"location": "Root.DE.999.101.01"}, r)
        lat = []
        for _ in range(500):
            t0 = time.perf_counter(); out = await stub(r); lat.append((time.perf_counter() - t0) * 1000)
        lat.sort()
        print("aio unary OK:", out.purchase_transaction_id, f"p50 {lat[250]:.3f} ms p95 {lat[475]:.3f} ms")
        # concurrency: 200 in flight
        for n in (100, 500, 2000):
            t0 = time.perf_counter()
            res = await asyncio.gather(*(stub(r, timeout=10) for _ in range(n)), return_exceptions=True)
            errs = [x for x in res if isinstance(x, Exception)]
            print(f"aio {n} concurrent calls: {(time.perf_counter()-t0)*1000:.0f} ms, errors={len(errs)} {str(errs[0])[:160] if errs else ''}")
    await server.stop(0)
asyncio.run(main())
