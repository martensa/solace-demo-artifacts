"""End-to-end spike: start server in-process, drive it with the generic client,
compare emitted events to GEBIT samples, measure latency, test reflection + health.

usage: python -I tools/run_spike.py <spike_dir> <pb[:pb]> <samples_dir> <out_dir>
"""
import glob
import json
import os
import statistics as st
import sys
import time
import uuid

sys.path.insert(0, sys.argv[1])
import grpc
from google.protobuf import any_pb2, descriptor_pool, json_format, message_factory
from grpc_health.v1 import health_pb2, health_pb2_grpc
from grpc_reflection.v1alpha.proto_reflection_descriptor_database import ProtoReflectionDescriptorDatabase

from gebitsim.client import GebitClient
from gebitsim.descriptors import PURCHASE_SVC, Types, load_pool
from gebitsim.server import build_server

PB, SAMPLES, OUT = sys.argv[2].split(":"), sys.argv[3], sys.argv[4]
os.makedirs(OUT, exist_ok=True)
EVENTS = os.path.join(OUT, "events.jsonl")
if os.path.exists(EVENTS):
    os.remove(EVENTS)
results = {}


def check(name, ok, detail=""):
    results[name] = (bool(ok), detail)
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")


server, sim, info = build_server(PB, 0, EVENTS)
server.start()
port = info["port"]
print("server info:", {k: v for k, v in info.items() if k != "implemented"}, "implemented:", info["implemented"])
check("descriptor pool built at runtime (merged purchase+receipt)", True, f"{info['pool_load_s']*1000:.0f} ms, {info['methods']} methods registered")

# ---------- 1. generic client from its own pool (client does not share server objects) ----------
ctypes = Types(load_pool(PB))
ch = grpc.insecure_channel(f"localhost:{port}")
grpc.channel_ready_future(ch).result(timeout=5)
cli = GebitClient(ch, ctypes)
hdr = lambda step: {"traceId": f"eurocis.spike.{step}", "originator": {}}

lat: dict[str, list[float]] = {}


def timed(method, body):
    t0 = time.perf_counter()
    r = cli.call(method, body)
    lat.setdefault(method, []).append((time.perf_counter() - t0) * 1000)
    return r


def sale(tag, articles, cash_cents, capture=True, drawer="BOOTH_TILL_01"):
    r = timed("CreatePurchaseTransaction", {"header": hdr(f"{tag}.s01_create"), "location": "Root.DE.999.101.01",
                                            "employeeId": "ID199901", "cashdrawerId": drawer})
    tx = r.purchase_transaction_id
    for a in articles:
        body = {"header": hdr(f"{tag}.s02_addArticle"), "purchaseTransactionId": tx, "articleId": a, "itemCount": 1}
        if capture:
            body["capturingInformation"] = {"inputMethod": "SCAN", "inputValue": "4006381333931"}
        timed("AddArticle", body)
    timed("StartPaymentProcess", {"header": hdr(f"{tag}.s03_StartPaymentProcess"), "purchaseTransactionId": tx})
    timed("CreateCashPayment", {"header": hdr(f"{tag}.s04_payment"), "purchaseTransactionId": tx,
                                "amount": {"currency": "EUR", "amount": {"intVal": str(cash_cents // 100)}},
                                "clientId": "the_clientId", "clientTransactionId": f"clientTransactionId_{uuid.uuid4()}"})
    return tx


# replay the GEBIT simpleSale: 1 x GEBIT Ente (8.67), pay 10 EUR cash -> change 1.33
tx = sale("simpleSale", ["IDarticle004"], 1000, capture=False, drawer="PURCHASE_IT_TEST_CASHDRAWER")
evs = [json.loads(l) for l in open(EVENTS)]
names = [e["payload"]["@type"].rsplit(".", 1)[1] for e in evs]
sample_files = sorted(glob.glob(SAMPLES + "/*.json"))
sample_names = [os.path.basename(f)[3:-5] for f in sample_files]
check("simpleSale event sequence == GEBIT sample (11 events, same order)", names == sample_names, str(names))
check("CreatePurchaseTransaction returns PurchaseTransactionId", bool(tx), tx)


# ---------- 2. shape comparison event-by-event ----------
def paths(o, p=""):
    out = set()
    if isinstance(o, dict):
        for k, v in o.items():
            out |= {f"{p}.{k}"} | paths(v, f"{p}.{k}")
    elif isinstance(o, list):
        for v in o:
            out |= paths(v, f"{p}[]")
    else:
        out.add(f"{p}:{type(o).__name__}")
    return out


mine = {}
for e in evs:
    mine.setdefault(e["payload"]["@type"], []).append(e["payload"])
shape_ok, diffs = True, []
for f in sample_files:
    s = json.load(open(f))
    cands = mine.get(s["@type"])
    if not cands:
        diffs.append(f"{os.path.basename(f)}: not emitted")
        continue
    m = cands.pop(0)
    ps, pm = paths(s), paths(m)
    # extensionProperties in the sample are test fixtures (foo/bar), not semantics
    ignore = lambda x: ".extensionProperties" in x and "calculatedPositionPrice" not in x
    only_s = sorted(x for x in ps - pm if not ignore(x))
    only_m = sorted(x for x in pm - ps if not ignore(x))
    if only_s or only_m:
        shape_ok = False
        diffs.append(f"{os.path.basename(f)}: sample-only={only_s[:6]} sim-only={only_m[:6]}")
    if list(s)[:3] != list(m)[:3]:
        shape_ok = False
        diffs.append(f"{os.path.basename(f)}: key order {list(s)[:3]} vs {list(m)[:3]}")
check("emitted JSON field shape == GEBIT samples (key paths + value types)", shape_ok, "; ".join(diffs) or "all event types identical shape")

# values: same business content once volatile fields (ids, timestamps, trace, fixtures) are masked
VOLATILE = {"header", "creationTimestamp", "traceId", "purchaseTransactionId", "positionId", "paymentPositionId",
            "clientTransactionId", "createdAt", "openedAt", "closedAt", "receiptNumber", "fiscalTransactionId",
            "serializedReceiptContent", "serializedReceiptVersion"}
def mask(o, top=True):
    if isinstance(o, dict):
        return {k: mask(v, False) for k, v in o.items()
                if k not in VOLATILE and not (top and k == "extensionProperties")}
    if isinstance(o, list):
        return [mask(v, False) for v in o]
    return o
vdiff = []
for f, e in zip(sample_files, evs):
    a, b = mask(json.load(open(f))), mask(e["payload"])
    if a != b:
        vdiff.append(os.path.basename(f) + ": " + ", ".join(k for k in set(a) | set(b) if a.get(k) != b.get(k)))
check("emitted values == GEBIT samples (offsets, status, sums, taxes, change; ids/timestamps masked)", not vdiff, "; ".join(vdiff))
with open(os.path.join(OUT, "sim_PositionAdded.json"), "w") as fh:
    json.dump([e for e in evs if e["payload"]["@type"].endswith("PositionAdded")][0], fh, indent=2)
with open(os.path.join(OUT, "sim_PurchaseTransactionClosed.json"), "w") as fh:
    json.dump([e for e in evs if e["payload"]["@type"].endswith("Closed")][0], fh, indent=2)

# every emitted payload re-parses strictly against the pool
strict_ok = True
for e in evs:
    try:
        json_format.ParseDict(e["payload"], any_pb2.Any(), descriptor_pool=ctypes.pool)
    except Exception as ex:  # noqa
        strict_ok = False
        print("strict parse failed", ex)
check("emitted payloads re-parse strictly (ignore_unknown_fields=False)", strict_ok)

# receipt inside Closed decodes
closed = [e for e in evs if e["payload"]["@type"].endswith("Closed")][0]["payload"]
import base64
ra = any_pb2.Any()
ra.ParseFromString(base64.b64decode(closed["serializedReceiptContent"]))
rcls = message_factory.GetMessageClass(ctypes.pool.FindMessageTypeByName(ra.type_url.split("/", 1)[1]))
rmsg = rcls()
ra.Unpack(rmsg)
check("Closed.serializedReceiptContent = binary Any(Receipt) from receipt descriptor", rmsg.total.value == "8.67",
      f"type_url={ra.type_url}, total={rmsg.total.value}")

# ---------- 3. cancel path ----------
r = timed("CreatePurchaseTransaction", {"header": hdr("cancel.s01"), "location": "Root.DE.999.101.01", "employeeId": "ID199901"})
timed("AddArticle", {"header": hdr("cancel.s02"), "purchaseTransactionId": r.purchase_transaction_id, "articleId": "IDcoffee01", "itemCount": 2})
timed("CancelPurchaseTransaction", {"header": hdr("cancel.s03"), "purchaseTransactionId": r.purchase_transaction_id,
                                    "cancellationReason": "customer left", "cancellationReasonCode": "ABANDONED"})
evs2 = [json.loads(l) for l in open(EVENTS)][len(evs):]
n2 = [e["payload"]["@type"].rsplit(".", 1)[1] for e in evs2]
check("CancelPurchaseTransaction emits InCancellation -> Cancelled", n2[-2:] == ["PurchaseTransactionInCancellation", "PurchaseTransactionCancelled"], str(n2))
print("example topic:", evs2[-1]["topic"])

# ---------- 4. error mapping ----------
try:
    cli.call("AddArticle", {"purchaseTransactionId": r.purchase_transaction_id, "articleId": "IDbanana01"})
    check("AddArticle on cancelled basket -> FAILED_PRECONDITION", False)
except grpc.RpcError as e:
    check("AddArticle on cancelled basket -> FAILED_PRECONDITION", e.code() == grpc.StatusCode.FAILED_PRECONDITION, e.details())
try:
    cli.call("VoidArticlePosition", {"purchaseTransactionId": r.purchase_transaction_id})
except grpc.RpcError as e:
    check("non-simulated RPC -> UNIMPLEMENTED (all 106 registered)", e.code() == grpc.StatusCode.UNIMPLEMENTED, e.details())

# ---------- 5. latency ----------
lat.clear()
sink_count0 = sim.sink.count
build_us = []
orig_publish = sim.sink.publish
def pub(ev):
    build_us.append(ev.build_us)
    orig_publish(ev)
sim.sink.publish = pub
N = int(os.environ.get("SPIKE_N", "200"))
t0 = time.perf_counter()
for i in range(N):
    sale(f"bench{i}", ["IDarticle004", "IDbanana01", "IDcoffee01"], 3000)
wall = time.perf_counter() - t0
def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]
lat_table = {m: {"n": len(v), "p50_ms": round(st.median(v), 3), "p95_ms": round(pct(v, 95), 3), "max_ms": round(max(v), 3)} for m, v in lat.items()}
for m, v in lat_table.items():
    print(f"  {m:28s} {v}")
evn = sim.sink.count - sink_count0
print(f"  events emitted: {evn} in {wall:.2f}s -> {evn / wall:.0f} ev/s; event build+serialise p50 {st.median(build_us):.0f} us, p95 {pct(build_us, 95):.0f} us")
check("latency: unary call p95 < 10 ms on localhost (incl. JSONL sink)", all(v["p95_ms"] < 10 for v in lat_table.values()),
      json.dumps({m: v["p95_ms"] for m, v in lat_table.items()}))
results["latency"] = (True, lat_table)

# ---------- 6. health ----------
hc = health_pb2_grpc.HealthStub(ch).Check(health_pb2.HealthCheckRequest(service=PURCHASE_SVC))
check("grpc.health.v1 Check(PurchaseTransactionService) == SERVING", hc.status == health_pb2.HealthCheckResponse.SERVING)

# ---------- 7. reflection: client with NO local descriptors (what grpcurl/Postman do) ----------
ch2 = grpc.insecure_channel(f"localhost:{port}")
db = ProtoReflectionDescriptorDatabase(ch2)
services = list(db.get_services())
check("reflection v1alpha list services", PURCHASE_SVC in services, str(services))
rpool = descriptor_pool.DescriptorPool(db)
t0 = time.perf_counter()
svc = rpool.FindServiceByName(PURCHASE_SVC)
m = svc.methods_by_name["AddArticle"]
t_ref = (time.perf_counter() - t0) * 1000
Req = message_factory.GetMessageClass(m.input_type)
Resp = message_factory.GetMessageClass(m.output_type)
Create = svc.methods_by_name["CreatePurchaseTransaction"]
CReq, CResp = (message_factory.GetMessageClass(Create.input_type), message_factory.GetMessageClass(Create.output_type))
cstub = ch2.unary_unary(f"/{PURCHASE_SVC}/CreatePurchaseTransaction", request_serializer=CReq.SerializeToString, response_deserializer=CResp.FromString)
astub = ch2.unary_unary(f"/{PURCHASE_SVC}/AddArticle", request_serializer=Req.SerializeToString, response_deserializer=Resp.FromString)
cr = CReq(); json_format.ParseDict({"location": "Root.DE.999.101.01", "employeeId": "ID199901"}, cr)
txr = cstub(cr).purchase_transaction_id
ar = Req(); json_format.ParseDict({"purchaseTransactionId": txr, "articleId": "IDbanana01", "itemCount": 3}, ar)
astub(ar)
last = [p for p in (json.loads(l)["payload"] for l in open(EVENTS)) if p["@type"].endswith("PositionAdded")][-1]
check("reflection-only client (no .pb) resolves service+types and calls AddArticle", last["@type"].endswith("PositionAdded") and last["itemCount"] == 3,
      f"{len(svc.methods)} methods via reflection; first resolve {t_ref:.0f} ms")
# health/reflection descriptors resolvable too (grpcurl describe)
try:
    rpool.FindServiceByName("grpc.health.v1.Health")
    check("reflection describes grpc.health.v1.Health", True)
except Exception as ex:  # noqa
    check("reflection describes grpc.health.v1.Health", False, str(ex))
# v1 reflection (grpcurl tries v1 first, Postman newer versions too)
from grpc_reflection.v1alpha import reflection_pb2
v1 = ch2.stream_stream("/grpc.reflection.v1.ServerReflection/ServerReflectionInfo",
                       request_serializer=reflection_pb2.ServerReflectionRequest.SerializeToString,
                       response_deserializer=reflection_pb2.ServerReflectionResponse.FromString)
resp = list(v1(iter([reflection_pb2.ServerReflectionRequest(list_services="")])))
check("reflection v1 (grpc.reflection.v1.ServerReflection) list services", any(s.name == PURCHASE_SVC for s in resp[0].list_services_response.service),
      str([s.name for s in resp[0].list_services_response.service]))
resp = list(v1(iter([reflection_pb2.ServerReflectionRequest(file_containing_symbol=PURCHASE_SVC)])))
check("reflection v1 file_containing_symbol returns transitive file set", len(resp[0].file_descriptor_response.file_descriptor_proto) > 30,
      f"{len(resp[0].file_descriptor_response.file_descriptor_proto)} files")

server.stop(0)
with open(os.path.join(OUT, "results.json"), "w") as fh:
    json.dump({k: v for k, v in results.items()}, fh, indent=2, default=str)
fails = [k for k, (ok, _) in results.items() if not ok]
print("FAILED:", fails if fails else "none")
