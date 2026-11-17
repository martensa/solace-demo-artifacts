"""Pitfall experiments for the runtime-descriptor approach."""
import json
import sys
import time

sys.path.insert(0, sys.argv[1])
from google.protobuf import any_pb2, descriptor_pb2, descriptor_pool, json_format, message_factory

from gebitsim.descriptors import EVENT_PKG, Types, load_pool

PB = sys.argv[2].split(":")
SAMPLE = sys.argv[3]

# 1. Adding the purchase set to the DEFAULT pool (instead of a fresh one)
fds = descriptor_pb2.FileDescriptorSet()
fds.ParseFromString(open(PB[0], "rb").read())
dflt = descriptor_pool.Default()
errs = []
for f in fds.file:
    try:
        dflt.Add(f)
    except Exception as e:  # noqa
        errs.append(f"{f.name}: {type(e).__name__}: {str(e)[:90]}")
print("1. default-pool Add errors:", len(errs), errs[:3])
try:
    a = any_pb2.Any()
    json_format.ParseDict(json.load(open(SAMPLE)), a)  # no descriptor_pool argument
    print("   default pool then resolves @type without descriptor_pool=:", a.type_url)
except Exception as e:  # noqa
    print("   default pool resolve failed:", e)

# 2. Unsorted add into a fresh pool (reverse order) -> missing dependency
p = descriptor_pool.DescriptorPool()
try:
    for f in reversed(fds.file):
        p.Add(f)
    print("2. reverse-order add: OK (pool resolves lazily)")
except Exception as e:  # noqa
    print("2. reverse-order add fails:", type(e).__name__, str(e)[:120])

pool = load_pool(PB)
T = Types(pool)

# 3. Custom option (de.gebit.rp.protobuf.options.async_message_set) from a runtime pool
d = pool.FindMessageTypeByName(f"{EVENT_PKG}.PositionAdded")
opts = d.GetOptions()
print("3. GetOptions() type:", type(opts).__module__, "unknown/ext visible via ListFields:", [f.name for f, _ in opts.ListFields()])
ext = pool.FindExtensionByName("de.gebit.rp.protobuf.options.async_message_set")
MO = message_factory.GetMessageClass(pool.FindMessageTypeByName("google.protobuf.MessageOptions"))
mo = MO.FromString(opts.SerializeToString())
print("   re-parse into pool's own MessageOptions -> Extensions[ext] =", repr(mo.Extensions[ext]))
domain = [m for m in pool.FindFileByName("de/gebit/rp/purchase/purchase/v2/event/basket_event.proto").message_types_by_name.values()
          if MO.FromString(m.GetOptions().SerializeToString()).Extensions[ext] == "PurchaseDomainEvents"]
print("   basket_event.proto domain events:", len(domain))

# 4. json option variants vs the GEBIT sample
src = json.load(open(SAMPLE))
a = any_pb2.Any()
json_format.ParseDict(src, a, descriptor_pool=pool)
variants = {
    "default (GEBIT-identical)": {},
    "preserving_proto_field_name=True": {"preserving_proto_field_name": True},
    "always_print_fields_with_no_presence=True": {"always_print_fields_with_no_presence": True},
    "use_integers_for_enums=True": {"use_integers_for_enums": True},
    "unquote_int64_if_possible=True": {"unquote_int64_if_possible": True},
}
for name, kw in variants.items():
    try:
        out = json.loads(json_format.MessageToJson(a, descriptor_pool=pool, **kw))
        print(f"4. {name:45s} identical={out == src} bytes={len(json.dumps(out))}")
    except TypeError as e:
        print(f"4. {name:45s} n/a: {e}")

# 5. ensure_ascii and non-ASCII
m = T.event("PositionAdded")
m.description = "Bio-Möhren Düsseldorf"
print("5. ensure_ascii default:", json.loads(json_format.MessageToJson(m))["description"], "|raw:", json_format.MessageToJson(m, indent=None)[:60])
print("   ensure_ascii=False   :", json_format.MessageToJson(m, indent=None, ensure_ascii=False)[:60])

# 6. Serialisation cost: Any route vs dict route (same output)
ev = T.cls(a.type_url.split("/", 1)[1])()
a.Unpack(ev)
N = 2000
t0 = time.perf_counter()
for _ in range(N):
    aa = any_pb2.Any(); aa.Pack(ev); s1 = json_format.MessageToJson(aa, descriptor_pool=pool)
t1 = time.perf_counter()
for _ in range(N):
    s2 = json.dumps({"@type": "type.googleapis.com/" + ev.DESCRIPTOR.full_name, **json_format.MessageToDict(ev)}, indent=2)
t2 = time.perf_counter()
print(f"6. Any route {1e6*(t1-t0)/N:.0f} us/event, dict route {1e6*(t2-t1)/N:.0f} us/event, same JSON: {json.loads(s1) == json.loads(s2)}")
t0 = time.perf_counter()
for _ in range(N):
    x = T.event("PositionAdded"); json_format.ParseDict(json.loads(s2) | {}, aa := any_pb2.Any(), descriptor_pool=pool)
print(f"   ParseDict(Any) {1e6*(time.perf_counter()-t0)/N:.0f} us/event; binary size {len(ev.SerializeToString())} B vs JSON {len(s1)} B")

# 7. typos and enum names are caught at build time
for bad in ({"purchaseTransactionStatus": "OPEN"}, {"itemcount": 1}, {"itemCount": "1"}):
    try:
        json_format.ParseDict(bad, T.event("PositionAdded"))
        print("7.", bad, "-> accepted")
    except json_format.ParseError as e:
        print("7.", bad, "-> ParseError:", str(e)[:100])

# 8. proto3 'optional' (receipt API) prints explicit defaults
R = T.new("de.gebit.rp.receipt.receipt.v2.datatype.Receipt")
R.cashdrawer_id = ""
R.receipt_type = ""
print("8. receipt optional field set to '' ->", json_format.MessageToJson(R, indent=None), "(receipt_type, non-optional, omitted)")
print("   receipt Decimal/OffsetTimestamp shapes:",
      [f.name for f in pool.FindMessageTypeByName("de.gebit.rp.protobuf.basic.Decimal").fields],
      [f"{f.name}:{f.message_type.full_name if f.message_type else f.type}" for f in pool.FindMessageTypeByName("de.gebit.rp.protobuf.basic.OffsetTimestamp").fields])
