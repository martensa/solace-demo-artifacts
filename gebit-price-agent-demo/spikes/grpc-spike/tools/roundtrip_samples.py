"""Check: GEBIT sample JSON -> message (custom pool) -> JSON is lossless with our options."""
import glob, json, sys, time
sys.path.insert(0, sys.argv[1])
from google.protobuf import any_pb2, json_format
from gebitsim.descriptors import load_pool

pool = load_pool(sys.argv[2].split(":"))
ok = 0
for path in sorted(glob.glob(sys.argv[3] + "/*.json")):
    src = json.load(open(path))
    a = any_pb2.Any()
    json_format.ParseDict(src, a, descriptor_pool=pool)          # strict: unknown field -> error
    out = json.loads(json_format.MessageToJson(a, descriptor_pool=pool))
    same = out == src
    ok += same
    print(f"{'SAME' if same else 'DIFF'} {path.rsplit('/',1)[1]} type_url={a.type_url.rsplit('.',1)[1]} bin={len(a.value)}B json={len(json.dumps(src))}B")
    if not same:
        for k in set(src) | set(out):
            if src.get(k) != out.get(k):
                print("   key", k, "\n    src", json.dumps(src.get(k))[:200], "\n    out", json.dumps(out.get(k))[:200])
print(f"{ok} identical")
# negative: Any without custom pool
try:
    json_format.ParseDict(json.load(open(sorted(glob.glob(sys.argv[3] + "/*.json"))[0])), any_pb2.Any())
    print("default-pool parse: unexpectedly OK")
except Exception as e:
    print("default-pool parse fails as expected:", type(e).__name__, str(e)[:120])
