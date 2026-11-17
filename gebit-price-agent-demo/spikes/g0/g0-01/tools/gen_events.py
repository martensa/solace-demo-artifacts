"""Generate the G0-01 test events with gebitsim (spikes/grpc-spike).

Runs in the gpos-g0-grpc:spike image (protobuf + gebitsim), with the
GEBIT descriptor set mounted READ-ONLY at runtime; the output is a JSONL
file OUTSIDE the repo (the events are GEBIT-format, vendor material):

  docker run --rm --entrypoint python \
    -v ~/Downloads/Gebit/purchase-api-2.50.0.pb:/d/purchase.pb:ro \
    -v $PWD/tools:/g0:ro -v <scratchpad>/g0-01:/out \
    gpos-g0-grpc:spike /g0/gen_events.py --out /out/events.jsonl

Every payload is the strict proto3 JSON of google.protobuf.Any (with
'@type'), built by gebitsim's EventFactory (ParseDict strict, so a typo
fails), pretty-printed like GEBIT's samples. Article texts carry
umlauts, ss, typographic quotes and en dashes. Six baskets, 20 events:
3x PositionAdded article030 (TR2, verdict price_trigger), 3x
LoyaltyMembershipAssigned (card, verdict member), 14 others (default).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid

sys.path.insert(0, "/app")
from gebitsim.descriptors import Types, load_pool  # noqa: E402
from gebitsim.sim import Basket, Position, Simulator  # noqa: E402

ST = "PURCHASE_TRANSACTION_STATUS_"
# articleNumber -> (description, gross cents, taxClass, rate bp); fictional
ART = {
    "article030": ("Kaffeepads Röstung „Würzig“ 36 Stück", 499, "A", 700),
    "article004": ("GEBIT Ente – Quietscheente Größe M", 867, "C", 1900),
    "article007": ("Espresso Bohnen 1 kg – Röstung „Süditalien“", 799, "A", 700),
    "article001": ("Kartoffelchips Meersalz 175 g", 199, "A", 700),
    "article011": ("Bio-Äpfel Elstar 1 kg, Klasse I", 249, "A", 700),
    "article017": ("Valentins-Pralinen „Herzensgrüße“ 250 g", 699, "A", 700),
    "article019": ("Fruchtgummi Bärchen sauer 300 g", 129, "A", 700),
    "article025": ("Brötchen Sesam 6 Stück – Bäckerei Süß", 189, "A", 700),
}
PLAN = [  # (basket, event, article); <= 3 positions keeps 2.6-5.5 KB
    ("A", "PositionAdded", "article030"), ("A", "PositionAdded", "article004"),
    ("A", "PositionAdded", "article007"),
    ("B", "PositionAdded", "article011"), ("B", "PositionAdded", "article030"),
    ("B", "LoyaltyMembershipAssigned", ""), ("B", "PaymentProcessStarted", ""),
    ("C", "PositionAdded", "article004"), ("C", "PositionAdded", "article017"),
    ("C", "PositionAdded", "article001"),
    ("D", "PositionAdded", "article030"), ("D", "LoyaltyMembershipAssigned", ""),
    ("D", "PositionAdded", "article019"), ("D", "PaymentProcessStarted", ""),
    ("E", "PositionAdded", "article025"), ("E", "LoyaltyMembershipAssigned", ""),
    ("E", "PositionAdded", "article011"), ("E", "PaymentProcessStarted", ""),
    ("F", "PositionAdded", "article007"), ("F", "PositionAdded", "article017"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pb", default="/d/purchase.pb")
    ap.add_argument("--out", required=True)
    ap.add_argument("--topic-root", default="gpos/spike/p01/pos")
    a = ap.parse_args()
    types = Types(load_pool([a.pb]))
    sim = Simulator(types, sink=None)
    baskets: dict[str, Basket] = {}
    n = 0
    with open(a.out, "w", encoding="utf-8") as fh:
        for key, name, art in PLAN:
            b = baskets.get(key)
            if b is None:
                b = baskets[key] = Basket(str(uuid.uuid4()), "Root.DE.999.101.01",
                                          "ID199901", "CD01", created_ns=time.time_ns())
                b.offset = 2  # Created, Opened before the first position
            trace = f"g0-01-{key}-{b.offset + 1}"
            if name == "PositionAdded":
                desc, cents, cls, rate = ART[art]
                p = Position(str(uuid.uuid4()), "ID" + art, art, desc, 1, cents, cls, rate)
                b.positions.append(p)
                body = {"positionId": p.position_id,
                        "articlePositionType": "ARTICLE_POSITION_TYPE_SALE",
                        "articleId": p.article_id, "articleNumber": art, "itemCount": 1,
                        "description": desc, "pricingInformation": sim.pricing(b),
                        "createdAt": {"seconds": str(int(time.time())), "nanos": 0,
                                      "offset": 60},
                        "purchaseTransactionStatus": ST + "OPEN",
                        "capturingInformation": {"inputValue": "40" + art[-3:] + "0012345"}}
            elif name == "LoyaltyMembershipAssigned":
                body = {"membershipPositionId": str(uuid.uuid4()),
                        "pricingInformation": sim.pricing(b),
                        "purchaseTransactionStatus": ST + "OPEN",
                        "capturingInformation": {"inputValue": "9276000100012345"},
                        "extensionProperties": [
                            {"key": "programName",
                             "typedValue": {"stringValue": "Kundenkarte „Kaffeepause“ – Grün"}},
                            {"key": "anrede", "typedValue": {"stringValue": "Sie"}}],
                        "paymentSessionSums": sim.sums(b)}
            else:
                body = {"purchaseTransactionStatus": ST + "IN_PAYMENT",
                        "paymentSessionSums": sim.sums(b),
                        "pricingInformation": sim.pricing(b)}
            e = sim.ev.build(name, body, tx_id=b.tx_id, location=b.location,
                             offset=b.next_offset(), trace_id=trace)
            # MessageToJson escapes non-ASCII (\u00fc); GEBIT's samples carry raw
            # UTF-8, so re-render with the same 2-space layout and key order.
            payload = json.dumps(json.loads(e.payload), indent=2, ensure_ascii=False)
            n += 1
            seq = f"p01-{n:02d}"
            fh.write(json.dumps({"seq": seq, "event": name, "article": art,
                                 "topic": f"{a.topic_root}/{name}/{b.tx_id}",
                                 "bytes": len(payload.encode()),
                                 "payload": payload}, ensure_ascii=False) + "\n")
            print(f"{seq} {name:26} {art:10} {len(payload.encode()):5d} B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
