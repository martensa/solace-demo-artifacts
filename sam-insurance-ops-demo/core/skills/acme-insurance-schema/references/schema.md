# acme_insurance reference: value domains and example queries

## Categorical value domains (exact values in the data)

- ins_claims.line: MOTOR, PROPERTY
- ins_claims.fnol_channel: APP, VOICE_AGENT, WORKSHOP_PORTAL,
  DRIVE_IN_SCANNER, AGENCY_EMAIL
- ins_claims.severity: MINOR (glass / dents, estimate < 1,000 ->
  Fast Lane), MODERATE, SEVERE
- ins_claims.status: RECEIVED, CONFIRMED, AWAITING_WORKSHOP_SLOT,
  IN_REPAIR, TOTAL_LOSS_FASTLANE, ON_HOLD (valid, 0 rows at the
  snapshot -- the target status for a fraud hold)
- ins_claims.event_id: HZ-0913 (all rows)
- ins_policies.product: MOTOR_COMPREHENSIVE, MOTOR_PARTIAL, PROPERTY
- ins_policies.district: BOEBLINGEN, LUDWIGSBURG, STUTTGART,
  ESSLINGEN
- ins_policies.status: ACTIVE
- ins_customers.segment: PRIVATE, FLEET
- ins_repair_partners.partner_type: DRIVE_IN, BODY_SHOP,
  ASSISTANCE, RENTAL
- ins_repair_partners.contract_status: ACTIVE, INACTIVE
- ins_repair_partners.tier: PREMIUM, STANDARD
- ins_payment_items.payee_type: CUSTOMER, WORKSHOP
- ins_payment_items.status: SCHEDULED
- ins_payment_items.payment_run_id: PR-2026-30

## Partners (all 10 rows)

- P-BRAENDLE Braendle Drive-In Hail Center, Sindelfingen, DRIVE_IN,
  ACTIVE, 120 scans/day (640 claims AWAITING_WORKSHOP_SLOT)
- P-DELLENDOC Dellen-Doktor Sindelfingen, DRIVE_IN, INACTIVE since
  2026-01-01, 90 scans/day, note "tier renegotiation -- parts-channel
  clause PC-4 unsigned"
- P-KAROSSERIE-SCHNELL Karosserie Schnell GmbH, Boeblingen,
  BODY_SHOP (workshop code W-0471 in contract_note)
- P-AUTOWERK-BB Autowerk Boeblingen, BODY_SHOP
- P-LACKPROFI-LEO Lackprofi Leonberg, BODY_SHOP
- P-ROADASSIST RoadAssist Pick-up and Remote Valuation, Stuttgart,
  ASSISTANCE (pick-up + remote valuation for total losses)
- P-HAGELPOINT-LB Hagelpoint Ludwigsburg, DRIVE_IN, 100 scans/day
- P-DELLENFIX-LB Dellenfix Ludwigsburg, DRIVE_IN, 80 scans/day
- P-RENTAFLEET RentaFleet Ludwigsburg, RENTAL, 35 cars available
- Contracted rates for repairers: hourly 118.00, paint 96.00.

## Storyline layout (what the numbers should come out as)

- 10,400 claims: 9,650 MOTOR (CLM-0913-00001..09650), 750 PROPERTY
  (09651..10400). Severity 6,200 / 3,600 / 600 (motor 5,750 /
  3,340 / 560, property 450 / 260 / 40 -- the same split as the
  MongoDB intake documents). Status CONFIRMED 5,900,
  AWAITING_WORKSHOP_SLOT 2,140, IN_REPAIR 1,530,
  TOTAL_LOSS_FASTLANE 210, RECEIVED 620. Channels APP 4,160,
  VOICE_AGENT 2,600, WORKSHOP_PORTAL 1,560, DRIVE_IN_SCANNER 1,040,
  AGENCY_EMAIL 1,040 (property claims use APP, VOICE_AGENT and
  AGENCY_EMAIL only).
- Stalled cohort: 412 claims (CLM-0913-06001..06412) in
  AWAITING_WORKSHOP_SLOT at P-BRAENDLE since Sun 2026-07-19
  09:00..12:00; 293 of their policies have repair_network_clause
  (RN-3); 4 of their customers carry complaint_flag.
- Every other AWAITING_WORKSHOP_SLOT claim entered the status on
  Mon 2026-07-20 after 06:15, so "waiting > 4 h" returns exactly
  the cohort.
- Exposure: BOEBLINGEN 31,600 motor policies (15,800 without
  garage) + 1,900 property; LUDWIGSBURG 17,400 motor (8,900 without
  garage) + 2,300 property.
- Fraud act: CLM-0913-08103 scanner mismatch (DRIVE_IN_SCANNER,
  estimate 6,800, AWAITING at P-BRAENDLE); pattern A 08101..08119;
  pattern B 08201..08211 (APP) duplicated by 08301..08311
  (VOICE_AGENT, same policy and VIN); pattern C 08401..08417 at
  W-0471 with hourly 162.84 / paint 132.48 (+38 %), 08401..08409
  sharing one line_item_text.
- Payment run PR-2026-30 (Fri 2026-07-24 16:00): 3,900 items, EUR
  14,200,000.00. It contains payment items for flagged claims (the
  17 W-0471 workshop items, the customer items of the 11
  duplicate-VIN APP legs 08201..08211 and of the 6 VOICE legs
  08301..08306); the fraud report derives the EUR at risk from
  them (rehearsed: 34 items, EUR 178,648.07 to hold).
- Fast Lane samples: CLM-0913-00001..00040 (MINOR, RECEIVED,
  estimate 180..950). The 8 the cockpit publishes as FNOL events are
  pinned: CLM-0913-00001..00008 on policies POL-104211, POL-118902,
  POL-121377, POL-109654, POL-133018, POL-115486, POL-127730,
  POL-112245 (holders Lena Hartmann, Jonas Keller, Miriam Schaefer,
  Tobias Wagner, Selin Aydin, Markus Brandt, Anna Fischer, Daniel
  Roth; estimates 640, 420, 890, 310, 760, 540, 950, 180; all
  MOTOR_COMPREHENSIVE, hail_cover, no garage, district BOEBLINGEN).

## Example queries

Event overview by line, severity and status:

```sql
SELECT line, severity, status, COUNT(*) AS claims,
       SUM(reserve_eur) AS reserve_eur
FROM ins_claims
WHERE event_id = 'HZ-0913'
GROUP BY line, severity, status
ORDER BY line, severity, status;
```

Channel mix of the event:

```sql
SELECT fnol_channel, COUNT(*) AS claims,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct
FROM ins_claims
GROUP BY fnol_channel
ORDER BY claims DESC;
```

Stalled cohort: claims waiting for a workshop slot longer than 4 h,
by partner, with age (snapshot Mon 2026-07-20 10:00):

```sql
SELECT assigned_partner_id, COUNT(*) AS claims,
       ROUND(MIN(EXTRACT(EPOCH FROM
             timestamp '2026-07-20 10:00' - status_since) / 3600), 1)
         AS min_age_h,
       ROUND(MAX(EXTRACT(EPOCH FROM
             timestamp '2026-07-20 10:00' - status_since) / 3600), 1)
         AS max_age_h,
       MIN(claim_id) AS first_claim, MAX(claim_id) AS last_claim
FROM ins_claims
WHERE status = 'AWAITING_WORKSHOP_SLOT'
  AND status_since < timestamp '2026-07-20 06:00'
GROUP BY assigned_partner_id;
```

RN-3 share and severity mix of the stalled cohort:

```sql
SELECT COUNT(*) AS cohort,
       COUNT(*) FILTER (WHERE p.repair_network_clause) AS rn3,
       ROUND(100.0 * COUNT(*) FILTER (WHERE p.repair_network_clause)
             / COUNT(*), 1) AS rn3_pct,
       COUNT(*) FILTER (WHERE c.severity = 'SEVERE') AS severe,
       COUNT(*) FILTER (WHERE cu.complaint_flag) AS complaints
FROM ins_claims c
JOIN ins_policies p ON p.policy_id = c.policy_id
JOIN ins_customers cu ON cu.customer_id = p.customer_id
WHERE c.status = 'AWAITING_WORKSHOP_SLOT'
  AND c.status_since < timestamp '2026-07-20 06:00';
```

Partner load vs capacity (drive-ins) and partner status:

```sql
SELECT p.partner_id, p.name, p.contract_status,
       p.contract_status_since, p.contract_note,
       p.daily_scan_capacity,
       COUNT(c.claim_id) AS awaiting_slot,
       ROUND(COUNT(c.claim_id)::numeric
             / NULLIF(p.daily_scan_capacity, 0), 1) AS backlog_days
FROM ins_repair_partners p
LEFT JOIN ins_claims c
       ON c.assigned_partner_id = p.partner_id
      AND c.status = 'AWAITING_WORKSHOP_SLOT'
WHERE p.partner_type = 'DRIVE_IN'
GROUP BY p.partner_id, p.name, p.contract_status,
         p.contract_status_since, p.contract_note,
         p.daily_scan_capacity
ORDER BY awaiting_slot DESC;
```

Exposure without garage by district (plus property policies):

```sql
SELECT district,
       COUNT(*) FILTER (WHERE product <> 'PROPERTY') AS motor_policies,
       COUNT(*) FILTER (WHERE product <> 'PROPERTY'
                          AND garage_parking = false) AS motor_no_garage,
       COUNT(*) FILTER (WHERE product = 'PROPERTY') AS property_policies
FROM ins_policies
WHERE status = 'ACTIVE'
GROUP BY district
ORDER BY district;
```

Capacity and rental cars in Landkreis Ludwigsburg (storm readiness):

```sql
SELECT partner_id, name, partner_type, contract_status,
       daily_scan_capacity, rental_cars_available
FROM ins_repair_partners
WHERE city = 'Ludwigsburg'
ORDER BY partner_type, partner_id;
```

W-0471 (P-KAROSSERIE-SCHNELL) estimates vs contracted rates, with
identical line-item texts:

```sql
SELECT e.claim_id, e.hours, e.hourly_rate_eur, e.paint_rate_eur,
       e.total_eur,
       ROUND(100 * (e.hourly_rate_eur / p.contracted_hourly_rate_eur
                    - 1), 1) AS hourly_dev_pct,
       COUNT(*) OVER (PARTITION BY e.line_item_text) AS same_text_count
FROM ins_workshop_estimates e
JOIN ins_repair_partners p ON p.partner_id = e.partner_id
WHERE e.partner_id = 'P-KAROSSERIE-SCHNELL'
  AND (e.hourly_rate_eur > p.contracted_hourly_rate_eur
       OR e.paint_rate_eur > p.contracted_paint_rate_eur)
ORDER BY e.claim_id;
```

Payment-run items PR-2026-30 for a list of claim ids (the hold list):

```sql
SELECT payment_item_id, claim_id, payee_type, payee_partner_id,
       amount_eur, scheduled_for
FROM ins_payment_items
WHERE payment_run_id = 'PR-2026-30'
  AND claim_id IN ('CLM-0913-08301', 'CLM-0913-08302',
                   'CLM-0913-08303', 'CLM-0913-08401')
ORDER BY claim_id;
```

Payment-run totals and the amount at risk for id ranges:

```sql
SELECT COUNT(*) AS items, ROUND(SUM(amount_eur), 2) AS total_eur,
       COUNT(*) FILTER (WHERE claim_id BETWEEN 'CLM-0913-08101'
                                           AND 'CLM-0913-08119'
                           OR claim_id BETWEEN 'CLM-0913-08301'
                                           AND 'CLM-0913-08311'
                           OR claim_id BETWEEN 'CLM-0913-08401'
                                           AND 'CLM-0913-08417')
         AS flagged_items,
       ROUND(SUM(amount_eur) FILTER (
             WHERE claim_id BETWEEN 'CLM-0913-08101'
                                AND 'CLM-0913-08119'
                OR claim_id BETWEEN 'CLM-0913-08301'
                                AND 'CLM-0913-08311'
                OR claim_id BETWEEN 'CLM-0913-08401'
                                AND 'CLM-0913-08417'), 2)
         AS flagged_eur
FROM ins_payment_items
WHERE payment_run_id = 'PR-2026-30';
```

Policies and VINs behind duplicate reports (pattern B, primary vs
duplicate claim on the same policy):

```sql
SELECT a.claim_id AS primary_claim, a.fnol_channel AS primary_channel,
       b.claim_id AS duplicate_claim, b.fnol_channel AS dup_channel,
       p.policy_id, p.vehicle_vin,
       a.reported_at AS primary_reported, b.reported_at AS dup_reported
FROM ins_claims a
JOIN ins_claims b ON b.policy_id = a.policy_id
                 AND b.claim_id > a.claim_id
JOIN ins_policies p ON p.policy_id = a.policy_id
WHERE a.line = 'MOTOR'
ORDER BY a.claim_id;
```

Fast Lane check for one claim (claim + policy in one small query):

```sql
SELECT c.claim_id, c.severity, c.status, c.estimate_eur,
       p.policy_id, p.status AS policy_status, p.hail_cover,
       p.deductible_eur, p.repair_network_clause, p.district, p.city
FROM ins_claims c
JOIN ins_policies p ON p.policy_id = c.policy_id
WHERE c.claim_id = 'CLM-0913-00001';
```

Nearest active drive-in for a slot proposal (same district):

```sql
SELECT partner_id, name, city, daily_scan_capacity
FROM ins_repair_partners
WHERE partner_type = 'DRIVE_IN' AND contract_status = 'ACTIVE'
  AND city IN ('Sindelfingen', 'Boeblingen')
ORDER BY daily_scan_capacity DESC
LIMIT 1;
```
