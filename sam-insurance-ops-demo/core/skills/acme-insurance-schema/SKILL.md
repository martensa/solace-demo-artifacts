---
name: acme-insurance-schema
description: Exact schema of the acme_insurance postgres database (tables ins_customers, ins_policies, ins_claims, ins_repair_partners, ins_workshop_estimates, ins_payment_items). Load before writing any SQL against the Acme Insurance DB connector to get correct table and column names, data types, value domains, the aggregation rules for the 10,400-claim table and the fixed snapshot time.
---

# Acme Insurance database schema

Database `acme_insurance` has exactly SIX tables. Everything in it
belongs to ONE hail event, `HZ-0913` (Sat 2026-07-18 18:40, Landkreis
Boeblingen). The data snapshot is Mon 2026-07-20 10:00 -- that is
"now" for every age or waiting-time calculation.

## Table: ins_customers (51,525 rows, one per policy holder)

| Column | Type | Notes |
|---|---|---|
| customer_id | text | primary key, e.g. CUS-000001 |
| full_name | text | synthetic name or company (FLEET) |
| city / postal_code | text | same address as the holder's policies |
| segment | text | PRIVATE, FLEET |
| preferred_channel | text | same domain as ins_claims.fnol_channel |
| complaint_flag | boolean | true = formal complaint on file |

## Table: ins_policies (68,700 rows)

| Column | Type | Notes |
|---|---|---|
| policy_id | text | primary key, e.g. POL-000001 |
| customer_id | text | joins ins_customers |
| product | text | MOTOR_COMPREHENSIVE, MOTOR_PARTIAL, PROPERTY |
| vehicle_vin / vehicle_model | text | NULL for PROPERTY |
| garage_parking | boolean | NULL for PROPERTY; false = no garage |
| postal_code / city | text | |
| district | text | BOEBLINGEN, LUDWIGSBURG, STUTTGART, ESSLINGEN |
| hail_cover | boolean | clause HC-7 active |
| deductible_eur | integer | |
| repair_network_clause | boolean | clause RN-3 (15 % discount, steering) |
| status | text | ACTIVE |
| start_date | date | |

## Table: ins_claims (10,400 rows -- ALWAYS aggregate)

| Column | Type | Notes |
|---|---|---|
| claim_id | text | primary key, CLM-0913-00001 .. CLM-0913-10400 |
| policy_id | text | joins ins_policies |
| event_id | text | HZ-0913 (all rows) |
| line | text | MOTOR, PROPERTY |
| fnol_channel | text | APP, VOICE_AGENT, WORKSHOP_PORTAL, DRIVE_IN_SCANNER, AGENCY_EMAIL |
| reported_at | timestamp | first notice of loss |
| severity | text | MINOR, MODERATE, SEVERE |
| status | text | RECEIVED, CONFIRMED, AWAITING_WORKSHOP_SLOT, IN_REPAIR, TOTAL_LOSS_FASTLANE, ON_HOLD |
| status_since | timestamp | when the current status was entered |
| assigned_partner_id | text | joins ins_repair_partners, NULL if none |
| estimate_eur | integer | NULL while no estimate exists |
| reserve_eur | integer | case reserve |
| drivable | boolean | NULL for PROPERTY |

## Table: ins_repair_partners (10 rows)

| Column | Type | Notes |
|---|---|---|
| partner_id | text | primary key, e.g. P-BRAENDLE |
| name / city / postal_code | text | |
| partner_type | text | DRIVE_IN, BODY_SHOP, ASSISTANCE, RENTAL |
| contract_status | text | ACTIVE, INACTIVE |
| contract_status_since | date | |
| contract_note | text | free text (contract ids, workshop code) |
| tier | text | PREMIUM, STANDARD |
| daily_scan_capacity | integer | DRIVE_IN only, NULL otherwise |
| contracted_hourly_rate_eur | numeric | 118.00 for repairers |
| contracted_paint_rate_eur | numeric | 96.00 for repairers |
| rental_cars_available | integer | RENTAL only |

## Table: ins_workshop_estimates (1,600 rows)

| Column | Type | Notes |
|---|---|---|
| estimate_id | text | primary key, EST-<claim suffix> |
| claim_id | text | joins ins_claims (one estimate per claim) |
| partner_id | text | joins ins_repair_partners |
| hours | numeric | labour hours |
| hourly_rate_eur / paint_rate_eur | numeric | rates USED in this estimate |
| total_eur | numeric | = hours * (hourly_rate_eur + paint_rate_eur) |
| line_item_text | text | free text |
| submitted_at | timestamp | |

## Table: ins_payment_items (3,900 rows)

| Column | Type | Notes |
|---|---|---|
| payment_item_id | text | primary key, PI-30-00001 .. |
| payment_run_id | text | PR-2026-30 (all rows) |
| claim_id | text | joins ins_claims |
| payee_type | text | CUSTOMER, WORKSHOP |
| payee_partner_id | text | WORKSHOP items only |
| iban_hash | text | hashed payee account |
| amount_eur | numeric | |
| status | text | SCHEDULED |
| scheduled_for | timestamp | 2026-07-24 16:00 (all rows) |

## Query rules

1. Use exactly these table/column names; there are no other tables.
2. Scale: ins_claims has 10,400 rows and ins_policies 68,700.
   ALWAYS aggregate (COUNT, SUM, GROUP BY) on them; never
   `SELECT *` on ins_claims without a claim_id filter and a LIMIT
   of at most 50. Return lists of ids only when asked for records
   to inspect, and cap them at 50.
3. The clock is fixed: "now" is `timestamp '2026-07-20 10:00'`.
   Never use now() or CURRENT_DATE. "Waiting longer than 4 hours"
   means `status_since < timestamp '2026-07-20 06:00'`.
4. Joins: claims.policy_id -> policies; policies.customer_id ->
   customers; claims.assigned_partner_id -> partners;
   estimates.claim_id -> claims; payment_items.claim_id -> claims
   and payment_items.payee_partner_id -> partners.
5. Exposure = ins_policies, motor products (`product <> 'PROPERTY'`)
   per district; "without garage" = `garage_parking = false`
   (property rows are NULL, so always filter explicitly).
6. Partner load = COUNT of ins_claims per assigned_partner_id in
   status AWAITING_WORKSHOP_SLOT, compared with daily_scan_capacity
   (drive-ins only; body shops have NULL capacity).
7. Workshop code W-0471 is partner P-KAROSSERIE-SCHNELL (the code
   appears in contract_note). Contracted rates live in
   ins_repair_partners; deviations live in ins_workshop_estimates:
   compare each estimate's hourly_rate_eur / paint_rate_eur with
   the partner's contracted rates.
8. Cross-store: intake documents (narratives, photos with EXIF
   timestamps, damage signals, repeat contacts, voice transcripts),
   drive-in scanner results and weather cells live in MongoDB
   (Storm Intake Analyst). Policy wordings (HC-7, RN-3, TL-1),
   claims guidelines, partner contracts and storm playbooks live in
   the knowledge base (Acme Claims Knowledge Expert). No cross-store
   JOINs; correlate via claim_id, partner_id and document ids at
   the analysis level.
9. Money columns are plain numeric or integer (no money type);
   use `ROUND(SUM(...), 2)` for report figures.

For value domains, the storyline layout and ready-made example
queries, read `references/schema.md`.
