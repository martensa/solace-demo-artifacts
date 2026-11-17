# Feasibility spike: GEBIT-style gRPC endpoint and event publisher built from descriptor sets at runtime

Date: 2026-11-10. Scope: the POS simulator ("Kasse") backend for the EuroCIS 2027 price-agent demo.
The spike tests whether we can serve GEBIT's `PurchaseTransactionService` over gRPC and emit
GEBIT-format events **without generated stubs**. GEBIT's descriptor sets are mounted at runtime
and treated as data only.

Code is in `.../scratchpad/impl/grpc-spike/` (a venv sits in `.venv/`). Everything ran with `python -I`.
Nothing from `~/Downloads/Gebit` was executed or copied: the two `.pb` files were only opened
read-only, by path. The lab was not touched (no kubectl, broker, DB or docker actions).

Environment: Python 3.13.5. Packages: `grpcio==1.85.1`, `grpcio-reflection==1.85.1`,
`grpcio-health-checking==1.85.1`, `protobuf==7.36.2` (upb backend).

## Result: feasible, 18 of 18 checks pass

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Build a DescriptorPool at runtime from the purchase-2.50.0 and receipt-2.13.0 `.pb` files (merged) | PASS | 57+18 files, 4 ms. The `formatted_content.proto` shared by both sets is byte-identical |
| 2 | Generic gRPC server (`method_handlers_generic_handler` + `message_factory`) registers all 106 RPCs | PASS | 5 RPCs are implemented. The other 101 return `UNIMPLEMENTED` with a message |
| 3 | Generic client (stubs built from its own pool, requests built from JSON like `grpcurl -d`) | PASS | `CreatePurchaseTransaction` returns `PurchaseTransactionId` |
| 4 | Replaying the GEBIT simpleSale (1x "GEBIT Ente" 8.67, 10 EUR cash) gives the same 11 events in the same order | PASS | Created, Opened, PositionAdded, FiscalTransactionAssigned, PaymentProcessStarted, 2x CashPaymentPositionCreated (PAYMENT, CHANGE), PaymentProcessCompleted, InChargingFinancialTransaction, InClosing, Closed |
| 5 | Emitted JSON has the same **shape** as the samples (all key paths and value types, key order) | PASS | All 11 event types are identical |
| 6 | Emitted **values** match the samples once ids, timestamps, traceIds and test fixtures are masked | PASS | offsets 1..11, statuses, taxes (19 %: net 729 / tax 138), paymentSessionSums, change -133, amount `{intVal:"10"}` |
| 7 | GEBIT samples round-trip unchanged (sample JSON -> Any(message) -> JSON equals the input, dict equality) | PASS | 11/11 |
| 8 | Emitted payloads re-parse strictly against the pool (`ignore_unknown_fields=False`) | PASS | |
| 9 | `PurchaseTransactionClosed.serializedReceiptContent` = base64 of a binary `Any(Receipt)` built from the receipt descriptor in the same pool | PASS | Decodes back, total 8.67 |
| 10 | `CancelPurchaseTransaction` emits InCancellation then Cancelled | PASS | |
| 11 | Error mapping: a command in the wrong state returns `FAILED_PRECONDITION` | PASS | The GEBIT rich `ErrorMessage` detail is not built yet |
| 12 | Latency: p95 below 10 ms per unary call on localhost, including event build and the JSONL sink | PASS | see the latency section |
| 13 | `grpc.health.v1` reports SERVING (usable for k8s native gRPC probes) | PASS | |
| 14 | Server reflection v1alpha `list` (served from the runtime pool) | PASS | |
| 15 | Reflection-only client with **no local .pb** resolves the service and types, then calls AddArticle (the grpcurl/Postman flow) | PASS | 106 methods, first resolve 4 ms |
| 16 | Reflection can describe `grpc.health.v1.Health` | PASS | works after adding health/reflection protos to the pool |
| 17 | Reflection **v1** (`grpc.reflection.v1.ServerReflection`, which grpcurl tries first) | PASS | v1 alias, see snippet 5 |
| 18 | v1 `file_containing_symbol` returns the transitive file set | PASS | 39 files |

Not tested:

- The real `grpcurl` and Postman binaries. grpcurl is not installed here, and installing it means a
  download that needs approval. Check 15 runs the same protocol steps grpcurl does: list services,
  fetch files by symbol, build a dynamic message from JSON, then call.
- gRPC through the lab NGINX ingress (TLS, `backend-protocol: GRPC`).
- Publishing to Solace. No broker writes were allowed, so a JSONL sink stands in. Topics and user
  properties are computed per event.

Additional measurements:

- Cold start of `python -m gebitsim.server` (descriptors passed by env var) until health reports
  SERVING: about 1.0 s. Nearly all of that is the grpc import; loading the pool takes 3-4 ms.
- `grpc.aio` variant: generic handler plus reflection in one asyncio loop works. Unary p50 0.41 ms,
  p95 0.58 ms. 100 and 500 concurrent calls had no errors. With 2000 in flight on one channel,
  211 calls came back `CANCELLED`. Booth load is a few calls per second, so this does not matter
  here.

## Latency (localhost, sync server with 16 threads, 200 baskets x 3 scans + pay)

| RPC | n | p50 ms | p95 ms | max ms |
|---|---|---|---|---|
| CreatePurchaseTransaction | 200 | 0.55 | 0.95 | 6.6 |
| AddArticle | 600 | 0.89 | 1.42 | 3.4 |
| StartPaymentProcess | 200 | 0.96 | 1.47 | 5.9 |
| CreateCashPayment (6 events) | 200 | 1.66 | 2.41 | 6.9 |

- Throughput: about 2000 events/s end to end.
- Building one event (ParseDict, Pack, MessageToJson): p50 135 us, p95 530 us.
- The serialisation step alone is about 75 us. The Any route and the dict route cost the same and
  give the same output.
- Size per PositionAdded event: 494 B binary vs about 1.8-2.9 KB JSON.
- Conclusion: the simulator's latency is negligible next to SAM's (22 ms entrypoint, 4.5 s agent).

## Code patterns (verified)

### 1. Pool from mounted descriptor sets (dedup, topological add, fresh pool)

```python
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

def load_pool(paths):
    files = {}
    for p in paths:
        fds = descriptor_pb2.FileDescriptorSet(); fds.ParseFromString(open(p, "rb").read())
        for f in fds.file:
            if f.name in files and files[f.name].SerializeToString(deterministic=True) != f.SerializeToString(deterministic=True):
                raise ValueError(f"conflicting {f.name}")
            files[f.name] = f
    pool, added = descriptor_pool.DescriptorPool(), set()   # NOT descriptor_pool.Default()
    def add(n):
        if n in added: return
        for d in files[n].dependency: add(d)                 # upb resolves eagerly: deps first
        pool.Add(files[n]); added.add(n)
    for n in files: add(n)
    return pool

cls = lambda pool, name: message_factory.GetMessageClass(pool.FindMessageTypeByName(name))
```

### 2. Generic server for every method of the service

```python
svc = pool.FindServiceByName("de.gebit.rp.purchase.purchase.v2.service.PurchaseTransactionService")
handlers = {}
for m in svc.methods:
    Req, Resp = cls(pool, m.input_type.full_name), cls(pool, m.output_type.full_name)
    handlers[m.name] = grpc.unary_unary_rpc_method_handler(
        getattr(impl, m.name, None) or unimplemented(m.name),
        request_deserializer=Req.FromString, response_serializer=Resp.SerializeToString)
server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler(svc.full_name, handlers),))
# handler signature: def AddArticle(self, req, context) -> Empty from the pool:
#   cls(pool, "google.protobuf.Empty")()   (the GEBIT set brings its own empty.proto)
```

### 3. Generic client (requests from JSON, like `grpcurl -d`)

```python
stub = channel.unary_unary(f"/{svc.full_name}/{m.name}",
                           request_serializer=Req.SerializeToString, response_deserializer=Resp.FromString)
req = Req(); json_format.ParseDict({"purchaseTransactionId": tx, "articleId": "IDarticle004", "itemCount": 1}, req)
stub(req, timeout=5)
```

### 4. Event in GEBIT's wire format (proto3 JSON of `Any`)

```python
ev = cls(pool, "de.gebit.rp.purchase.purchase.v2.event.PositionAdded")()
json_format.ParseDict({"header": {...}, "metadata": {"offset": "3", ...}, ...}, ev)  # strict, catches typos/enum names
a = any_pb2.Any(); a.Pack(ev)                       # type_url = type.googleapis.com/<full name>
payload = json_format.MessageToJson(a, descriptor_pool=pool)   # default options == GEBIT samples
topic = f"gebit/rp/purchase/v2/{category}/PositionAdded/{country}/{company}/{store}/{till}/{tx_id}"
# category from the descriptor: ev.DESCRIPTOR.file.name -> ".../event/basket_event.proto" -> "basket"
```

### 5. Reflection from the runtime pool, v1alpha plus a v1 alias

```python
from grpc_reflection.v1alpha import reflection, reflection_pb2, reflection_pb2_grpc
for fd in (reflection_pb2.DESCRIPTOR, health_pb2.DESCRIPTOR):
    pool.AddSerializedFile(fd.serialized_pb)        # so `describe grpc.health.v1.Health` resolves
names = [svc.full_name, health.SERVICE_NAME, reflection.SERVICE_NAME, "grpc.reflection.v1.ServerReflection"]
servicer = reflection.ReflectionServicer(names, pool=pool)
reflection_pb2_grpc.add_ServerReflectionServicer_to_server(servicer, server)
v1 = grpc.stream_stream_rpc_method_handler(servicer.ServerReflectionInfo,   # v1 == v1alpha on the wire
        request_deserializer=reflection_pb2.ServerReflectionRequest.FromString,
        response_serializer=reflection_pb2.ServerReflectionResponse.SerializeToString)
server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler(
        "grpc.reflection.v1.ServerReflection", {"ServerReflectionInfo": v1}),))
```

Expected grpcurl usage (not run here):

```text
grpcurl -plaintext localhost:50051 list
grpcurl -plaintext localhost:50051 describe de.gebit.rp.purchase.purchase.v2.service.PurchaseTransactionService.AddArticle
grpcurl -plaintext -d '{"location":"Root.DE.999.101.01","employeeId":"ID199901"}' \
  localhost:50051 de.gebit.rp.purchase.purchase.v2.service.PurchaseTransactionService/CreatePurchaseTransaction
```

In Postman, create a new gRPC request and choose "Using server reflection".

### 6. Reading GEBIT's custom message option (for example, to filter domain events)

```python
ext = pool.FindExtensionByName("de.gebit.rp.protobuf.options.async_message_set")
MO = cls(pool, "google.protobuf.MessageOptions")              # the pool's own descriptor.proto
val = MO.FromString(desc.GetOptions().SerializeToString()).Extensions[ext]   # "PurchaseDomainEvents"
```

## Pitfalls found (each one reproduced)

1. **Fresh pool, not the default one.** The purchase set brings its own (older)
   `google/protobuf/descriptor.proto`. Adding it to `descriptor_pool.Default()` fails with
   `duplicate file name`, while `empty.proto` adds fine.
   - Use a fresh `DescriptorPool()` per process role.
   - Pass `descriptor_pool=pool` to every `json_format.Parse/ParseDict/MessageToJson`.
2. **Dependency order.** With upb, a file whose imports are not yet in the pool fails immediately:
   `Depends on file 'de/gebit/rp/protobuf/options/api_metadata.proto'`.
   - One set is already in order. Merged sets need the topological add.
   - Both sets were built with imports included: no dependency is missing. The
     `options/basic/formatted_content` protos exist **only** in the `.pb`, not in the zipped
     sources, so `protoc` on the sources fails.
3. **`@type` resolution.** Calling `ParseDict` on an `Any` without `descriptor_pool=pool` raises
   `ParseError: Can not find message descriptor by type_url`. The type URL prefix is
   `type.googleapis.com/` (the `Pack()` default).
4. **Classes are per pool.** Two pools give two `Money` classes, and `CopyFrom` across them raises
   `TypeError ... expected <class 'Money'> got <class 'Money'>`.
   - Keep one pool per process and cache the classes.
   - Exchange messages between pools only as bytes or JSON.
5. **Custom options.** `desc.GetOptions()` returns the runtime's `descriptor_pb2.MessageOptions`, so
   `.Extensions[ext]` with the pool's extension raises `KeyError: Extension doesn't match`. Re-parse
   the options into the pool's own `MessageOptions` (snippet 6).
6. **JSON options.** The **defaults** of `MessageToJson` reproduce GEBIT exactly (11/11 dict-equal).
   Every other option breaks equality:
   - `preserving_proto_field_name` gives snake_case.
   - `always_print_fields_with_no_presence` emits empty fields: +22 % bytes.
   - `use_integers_for_enums` gives numbers instead of enum names.
   - `unquote_int64_if_possible` turns int64 values into numbers.
   - Old snippets use `including_default_value_fields`, which was renamed in protobuf 5.26 and is
     gone in 7.x.
7. **Numbers.** The int64 fields are strings in JSON: `metadata.offset`, `seconds`, `BDecimal.intVal`.
   The int32 fields are numbers: `nanos`, `OffsetTimestamp.offset` (minutes), `scale`, `itemCount`.
   - A zero is omitted: `{"scale": 2}` means 0.00, so consumers must default `intVal` to 0.
   - `ParseDict` is lenient: it accepts `"itemCount": "1"`. Validation does not catch
     numeric-string mistakes, but it does catch unknown fields and wrong enum names.
8. **Enums.** Enum values carry their type prefix (`PURCHASE_TRANSACTION_STATUS_OPEN`).
   `"OPEN"` is a ParseError.
9. **Names.** None of the 2998 GEBIT fields has a custom `json_name`; all are plain lowerCamelCase.
   The only simple-name clash is `Header` (`command.Header` vs `event.Header`), so always use full
   names. Request and response types live in other packages (`command.*`, `query.*`, `datatype.*`).
10. **Two time and decimal shapes.**
    - Purchase API: GEBIT's own `datatype.Timestamp`/`OffsetTimestamp` (`{"seconds":"..","nanos":..,"offset":60}`)
      and `BDecimal{scale,intVal}`.
    - Receipt API: `google.protobuf.Timestamp` (RFC 3339 string), `basic.Decimal{value:"8.67"}`,
      and proto3 `optional` fields. Those fields print explicitly even when they hold `""`, which is
      why `simpleSale.json` shows `"storeName": ""`.
    - Mapping between the two shapes is the bulk of the receipt builder.
11. **Receipt stays binary inside JSON.** The `Closed`/`Cancelled` events carry
    `serializedReceiptFormat:"PROTOBUF"` plus base64 of a binary `Any(Receipt)`. A JSON-only
    consumer (SAM, the monitor) needs a decode step that holds the receipt descriptor.
12. **Non-ASCII.** `MessageToJson` escapes it by default (`ensure_ascii=True`): "Düsseldorf"
    becomes `Düsseldorf`. That is valid JSON and keeps the wire ASCII, which helps with the
    known solclientjs mangling. Java's JsonFormat writes raw UTF-8, so the bytes differ but the
    JSON is equivalent. Whitespace differs from Java too (`[{` style); no consumer may compare
    JSON text byte for byte.
13. **Timestamps.** The samples have `header.eventTimestamp` > `metadata.creationTimestamp` (event
    published after it was persisted); the spike sets both equal. `OffsetTimestamp.offset` is
    hard-coded to 60. For February 2027 this is correct (CET), but it should come from
    `zoneinfo("Europe/Berlin")`.
14. **Reflection.**
    - grpcio-reflection only ships v1alpha. grpcurl tries v1 first and falls back, and newer
      Postman prefers v1, so the spike adds a v1 alias.
    - The reflection servicer must get `pool=pool`. Otherwise it serves the default pool and
      cannot find the GEBIT service.
15. **Async commands.** As at GEBIT, `AddArticle` returns `Empty`. The POS UI learns `positionId`
    only from the `PositionAdded` event (correlation: `header.trace_id` -> `metadata.traceId`). The
    simulator UI therefore has to consume its own events, or the facade returns the events it
    emitted.
16. **Browser.** A browser cannot speak native gRPC. The Kasse UI needs either a REST/WebSocket
    facade in the same process, which calls the simulator core directly or goes through the gRPC
    client, or grpc-web through Envoy. The facade is the simpler option.
17. **Vendor material at deploy time.** The `.pb` files (267 KB + 52 KB, about 425 KB as base64)
    fit a ConfigMap (1 MiB limit) as `binaryData`.
    - `install.sh` should create the ConfigMap from a local path in `.env`
      (`GEBIT_DESCRIPTOR_DIR`), never from the repo. The same works on AKS.
    - The image contains no GEBIT content: no stubs and no protos.

## Estimate for the full simulator subset

What exists after the spike (about 600 lines of code):

- pool loader
- generic server and client
- 5 RPCs with GEBIT-exact event sequences for a simple sale
- minimal receipt
- reflection, health
- topic and user-property derivation
- golden test against the samples

| Work package | Person-days |
|---|---|
| Productionise the spike (config, logging, graceful shutdown, aio or sync choice, unit and golden tests vs GEBIT samples) | 1.0 |
| Remaining booth commands with event sequences: ChangeArticlePositionItemCount, VoidArticlePosition, CreateEftPayment (card), AssignLoyaltyMembership (calls the simulated loyalty service), Apply%/AbsoluteArticlePositionDiscount or OverrideArticlePositionPrice, ApplyArticlePositionPromotion, AddExtensionProperties, GetPurchaseTransaction query | 2.5 |
| Pricing engine: article prices **read from Postgres** (so approved price changes take effect at the till), positionDiscounts and setDiscounts, loyalty re-pricing, tax per class | 2.0 |
| Full Receipt builder (receipt API shapes, `simpleSale.json` as golden file) | 1.5 |
| Postgres persistence (baskets, positions, payments) plus a transactional outbox for events | 1.5 |
| Solace publisher (SMF or MQTT like BSG, topics, user properties, application message id, reconnect) | 1.0 |
| GEBIT rich error model (`ErrorMessage` in status details via grpcio-status) | 0.5 |
| Container, k8s manifests (descriptor ConfigMap from a local path, `grpc:` probes, Service), lab ingress for gRPC with TLS and the lab CA for grpcurl/Postman | 1.5 |
| **Total** | **about 11.5 (range 9-13)** |

Not included:

- the Kasse UI and the REST/WS facade (separate track)
- the monitor UI
- the loyalty service itself
- SAM wiring

A minimal booth variant would cost about 5-6 person-days: the 5 spike RPCs plus item-count and
line void, Postgres prices, the Solace publisher, a light receipt, and manifests.

Risks:

- Pricing fidelity for discounts and loyalty. There are no GEBIT samples for those sequences, so
  the event shapes for them are derived from the protos, not observed. Ask GEBIT for one IT event
  dump with a discount and with loyalty.
- gRPC through NGINX ingress needs TLS and the `GRPC` backend protocol (not tested yet).

## Files

- `.../impl/grpc-spike/gebitsim/descriptors.py`: pool loader, class cache
- `.../impl/grpc-spike/gebitsim/events.py`: event builder, topic, user properties, JSONL sink
- `.../impl/grpc-spike/gebitsim/sim.py`: the 5 RPCs, in-memory state, pricing, minimal receipt
- `.../impl/grpc-spike/gebitsim/server.py`: generic server, reflection v1alpha+v1, health, CLI
  (`GEBIT_DESCRIPTOR_SETS=a.pb:b.pb python -m gebitsim.server --port 50051 --events out.jsonl`)
- `.../impl/grpc-spike/gebitsim/client.py`: generic client
- `.../impl/grpc-spike/tools/run_spike.py`: the 18 checks and latency;
  `tools/roundtrip_samples.py`, `tools/pitfalls.py`, `tools/aio_check.py`, `tools/coldstart.py`
- `.../impl/grpc-spike/out/results.json`, `out/events.jsonl`, `out/sim_PositionAdded.json`,
  `out/sim_PurchaseTransactionClosed.json`

(`...` = `<scratchpad>`)
