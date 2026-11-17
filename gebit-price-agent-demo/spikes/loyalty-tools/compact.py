"""Print a compact, faithful sketch of our proto from the compiled descriptor set."""
import sys, textwrap
from google.protobuf import descriptor_pb2 as d
fds = d.FileDescriptorSet(); fds.ParseFromString(open(sys.argv[1], "rb").read())
T = {v: k[5:].lower() for k, v in d.FieldDescriptorProto.Type.items()}
def tname(f, pkg):
    if f.type in (d.FieldDescriptorProto.TYPE_MESSAGE, d.FieldDescriptorProto.TYPE_ENUM):
        n = f.type_name.lstrip(".")
        for p in ("de.showcase.loyalty.v1.",):
            if n.startswith(p): n = n[len(p):]
        if n.startswith(pkg.split("de.showcase.loyalty.v1.")[-1] + "."):
            n = n.split(".", 1)[1]
        return n
    return T[f.type]
for f in fds.file:
    if not f.package.startswith("de.showcase"): continue
    pkg = f.package
    print(f"// {f.name}  (package {pkg})")
    for e in f.enum_type:
        vals = ", ".join(v.name.replace(e.name and "", "") for v in e.value)
        short = [v.name for v in e.value]
        pre = __import__("os").path.commonprefix(short)
        print(textwrap.fill(f"enum {e.name} {{ {pre}* : " + " | ".join(s[len(pre):] for s in short) + " }", 100, subsequent_indent="    "))
    for m in f.message_type:
        parts = []
        oneofs = {}
        for fl in m.field:
            lab = "repeated " if fl.label == d.FieldDescriptorProto.LABEL_REPEATED else ("optional " if fl.proto3_optional else "")
            s = f"{lab}{tname(fl, pkg)} {fl.name} = {fl.number}"
            if fl.HasField("oneof_index") and not fl.proto3_optional:
                oneofs.setdefault(m.oneof_decl[fl.oneof_index].name, []).append(s)
            else:
                parts.append(s)
        for k, v in oneofs.items():
            parts.append(f"oneof {k} {{ " + "; ".join(v) + " }")
        res = [f"{r.start}-{r.end-1}" if r.end - 1 != r.start else str(r.start) for r in m.reserved_range]
        if res: parts.insert(0, "reserved " + ", ".join(res))
        print(textwrap.fill(f"message {m.name} {{ " + "; ".join(parts) + "; }", 100, subsequent_indent="    "))
    for s in f.service:
        print(f"service {s.name} {{")
        for r in s.method:
            i = r.input_type.lstrip(".").replace("de.showcase.loyalty.v1.", "")
            o = r.output_type.lstrip(".").replace("de.showcase.loyalty.v1.", "")
            print(f"  rpc {r.name}({i}) returns ({o});")
        print("}")
    print()
