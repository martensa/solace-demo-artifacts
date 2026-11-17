#!/usr/bin/env python3
"""gpos approval requests in the SAM inbox of the store manager (spec 12.6).

  sam_inbox.py list                 open gpos requests (hil, pending, Ref GP-...)
  sam_inbox.py cancel-gpos          cancel every open gpos request (reset step 6)
  sam_inbox.py answer REF approve|deny
                                    answer the oldest open request of one proposal
  sam_inbox.py watch                inbox watcher during the fair (make demo-watch)
  sam_inbox.py hygiene              count read gpos notifications (A-23)

Only entries of SAM_RUN_IDENTITY (marktleitung@solace.lab), category hil,
promptState pending, whose JSON names `Ref GP-...` (fallback A-6: the A2UI info
names Agent "gpos-price-approver"). Uses `sam api` as sam_admin (the CLI login
cache); answers on behalf of the store manager via ?userId= (G0-02 T6/T8).

watch polls every 0.5 s and reads each proposal through the BFF
(GET /api/proposals/{id}): the FIRST request of a pending proposal stays for the
store manager; a further request of the same Ref is a duplicate -> approve when
the price is already active (the gate answers already_applied, the monitor shows
the banner), else cancel; every request whose proposal is not pending (reset,
watchdog, expiry, orphan after an awe restart) -> cancel. build/sam_inbox.lock
keeps watch and e2e.py apart (e2e.py applies the same rules).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Mapping

from opslib import (RUN_IDENTITY_DEFAULT, Bff, Decision, Inbox, InboxItem, OpsError, SamApi,
                    decide, demo_env, exclusive_lock, with_ref)

POLL_S = 0.5


def make_inbox(env: Mapping[str, str]) -> Inbox:
    return Inbox(SamApi(env), env.get("SAM_RUN_IDENTITY", RUN_IDENTITY_DEFAULT))


def item_line(item: InboxItem) -> str:
    return json.dumps({"id": item.id, "createdAt": item.created_at, "ref": item.ref,
                       "agent": item.agent})


def cmd_list(inbox: Inbox) -> int:
    pending = inbox.pending_gpos()
    for item in pending:
        print(item_line(item))
    print(f"open gpos requests: {len(pending)}", file=sys.stderr)
    return 0


def cmd_cancel(inbox: Inbox) -> int:
    pending = inbox.pending_gpos()
    for item in pending:
        inbox.respond(item.id, None)
        print(f"cancelled {item.id} ({item.ref or item.agent})")
    print(f"cancelled gpos requests: {len(pending)}")
    return 0


def cmd_answer(inbox: Inbox, ref: str, answer: str) -> int:
    item = next((i for i in inbox.pending_gpos() if i.ref == ref), None)
    if item is None:
        print(f"no open request with Ref {ref}", file=sys.stderr)
        return 1
    inbox.respond(item.id, answer == "approve")
    print(f"{answer} {item.id} (Ref {ref})")
    return 0


def read_proposals(bff: Bff, refs: set[str]) -> dict[str, dict | None]:
    """ref -> proposal (None = unknown); a ref that cannot be read is left out
    so its request is left alone this round."""
    found: dict[str, dict | None] = {}
    for ref in refs:
        try:
            found[ref] = bff.proposal(ref)
        except Exception as exc:  # noqa: BLE001 -- network trouble: decide next round
            print(f"watch: proposal {ref} not readable ({type(exc).__name__})", file=sys.stderr)
    return found


def apply_decisions(inbox: Inbox, decisions: list[Decision], done: set[str]) -> None:
    for decision in decisions:
        if decision.action == "keep" or decision.item_id in done:
            continue
        inbox.respond(decision.item_id, True if decision.action == "approve" else None)
        done.add(decision.item_id)
        print(f"{time.strftime('%H:%M:%S')} {decision.action} {decision.item_id} "
              f"Ref {decision.ref}: {decision.reason}", flush=True)


def cmd_watch(inbox: Inbox, bff: Bff) -> int:
    first_by_ref: dict[str, str] = {}
    done: set[str] = set()
    print(f"watching the inbox of {inbox.user} every {POLL_S} s (Ctrl-C ends)", flush=True)
    while True:
        started = time.monotonic()
        try:
            pending = [i for i in inbox.pending_gpos() if i.id not in done]
            if any(i.ref is None for i in pending):          # fallback A-6
                pending = with_ref(pending, bff.booth_proposal_id())
            refs = {i.ref for i in pending if i.ref}
            apply_decisions(inbox, decide(pending, read_proposals(bff, refs), first_by_ref),
                            done)
        except OpsError as exc:
            print(f"watch: {exc}", file=sys.stderr, flush=True)
        time.sleep(max(0.0, POLL_S - (time.monotonic() - started)))


def cmd_hygiene(inbox: Inbox) -> int:
    """A-23: no documented delete/archive path for read notifications exists in
    2.542.1 (G0-04 T7/T7b open); count them and point to the runbook."""
    body = inbox.api.call("GET", f"/api/v1/notify/inbox?userId={inbox.user}&pageSize=100")
    data = body.get("data") if isinstance(body, dict) else body
    if isinstance(data, dict):
        data = data.get("items")
    gpos = [x for x in (data or []) if isinstance(x, dict) and "Ref GP-" in json.dumps(x)]
    print(f"gpos notifications in the inbox of {inbox.user}: {len(gpos)} "
          "(no API path to archive them, A-23; see RUNBOOK.md 'Posteingang')")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("list", "cancel-gpos", "watch", "hygiene"):
        sub.add_parser(name)
    answer = sub.add_parser("answer")
    answer.add_argument("ref")
    answer.add_argument("answer", choices=("approve", "deny"))
    args = ap.parse_args(argv)
    env = demo_env()
    try:
        inbox = make_inbox(env)
        if args.cmd == "list":
            return cmd_list(inbox)
        if args.cmd == "cancel-gpos":
            return cmd_cancel(inbox)
        if args.cmd == "answer":
            return cmd_answer(inbox, args.ref, args.answer)
        if args.cmd == "hygiene":
            return cmd_hygiene(inbox)
        with exclusive_lock("sam_inbox.py watch"):
            return cmd_watch(inbox, Bff(env))
    except KeyboardInterrupt:
        return 0
    except OpsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
