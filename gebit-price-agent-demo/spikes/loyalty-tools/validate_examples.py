"""Validate example JSON files against descriptor sets (data only)."""
import json, sys, glob, os
from google.protobuf import descriptor_pb2, descriptor_pool, json_format, message_factory
def pool_from(paths):
    pool = descriptor_pool.DescriptorPool()
    seen = set()
    for p in paths:
        fds = descriptor_pb2.FileDescriptorSet(); fds.ParseFromString(open(p, "rb").read())
        for f in fds.file:
            if f.name in seen: continue
            seen.add(f.name); pool.Add(f)
    return pool
pools = {"de.gebit.rp.purchase": pool_from([sys.argv[1]]), "de.gebit.rp.receipt": pool_from([sys.argv[2]]),
         "de.showcase.loyalty": pool_from([sys.argv[3]])}
ok = bad = 0
for fn in sorted(glob.glob(os.path.join(sys.argv[4], "*.json"))):
    d = json.load(open(fn)); t = d.pop("@type").split("/", 1)[1]
    pool = next(v for k, v in pools.items() if t.startswith(k))
    cls = message_factory.GetMessageClass(pool.FindMessageTypeByName(t))
    try:
        m = json_format.ParseDict(d, cls())
        rt = json_format.MessageToDict(m)
        size = len(json.dumps(dict({"@type": "type.googleapis.com/" + t}, **rt), separators=(",", ":")))
        print(f"OK   {os.path.basename(fn):45s} {t.rsplit('.',1)[1]:28s} {size:5d} B compact")
        ok += 1
    except Exception as e:
        print(f"FAIL {os.path.basename(fn)}: {e}"); bad += 1
print(f"{ok} ok, {bad} failed")
