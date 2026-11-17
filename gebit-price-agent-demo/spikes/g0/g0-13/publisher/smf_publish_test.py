"""G0-13 Teil B: persistentes SMF-Publish mit solace-pubsubplus auf VPN sam.

Modes:
  publish  sendet --count Nachrichten persistent (je die Haelfte an
           gebit/rp/purchase/v2/... und gpos/v1/..., Topic-Form Plan 2.4)
           und wartet je Nachricht auf das Broker-Ack
  consume  liest --expect Nachrichten aus --queue, prueft Topic, User
           Properties, Application Message ID und UTF-8-Payload, quittiert

Umgebung: SOLACE_HOST (z. B. tcp://host.docker.internal:55557), SOLACE_VPN,
SOLACE_USERNAME, SOLACE_PASSWORD (nie ausgegeben). Jede Ausgabezeile ist
JSON. Payloads sind synthetisch (kein GEBIT-Material).
"""
import argparse
import json
import os
import platform
import sys
import time
import uuid

from importlib.metadata import version

from solace.messaging.config.solace_properties import (
    authentication_properties as auth,
    service_properties as svc,
    transport_layer_properties as tl,
)
from solace.messaging.messaging_service import MessagingService
from solace.messaging.resources.queue import Queue
from solace.messaging.resources.topic import Topic

TEXT = "Grüße: ä ö ü ß €"   # UTF-8-Rundweg (vgl. G0-09)
STORE = "DE/999/101"
TILL = "99"                    # nicht die Standkasse 01 (Regel R1 filtert 01)

# (Topic-Vorlage, eventType); gpos/v1 nur Topics ohne SAM-Regel (R2-R5)
GEBIT = [
    ("gebit/rp/purchase/v2/basket/PositionAdded/{store}/{till}/{tx}", "PositionAdded"),
    ("gebit/rp/purchase/v2/basket/PositionAdded/{store}/{till}/{tx}", "PositionAdded"),
    ("gebit/rp/purchase/v2/basket/PositionAdded/{store}/{till}/{tx}", "PositionAdded"),
    ("gebit/rp/purchase/v2/basket/PositionAdded/{store}/{till}/{tx}", "PositionAdded"),
    ("gebit/rp/purchase/v2/purchase_transaction/PurchaseTransactionClosed/{store}/{till}/{tx}",
     "PurchaseTransactionClosed"),
]
GPOS = [
    ("gpos/v1/health/g0-13-{run}", "Health"),
    ("gpos/v1/samrun/g0-13-{run}", "SamRun"),
    ("gpos/v1/proposal/draft/101/article004/prp-g0-13-{run}", "ProposalDraft"),
    ("gpos/v1/approval/pending/prp-g0-13-{run}", "ApprovalPending"),
    ("gpos/v1/offer/tied_offer/{tx}", "OfferPublished"),
]


def log(kind, **kw):
    print(json.dumps({"t": round(time.time(), 3), "kind": kind, **kw}, ensure_ascii=False), flush=True)


def connect(client_name):
    props = {
        tl.HOST: os.environ["SOLACE_HOST"],
        svc.VPN_NAME: os.environ["SOLACE_VPN"],
        auth.SCHEME_BASIC_USER_NAME: os.environ["SOLACE_USERNAME"],
        auth.SCHEME_BASIC_PASSWORD: os.environ["SOLACE_PASSWORD"],
        svc.GENERATE_SENDER_ID: True,
        svc.GENERATE_SEND_TIMESTAMPS: True,
    }
    t0 = time.perf_counter()
    ms = MessagingService.builder().from_properties(props).build(client_name)
    ms.connect()
    log("connected", host=os.environ["SOLACE_HOST"], vpn=os.environ["SOLACE_VPN"],
        client=client_name, ms=round((time.perf_counter() - t0) * 1000, 1),
        sdk=version("solace-pubsubplus"), arch=platform.machine(),
        python=platform.python_version())
    return ms


def plan(run, count):
    tx = str(uuid.uuid4())
    items = []
    for i in range(count):
        tpl, ev = (GEBIT[i // 2 % len(GEBIT)] if i % 2 == 0 else GPOS[i // 2 % len(GPOS)])
        topic = tpl.format(store=STORE, till=TILL, tx=tx, run=run)
        agg = tx if topic.startswith("gebit/") else f"g0-13-{run}"
        items.append((topic, ev, agg, i + 1, tx))
    return items


def do_publish(a):
    ms = connect(f"gpos-g0-13-pub-{a.run}")
    pub = ms.create_persistent_message_publisher_builder().build()
    pub.start()
    lat = []
    for topic, ev, agg, off, tx in plan(a.run, a.count):
        body = {
            "@type": "type.googleapis.com/gpos.g0.SpikeEvent",
            "metadata": {"offset": str(off), "traceId": f"g0-13-{a.run}"},
            "eventType": ev, "purchaseTransactionId": tx, "text": TEXT,
            "arch": platform.machine(),
        }
        msg = (ms.message_builder()
               .with_application_message_id(f"{agg}:{off}")
               .with_http_content_header("application/json", "utf-8")
               .with_property("eventType", ev)
               .with_property("purchaseTransactionId", tx)
               .with_property("offset", str(off))
               .with_property("traceId", f"g0-13-{a.run}")
               .with_property("apiVersion", "g0-13-spike")
               .with_property("source", "sim")
               # bytearray = binaeres Attachment; bytes scheitert im SDK
               # ("Failed to create attachment", auch unter 3.12), str wird
               # zum SDT-String (G0-13)
               .build(bytearray(json.dumps(body, ensure_ascii=False).encode("utf-8"))))
        t0 = time.perf_counter()
        pub.publish_await_acknowledgement(msg, Topic.of(topic), time_out=5000)
        ms_ack = round((time.perf_counter() - t0) * 1000, 2)
        lat.append(ms_ack)
        log("acked", n=off, topic=topic, app_msg_id=f"{agg}:{off}", ack_ms=ms_ack)
    lat.sort()
    log("publish_done", count=len(lat), ack_ms_p50=lat[len(lat) // 2], ack_ms_max=lat[-1])
    if a.hold:   # Sitzung offen halten, damit SEMP die Client-Statistik zeigt
        time.sleep(a.hold)
    pub.terminate(grace_period=2000)
    ms.disconnect()
    log("disconnected")


def do_consume(a):
    ms = connect(f"gpos-g0-13-sub-{a.run}")
    rx = ms.create_persistent_message_receiver_builder().build(Queue.durable_exclusive_queue(a.queue))
    rx.start()
    seen, bad = [], []
    deadline = time.time() + a.timeout
    while len(seen) < a.expect and time.time() < deadline:
        m = rx.receive_message(timeout=2000)
        if m is None:
            continue
        p = m.get_properties() or {}
        raw = m.get_payload_as_bytes() or b""
        try:
            body = json.loads(raw.decode("utf-8"))
        except ValueError:
            body = {}
        checks = {
            "props": all(k in p for k in ("eventType", "purchaseTransactionId", "offset",
                                          "traceId", "apiVersion", "source")),
            "app_msg_id": (m.get_application_message_id() or "").endswith(":" + str(p.get("offset"))),
            "utf8": body.get("text") == TEXT,
            "type": body.get("@type", "").startswith("type.googleapis.com/"),
            "topic": (m.get_destination_name() or "").startswith(("gebit/rp/", "gpos/v1/")),
        }
        rgmid = m.get_replication_group_message_id()
        seen.append(m.get_destination_name())
        if not all(checks.values()):
            bad.append({"topic": m.get_destination_name(), "checks": checks})
        log("received", topic=m.get_destination_name(), app_msg_id=m.get_application_message_id(),
            redelivered=m.is_redelivered(), rgmid=str(rgmid) if rgmid else None,
            arch_of_publisher=body.get("arch"), ok=all(checks.values()))
        rx.ack(m)
    rx.terminate(grace_period=2000)
    ms.disconnect()
    log("consume_done", received=len(seen), expected=a.expect, bad=len(bad),
        gebit=sum(1 for s in seen if s.startswith("gebit/")),
        gpos=sum(1 for s in seen if s.startswith("gpos/")))
    sys.exit(0 if len(seen) == a.expect and not bad else 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["publish", "consume"])
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--expect", type=int, default=10)
    ap.add_argument("--queue", default="gpos-g0-test")
    ap.add_argument("--run", default=uuid.uuid4().hex[:6])
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--hold", type=float, default=0.0)
    a = ap.parse_args()
    do_publish(a) if a.mode == "publish" else do_consume(a)


if __name__ == "__main__":
    main()
