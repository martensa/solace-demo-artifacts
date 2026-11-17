import sys
from google.protobuf import descriptor_pb2
for path in sys.argv[1:]:
    fds = descriptor_pb2.FileDescriptorSet()
    fds.ParseFromString(open(path,'rb').read())
    print("==", path, len(fds.file), "files")
    pkgs = {}
    for f in fds.file:
        pkgs.setdefault(f.package, []).append(f.name)
    for p, names in sorted(pkgs.items()):
        print(" pkg", p, len(names))
    for f in fds.file:
        for s in f.service:
            print(" service", f.package + "." + s.name, len(s.method))
        for m in f.message_type:
            n = m.name.lower()
            if any(k in n for k in ("loyal","coupon","member","bonus","benefit","earn","burn","point","promotion","customer")):
                print("  msg", f.package + "." + m.name, [fld.name for fld in m.field][:25])
