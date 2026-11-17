import sys
from google.protobuf import descriptor_pb2
fds = descriptor_pb2.FileDescriptorSet()
fds.ParseFromString(open(sys.argv[1], 'rb').read())
names = [f.name for f in fds.file]
print("files:", len(names))
deps = set(d for f in fds.file for d in f.dependency)
missing = sorted(d for d in deps if d not in names)
print("deps not in set:", missing)
print("non-gebit files in set:", [n for n in names if not n.startswith("de/gebit/rp/purchase")])
svcs = [(f.name, s.name, len(s.method)) for f in fds.file for s in f.service]
print("services:", svcs)
pk = sorted(set(f.package for f in fds.file))
print("packages:", pk)
# order check: does each file come after its deps?
seen=set(); bad=0
for f in fds.file:
    for d in f.dependency:
        if d in names and d not in seen: bad+=1
    seen.add(f.name)
print("files listed before their deps:", bad)
print("syntax:", sorted(set(f.syntax for f in fds.file)), "editions:", sorted(set(f.edition for f in fds.file)))
