---
name: acme-knowledge-guide
description: How to use the five Acme Claims Knowledge MCP tools (policy wordings, claims guidelines, partner contracts, storm playbooks in Qdrant). Load before answering any clause, guideline, contract or playbook question to pick the right search tool, choose top_k, and cite doc_id plus title with the decisive sentence quoted.
---

# Acme Claims Knowledge guide

The connector `Acme Claims Knowledge` exposes five MCP tools over the
Qdrant collection `acme_knowledge` (52 documents, semantic search with
cosine scores). Every document has `doc_id`, `doc_type`, `title`,
`section`, `effective_from`, `tags` and `text` (80-250 words).

The knowledge base is the RULE BOOK. The numbers of the current event
(claims by status, a partner's assignments waiting, exposure per
district, payment runs) live in the Acme Insurance DB and the intake
store -- never read them from here.

## Which tool for which question

- `search_policy_wordings(query, top_k)` -- what the CUSTOMER is
  entitled to: hail cover HC-7, deductible rules, repair network
  steering clause RN-3 (five-working-day slot rule), total loss
  definition TL-1, glass, rental car, duties, exclusions, fleets,
  replacement value.
- `search_claims_guidelines(query, top_k)` -- how ACME handles a
  claim: Fast Lane CG-FL-1, Total Loss Fastlane CG-TL-2, BaFin 30-day
  rule CG-BAFIN-30, fraud indicators CG-FR-5, repeat contacts and
  complaints CG-CX-3, severity bands, status model and 4-hour stall
  threshold, holds, payment run rules, AI oversight, scanner
  results, estimate review.
- `search_partner_contracts(query, top_k)` -- what a PARTNER owes or
  what Acme may activate: capacities, second shift, overflow clause,
  INACTIVE status and the interim contract IC-2, pick-up and remote
  valuation, rental pre-booking, rate card and the 25 percent
  deviation threshold, workshop W-0471, network service levels.
- `search_storm_playbooks(query, top_k)` -- how to PLAN for a cell:
  conversion assumptions, options a-d, capacity math, SMS release
  rule, readiness stages, lessons learned from HZ-0907 and
  Reutlingen 2023.
- `get_knowledge_document(doc_id)` -- the full text of one document
  by id (e.g. `PW-RN-3`). Use it after a search hit to quote the
  decisive sentence completely, or when the user names a doc_id.

Each search returns a JSON list of `{doc_id, title, section, score,
text}` sorted by score (1.0 = identical). The lookup returns
`{doc_id, doc_type, title, section, effective_from, tags, text}`.
A `top_k` outside 1-20 is clamped, not rejected. A reply with an
`error` or `hint` key (empty query, unknown doc_id, `results: []`
because the collection is unseeded, knowledge base unavailable) is
data, not a crash: fix the call or say the corpus is unavailable.

## top_k guidance

1. Default `top_k` is 5. One precise clause question ("what does
   RN-3 say about a missing slot"): 3. A survey question ("what do
   the playbooks say about rental cars"): 8-10. Maximum 20.
2. Put the domain words into the query: clause id (RN-3, TL-1),
   partner id (P-DELLENDOC), "second shift", "conversion",
   "interim contract". Scores below about 0.5 mean the query
   missed; rephrase or try the neighbouring doc_type.
3. When a topic spans two document types, search both and cite
   both: RN-3 is a policy clause (PW-RN-3) AND a partner service
   level (PC-SLA-1); the IC-2 activation is a contract lever
   (PC-IC-2, PC-DELLENDOC-2024) AND a playbook step (SP-STAGE-1).
4. Never run more than three searches for one question; fetch the
   full document instead of re-searching for a longer excerpt.

## Answer rules

1. Cite every statement as doc_id + title, e.g. PW-RN-3 "Repair
   network steering clause RN-3".
2. Quote the decisive sentence verbatim in quotation marks, then
   apply it to the question in your own words (dates, partner ids,
   counts from the question).
3. Never invent clause numbers, capacities, rates or dates. If the
   corpus is silent, say so and name the closest document.
4. Keep rule book and live numbers apart: the contract says
   P-BRAENDLE is contracted for 120 scans per day; how many
   vehicles wait there today is a question for the Acme Insurance
   Query Expert (Postgres), not for this connector.
5. For a workflow node or a peer agent, return the key rules as
   short bullets with doc_ids; keep each quote under 40 words.
6. Do not create artifacts for knowledge answers; the excerpts are
   small enough for the chat.

## Key documents (doc_id -- decisive sentence)

Policy wordings:

- PW-HC-7 "Hail cover HC-7" -- deductible once per hail event; glass
  repaired via the partner network without deductible.
- PW-RN-3 "Repair network steering clause RN-3" -- 15 percent
  discount; "if no partner slot is offered within 5 working days
  after FNOL, the customer's free choice of workshop applies and
  the discount stays".
- PW-TL-1 "Total loss definition" -- estimate above 70 percent of
  replacement value, OR glass shattered + roof deformed + more than
  150 dents -> Total Loss Fastlane track.

Claims guidelines:

- CG-FL-1 "Fast Lane criteria" -- MINOR: glass or dents, estimate
  below EUR 1,000, policy active, hail cover -> auto-confirm,
  drive-in slot proposal, no adjuster; the Fast Lane never pays out.
- CG-TL-2 "Total Loss Fastlane" -- assistance pick-up, remote
  valuation, settlement target 5 working days; never in a drive-in
  queue.
- CG-BAFIN-30 "Processing-time rule" -- decision within 30 days,
  "volume is no excuse", day-20 escalation to the claims lead.
- CG-FR-5 "Fraud indicators guideline" -- EXIF before the event,
  same VIN via two channels within 48 h, estimate more than 25
  percent above contracted rate, identical line items, scanner
  deviation above 50 percent; the GDV sentence, quote it verbatim:
  "a single indicator proves nothing, the overall picture decides,
  a human specialist decides; never delay the honest majority".
- CG-CX-3 "Repeat contact and complaint handling" -- repeat calls
  are the earliest stall signal; complaint-flagged customers are
  never moved down a queue automatically.

Partner contracts:

- PC-BRAENDLE-2025 -- 120 scans/day; second shift +60/day on 24 h
  notice; overflow clause after three days of capacity.
- PC-DELLENDOC-2024 -- INACTIVE since 2026-01-01, renewal blocked by
  unsigned parts-channel clause PC-4; "the interim contract template
  IC-2 allows a 48 hour activation under the old terms for NatCat
  events" (90 scans/day).
- PC-IC-2 "Interim contract template IC-2" -- warning level 3
  trigger, 24 h confirmation, operations within 48 h, at most 60
  days, open renewal disputes parked.
- PC-ROADASSIST-2025 -- pick-up + remote valuation, 200 vehicles/day,
  standby reservation 24 h ahead.
- PC-RENTAFLEET-2026 -- pre-booking with 24 h notice, up to 150
  cars; standing pool about 35 cars in Ludwigsburg.
- PC-RATES-2026 -- hourly EUR 118.00, paint EUR 96.00; deviation
  review threshold 25 percent.

Storm playbooks:

- SP-NATCAT-4 "NatCat hail playbook v4" -- planning conversion 30
  percent of no-garage vehicles, property 18 percent; options (a)
  3 mobile units, 90 scans/day each, 24 h lead, (b) rental
  pre-booking, (c) warning SMS released by a human, (d) pre-staged
  Fastlane; capacity math example.
- SP-HZ-0907 "Lessons learned HZ-0907" -- conversion 0.28 on a 2 cm
  cell; "cells with 3 cm hail and more convert far higher".
- SP-REUTLINGEN-2023 -- 3.5 cm cell, conversion 0.58, rental cars
  gone on day two, total losses stuck in scan queues.

Filler documents (glass, deductibles, property hail cover, complaint
escalation, photo data protection, payment runs, holds, capacity
worksheet, readiness stages, body shop and drive-in contracts) exist
so that a search must be specific; cite them when they are the best
hit, but prefer the anchors above for the demo questions.
