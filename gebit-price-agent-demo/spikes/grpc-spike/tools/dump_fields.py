import sys
sys.path.insert(0, sys.argv[1])
from gebitsim.descriptors import load_pool
from google.protobuf.descriptor import FieldDescriptor as FD
pool = load_pool(sys.argv[2].split(":"))
TN = {v: k for k, v in vars(FD).items() if k.startswith("TYPE_")}
seen = set()
def dump(name, depth, maxdepth):
    d = pool.FindMessageTypeByName(name)
    for f in d.fields:
        t = f.message_type.full_name if f.message_type else (f.enum_type.full_name if f.enum_type else TN[f.type][5:].lower())
        rep = "repeated " if f.is_repeated else ""
        oneof = f" (oneof {f.containing_oneof.name})" if f.containing_oneof else ""
        print("  " * depth + f"{f.number:>3} {f.name} [{f.json_name}] : {rep}{t}{oneof}")
        if f.message_type and depth < maxdepth and f.message_type.full_name not in seen and not f.message_type.full_name.startswith("google."):
            seen.add(f.message_type.full_name)
            dump(f.message_type.full_name, depth + 1, maxdepth)
for n in sys.argv[3].split(","):
    seen.clear()
    print("##", n); dump(n, 1, int(sys.argv[4]) if len(sys.argv) > 4 else 1)
