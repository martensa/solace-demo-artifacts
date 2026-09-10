-- acme_insurance: claims operations data for Acme Insurance (P&C,
-- motor + property). ONE database, six tables: customers, policies,
-- claims, repair partners, workshop estimates, payment items.
-- Bulk rows are generated INSIDE postgres (generate_series + md5
-- hashing, no random()), then explicit anchors pin the storyline.
-- Idempotent: drop + recreate.
--
-- Storyline anchors (hail cell HZ-0913, Sat 2026-07-18 18:40,
-- Landkreis Boeblingen; snapshot = Mon 2026-07-20 10:00):
--   10,400 claims = 9,650 MOTOR + 750 PROPERTY
--   channels APP 4,160 / VOICE_AGENT 2,600 / WORKSHOP_PORTAL 1,560 /
--            DRIVE_IN_SCANNER 1,040 / AGENCY_EMAIL 1,040
--   severity MINOR 6,200 / MODERATE 3,600 / SEVERE 600
--   status   CONFIRMED 5,900 / AWAITING_WORKSHOP_SLOT 2,140 /
--            IN_REPAIR 1,530 / TOTAL_LOSS_FASTLANE 210 / RECEIVED 620
--            (ON_HOLD is a valid value with 0 rows at snapshot time)
--   stalled cohort CLM-0913-06001..06412 at P-BRAENDLE since Sun
--     09:00..12:00 (> 22 h); 293 of their policies carry RN-3
--   P-BRAENDLE: 640 assignments in AWAITING_WORKSHOP_SLOT
--     (412 cohort + 228 fresh ones since Mon 06:30..09:50)
--   fraud act: CLM-0913-08103 scanner mismatch (estimate 6,800);
--     pattern A 08101..08119, B 08201..08211 = 08301..08311 (same
--     policy/VIN), C 08401..08417 at W-0471 (+38 % rates, 9 identical
--     line texts); PR-2026-30 = 3,900 items, EUR 14,200,000.00
--   exposure: BOEBLINGEN 31,600 motor (15,800 no garage),
--     LUDWIGSBURG 17,400 motor (8,900 no garage) + 2,300 property
--   Fast Lane sample: CLM-0913-00001..00008 pinned to POL-104211 ..
--     (the cockpit's 8 MINOR FNOL events; cross-store contract with
--     the MongoDB intake seed -- section 6)
--
-- CLAIM-ID LAYOUT (c = numeric suffix of CLM-0913-xxxxx). Every
-- count above is exact BY CONSTRUCTION of these ranges. Other
-- builders (MongoDB fnol_intake / scanner_results) align on them.
--
--   c range        line      severity  status                  partner
--   00001..00100   MOTOR     MINOR     RECEIVED                -
--                  (00001..00040 = Fast Lane clerk samples, est 180..950;
--                   00001..00008 = cockpit FNOL sample anchor: pinned
--                   policy, channel, estimate, reported_at -- section 6)
--   00101..04500   MOTOR     MINOR     CONFIRMED               -
--   04501..04727   MOTOR     MINOR     AWAITING_WORKSHOP_SLOT  P-BRAENDLE
--                  (fresh, status_since Mon 06:30..09:50)
--   04728..05400   MOTOR     MINOR     AWAITING_WORKSHOP_SLOT  body shops
--   05401..05750   MOTOR     MINOR     IN_REPAIR               body shops
--   05751..06000   MOTOR     MODERATE  AWAITING_WORKSHOP_SLOT  body shops
--                  (05751..05910 already have a workshop estimate)
--   06001..06158   MOTOR     SEVERE    AWAITING_WORKSHOP_SLOT  P-BRAENDLE
--                  (cohort part 1: total-loss signature in MongoDB)
--   06159..06412   MOTOR     MODERATE  AWAITING_WORKSHOP_SLOT  P-BRAENDLE
--                  (cohort part 2)
--   06413..06454   MOTOR     SEVERE    AWAITING_WORKSHOP_SLOT  body shops
--   06455..06989   MOTOR     MODERATE  AWAITING_WORKSHOP_SLOT  body shops
--   06990..07982   MOTOR     MODERATE  IN_REPAIR               body shops
--   07983..08890   MOTOR     MODERATE  CONFIRMED               -
--                  except 08103 AWAITING_WORKSHOP_SLOT at P-BRAENDLE
--                  and 08401..08417 IN_REPAIR at P-KAROSSERIE-SCHNELL
--   08891..09290   MOTOR     MODERATE  RECEIVED                -
--   09291..09500   MOTOR     SEVERE    TOTAL_LOSS_FASTLANE     P-ROADASSIST
--   09501..09580   MOTOR     SEVERE    IN_REPAIR               body shops
--   09581..09620   MOTOR     SEVERE    RECEIVED                -
--   09621..09650   MOTOR     SEVERE    CONFIRMED               -
--   09651..10050   PROPERTY  MINOR     CONFIRMED               -
--   10051..10100   PROPERTY  MINOR     RECEIVED                -
--   10101..10270   PROPERTY  MODERATE  CONFIRMED               -
--   10271..10340   PROPERTY  MODERATE  IN_REPAIR               -
--   10341..10360   PROPERTY  MODERATE  RECEIVED                -
--   10361..10370   PROPERTY  SEVERE    CONFIRMED               -
--   10371..10390   PROPERTY  SEVERE    IN_REPAIR               -
--   10391..10400   PROPERTY  SEVERE    RECEIVED                -
--   "body shops" = P-AUTOWERK-BB / P-LACKPROFI-LEO /
--   P-KAROSSERIE-SCHNELL by c mod 3 (0 / 1 / 2).
--   Per line (same split as the MongoDB intake seed): motor MINOR
--   5,750 / MODERATE 3,340 / SEVERE 560; property 450 / 260 / 40.
--
-- CHANNEL RULE (exact totals, scattered over the ranges above; per
-- line: motor APP 3,860 / VOICE_AGENT 2,350 / WORKSHOP_PORTAL 1,560 /
-- DRIVE_IN_SCANNER 1,040 / AGENCY_EMAIL 840, property APP 300 /
-- VOICE_AGENT 250 / AGENCY_EMAIL 200 -- same as the MongoDB seed):
--   forced: 08101..08119 APP (08103 DRIVE_IN_SCANNER), 08201..08211
--           APP, 08301..08311 VOICE_AGENT, 08401..08417 WORKSHOP_PORTAL
--   night pool (Fast Lane sample 00001..00040 + cohort 06001..06412:
--           no drive-in / workshop intake): j = c (c <= 40) or
--           c - 5960 (cohort); m = (j * 2731) mod 452; m < 200 APP,
--           m < 360 VOICE_AGENT, else AGENCY_EMAIL -- except the
--           anchor 00001..00008 (pinned: APP 4 / VOICE_AGENT 2 /
--           AGENCY_EMAIL 2, section 6) and 00011, 00012, 00019,
--           00020 forced APP (the formula gives the anchor ids 8 APP
--           and 00011/00012 VOICE_AGENT, 00019/00020 AGENCY_EMAIL, so
--           these four flips keep the pool at 200 / 160 / 92)
--   property (c > 9650): m = ((c - 9650) * 7) mod 750;
--           m < 300 APP, m < 550 VOICE_AGENT, else AGENCY_EMAIL
--   other motor: n = c minus the number of forced + night-pool ids
--           below c (40 up to c 6000; 452 from 6413; 471 from 8120;
--           482 from 8212; 493 from 8312; 510 from 8418);
--           m = (n * 2731) mod 9140; m < 3631 APP, < 5810
--           VOICE_AGENT, < 7353 WORKSHOP_PORTAL, < 8392
--           DRIVE_IN_SCANNER, else AGENCY_EMAIL
--   example: c = 9 -> j = 9 -> m = 171 -> APP; c = 41 -> n = 1 ->
--           m = 2731 -> APP; c = 43 -> n = 3 -> m = 8193 ->
--           DRIVE_IN_SCANNER
--
-- POLICY LAYOUT (p = numeric suffix of POL-xxxxxx, 1..68,700):
--   1..15800 BOEBLINGEN motor no garage | 15801..31600 BB motor
--   garage | 31601..33500 BB property | 33501..42400 LUDWIGSBURG
--   motor no garage | 42401..50900 LB motor garage | 50901..53200 LB
--   property | 53201..62200 STUTTGART motor | 62201..63200 STR
--   property | 63201..68200 ESSLINGEN motor | 68201..68700 ES
--   property. STR/ES garage_parking = (p even). Holder of policy p
--   is customer p, except p mod 4 = 0 -> customer p - 1 (a second
--   policy) -> 51,525 customers.
--   policy of motor claim c = POL-(((c * 7919) mod 15800) + 1), a
--   BOEBLINGEN no-garage policy; duplicates 08301..08311 reuse the
--   policy (and VIN) of 08201..08211; property claim c ->
--   POL-(31600 + (((c - 9651) * 7919) mod 1900) + 1).
--   Fast Lane anchor (section 6): the bulk policies this formula
--   yields for c = 1..8 (POL-007920, -000039, -007958, -000077,
--   -007996, -000115, -008034, -000153) are re-keyed to POL-104211,
--   -118902, -121377, -109654, -133018, -115486, -127730, -112245 and
--   get the anchor attributes; row counts and exposure are unchanged.
--
-- TIMESTAMPS: reported_at Sat 2026-07-18 18:45 .. Mon 2026-07-20
-- 09:55; status_since >= reported_at and <= Mon 09:55. RECEIVED
-- claims are reported Mon 08:00..09:55, except the anchor
-- 00001..00008 (pinned Sat 19:12 .. Mon 07:55, status_since =
-- reported_at).

DROP TABLE IF EXISTS ins_payment_items;
DROP TABLE IF EXISTS ins_workshop_estimates;
DROP TABLE IF EXISTS ins_claims;
DROP TABLE IF EXISTS ins_repair_partners;
DROP TABLE IF EXISTS ins_policies;
DROP TABLE IF EXISTS ins_customers;
DROP FUNCTION IF EXISTS ins_hash(text);
DROP TABLE IF EXISTS ins_fastlane_anchor;   -- session-local helper, section 6

-- Deterministic 28-bit hash for cosmetic variety (names, VINs,
-- minutes inside a window). Dropped again at the end of the file.
CREATE FUNCTION ins_hash(key text) RETURNS integer
LANGUAGE sql IMMUTABLE AS
$$ SELECT ('x' || substr(md5(key), 1, 7))::bit(28)::int $$;

CREATE TABLE ins_customers (
    customer_id        text PRIMARY KEY,   -- CUS-000001 ..
    full_name          text NOT NULL,
    city               text,
    postal_code        text,
    segment            text NOT NULL,      -- PRIVATE | FLEET
    preferred_channel  text,               -- same domain as fnol_channel
    complaint_flag     boolean NOT NULL
);

CREATE TABLE ins_policies (
    policy_id              text PRIMARY KEY,   -- POL-000001 ..
    customer_id            text NOT NULL,      -- joins ins_customers
    product                text NOT NULL,      -- MOTOR_COMPREHENSIVE | MOTOR_PARTIAL | PROPERTY
    vehicle_vin            text,               -- NULL for PROPERTY
    vehicle_model          text,               -- NULL for PROPERTY
    garage_parking         boolean,            -- NULL for PROPERTY
    postal_code            text,
    city                   text,
    district               text NOT NULL,      -- BOEBLINGEN | LUDWIGSBURG | STUTTGART | ESSLINGEN
    hail_cover             boolean NOT NULL,   -- clause HC-7
    deductible_eur         integer NOT NULL,
    repair_network_clause  boolean NOT NULL,   -- clause RN-3 (15 % discount, insurer steers)
    status                 text NOT NULL,      -- ACTIVE
    start_date             date
);

CREATE TABLE ins_claims (
    claim_id             text PRIMARY KEY,     -- CLM-0913-00001 .. CLM-0913-10400
    policy_id            text NOT NULL,        -- joins ins_policies
    event_id             text NOT NULL,        -- HZ-0913
    line                 text NOT NULL,        -- MOTOR | PROPERTY
    fnol_channel         text NOT NULL,        -- APP | VOICE_AGENT | WORKSHOP_PORTAL | DRIVE_IN_SCANNER | AGENCY_EMAIL
    reported_at          timestamp NOT NULL,
    severity             text NOT NULL,        -- MINOR | MODERATE | SEVERE
    status               text NOT NULL,        -- RECEIVED | CONFIRMED | AWAITING_WORKSHOP_SLOT | IN_REPAIR | TOTAL_LOSS_FASTLANE | ON_HOLD
    status_since         timestamp NOT NULL,
    assigned_partner_id  text,                 -- joins ins_repair_partners, NULL if none
    estimate_eur         integer,              -- NULL while no estimate exists
    reserve_eur          integer NOT NULL,
    drivable             boolean               -- NULL for PROPERTY
);

CREATE TABLE ins_repair_partners (
    partner_id                  text PRIMARY KEY,
    name                        text NOT NULL,
    city                        text,
    postal_code                 text,
    partner_type                text NOT NULL,   -- DRIVE_IN | BODY_SHOP | ASSISTANCE | RENTAL
    contract_status             text NOT NULL,   -- ACTIVE | INACTIVE
    contract_status_since       date,
    contract_note               text,
    tier                        text,            -- PREMIUM | STANDARD
    daily_scan_capacity         integer,         -- DRIVE_IN only
    contracted_hourly_rate_eur  numeric,         -- 118.00 for repairers
    contracted_paint_rate_eur   numeric,         -- 96.00 for repairers
    rental_cars_available       integer          -- RENTAL only
);

CREATE TABLE ins_workshop_estimates (
    estimate_id      text PRIMARY KEY,   -- EST-<claim suffix>
    claim_id         text NOT NULL,      -- joins ins_claims (one estimate per claim)
    partner_id       text NOT NULL,      -- joins ins_repair_partners
    hours            numeric NOT NULL,
    hourly_rate_eur  numeric NOT NULL,
    paint_rate_eur   numeric NOT NULL,
    total_eur        numeric NOT NULL,   -- = hours * (hourly_rate_eur + paint_rate_eur)
    line_item_text   text,
    submitted_at     timestamp
);

CREATE TABLE ins_payment_items (
    payment_item_id   text PRIMARY KEY,   -- PI-30-00001 ..
    payment_run_id    text NOT NULL,      -- PR-2026-30
    claim_id          text NOT NULL,      -- joins ins_claims
    payee_type        text NOT NULL,      -- CUSTOMER | WORKSHOP
    payee_partner_id  text,               -- WORKSHOP items only
    iban_hash         text,
    amount_eur        numeric NOT NULL,
    status            text NOT NULL,      -- SCHEDULED
    scheduled_for     timestamp NOT NULL  -- 2026-07-24 16:00
);

-- -------------------------------------------------------------
-- 1. Policies (68,700) -- exposure by construction, see header.
-- -------------------------------------------------------------
INSERT INTO ins_policies
WITH geo (district, idx, postal_code, city) AS (VALUES
  ('BOEBLINGEN',  0, '71032', 'Boeblingen'),
  ('BOEBLINGEN',  1, '71034', 'Boeblingen'),
  ('BOEBLINGEN',  2, '71063', 'Sindelfingen'),
  ('BOEBLINGEN',  3, '71065', 'Sindelfingen'),
  ('BOEBLINGEN',  4, '71067', 'Sindelfingen'),
  ('BOEBLINGEN',  5, '71069', 'Sindelfingen'),
  ('BOEBLINGEN',  6, '71083', 'Herrenberg'),
  ('BOEBLINGEN',  7, '71093', 'Weil der Stadt'),
  ('BOEBLINGEN',  8, '71101', 'Schoenaich'),
  ('BOEBLINGEN',  9, '71229', 'Leonberg'),
  ('BOEBLINGEN', 10, '71263', 'Weil der Stadt'),
  ('BOEBLINGEN', 11, '71272', 'Leonberg'),
  ('BOEBLINGEN', 12, '71277', 'Leonberg'),
  ('BOEBLINGEN', 13, '71287', 'Weil der Stadt'),
  ('BOEBLINGEN', 14, '71296', 'Holzgerlingen'),
  ('BOEBLINGEN', 15, '71297', 'Gaertringen'),
  ('LUDWIGSBURG', 0, '71634', 'Ludwigsburg'),
  ('LUDWIGSBURG', 1, '71636', 'Ludwigsburg'),
  ('LUDWIGSBURG', 2, '71638', 'Ludwigsburg'),
  ('LUDWIGSBURG', 3, '71640', 'Ludwigsburg'),
  ('LUDWIGSBURG', 4, '71642', 'Ludwigsburg'),
  ('LUDWIGSBURG', 5, '71672', 'Marbach'),
  ('LUDWIGSBURG', 6, '71679', 'Asperg'),
  ('LUDWIGSBURG', 7, '71686', 'Remseck'),
  ('LUDWIGSBURG', 8, '71691', 'Freiberg'),
  ('LUDWIGSBURG', 9, '71701', 'Ditzingen'),
  ('LUDWIGSBURG', 10, '71706', 'Kornwestheim'),
  ('LUDWIGSBURG', 11, '71711', 'Marbach'),
  ('LUDWIGSBURG', 12, '71723', 'Marbach'),
  ('LUDWIGSBURG', 13, '71726', 'Freiberg'),
  ('LUDWIGSBURG', 14, '71729', 'Remseck'),
  ('LUDWIGSBURG', 15, '71732', 'Bietigheim-Bissingen'),
  ('STUTTGART',   0, '70173', 'Stuttgart'),
  ('STUTTGART',   1, '70174', 'Stuttgart'),
  ('STUTTGART',   2, '70176', 'Stuttgart'),
  ('STUTTGART',   3, '70178', 'Stuttgart'),
  ('STUTTGART',   4, '70180', 'Stuttgart'),
  ('STUTTGART',   5, '70182', 'Stuttgart'),
  ('STUTTGART',   6, '70184', 'Stuttgart'),
  ('STUTTGART',   7, '70186', 'Stuttgart'),
  ('ESSLINGEN',   0, '73728', 'Esslingen'),
  ('ESSLINGEN',   1, '73730', 'Esslingen'),
  ('ESSLINGEN',   2, '73732', 'Esslingen'),
  ('ESSLINGEN',   3, '73733', 'Esslingen'),
  ('ESSLINGEN',   4, '73734', 'Esslingen')
), base AS (
  SELECT p,
    CASE WHEN p <= 33500 THEN 'BOEBLINGEN'
         WHEN p <= 53200 THEN 'LUDWIGSBURG'
         WHEN p <= 63200 THEN 'STUTTGART'
         ELSE 'ESSLINGEN' END AS district,
    (p BETWEEN 31601 AND 33500 OR p BETWEEN 50901 AND 53200
     OR p BETWEEN 62201 AND 63200 OR p > 68200) AS is_property,
    CASE WHEN p <= 15800 OR p BETWEEN 33501 AND 42400 THEN false
         WHEN p <= 31600 OR p BETWEEN 42401 AND 50900 THEN true
         ELSE (p % 2 = 0) END AS garage,
    ins_hash('pol' || p) AS h
  FROM generate_series(1, 68700) AS p
)
SELECT 'POL-' || lpad(p::text, 6, '0'),
       'CUS-' || lpad((p - CASE WHEN p % 4 = 0 THEN 1 ELSE 0 END)::text, 6, '0'),
       CASE WHEN is_property THEN 'PROPERTY'
            WHEN p % 3 = 0 THEN 'MOTOR_PARTIAL'
            ELSE 'MOTOR_COMPREHENSIVE' END,
       CASE WHEN is_property THEN NULL
            ELSE 'WAC' || upper(substr(md5('vin' || p), 1, 14)) END,
       CASE WHEN is_property THEN NULL ELSE
         (ARRAY['VW Golf VIII', 'VW Tiguan', 'VW ID.4', 'Mercedes A-Class',
                'Mercedes C-Class', 'Mercedes GLC', 'BMW 3 Series', 'BMW X1',
                'Audi A4', 'Audi Q3', 'Porsche Macan', 'Opel Astra',
                'Ford Focus', 'Skoda Octavia', 'Seat Leon', 'Toyota Yaris',
                'Hyundai i30', 'Tesla Model 3', 'Renault Clio', 'Fiat 500'])
           [1 + h % 20] END,
       CASE WHEN is_property THEN NULL ELSE garage END,
       g.postal_code, g.city, b.district,
       -- HC-7: 10 % of garage-parked motor and 10 % of property lack it
       NOT ((garage OR is_property) AND p % 10 = 0),
       CASE WHEN is_property THEN 500 + (p % 2) * 500
            WHEN p % 3 = 0 THEN 150
            ELSE 300 + (p % 2) * 200 END,
       -- RN-3 baseline 55 % of motor policies; cohort pinned below
       (NOT is_property AND p % 20 < 11),
       'ACTIVE',
       date '2019-01-01' + (h % 2700)
FROM base b
JOIN geo g ON g.district = b.district
 -- a holder's second policy (p mod 4 = 0) shares the holder's address
 AND g.idx = (p - CASE WHEN p % 4 = 0 THEN 1 ELSE 0 END)
             % CASE b.district WHEN 'STUTTGART' THEN 8
                               WHEN 'ESSLINGEN' THEN 5 ELSE 16 END;

-- -------------------------------------------------------------
-- 2. Customers (51,525) -- one per policy holder, same address
--    as the holder's first policy. Names from two word lists.
-- -------------------------------------------------------------
INSERT INTO ins_customers
SELECT pol.customer_id,
       CASE WHEN p % 25 = 0 THEN
              (ARRAY['Logistik', 'Pflegedienst', 'Bauservice', 'Taxi',
                     'Kurierdienst', 'Gebaeudeservice'])[1 + h % 6]
              || ' ' || ln || ' GmbH'
            ELSE fn || ' ' || ln END,
       pol.city, pol.postal_code,
       CASE WHEN p % 25 = 0 THEN 'FLEET' ELSE 'PRIVATE' END,
       (ARRAY['APP', 'VOICE_AGENT', 'WORKSHOP_PORTAL', 'DRIVE_IN_SCANNER',
              'AGENCY_EMAIL'])[1 + (h / 7) % 5],
       false
FROM (
  SELECT p, ins_hash('cus' || p) AS h,
    (ARRAY['Anna', 'Ben', 'Clara', 'David', 'Elena', 'Felix', 'Greta',
           'Hannes', 'Ida', 'Jonas', 'Katja', 'Lukas', 'Marie', 'Nils',
           'Olivia', 'Paul', 'Rosa', 'Simon', 'Theresa', 'Ulrich', 'Vera',
           'Wolfgang', 'Yasmin', 'Zoe', 'Amir', 'Birgit', 'Cem', 'Dilara',
           'Emil', 'Frieda', 'Georg', 'Helga', 'Ines', 'Jakob', 'Karin',
           'Leon', 'Mira', 'Noah', 'Oskar', 'Pia'])
      [1 + ins_hash('fn' || p) % 40] AS fn,
    (ARRAY['Mueller', 'Schmidt', 'Schneider', 'Fischer', 'Weber', 'Meyer',
           'Wagner', 'Becker', 'Schulz', 'Hoffmann', 'Koch', 'Richter',
           'Klein', 'Wolf', 'Schroeder', 'Neumann', 'Schwarz', 'Zimmermann',
           'Braun', 'Krueger', 'Hofmann', 'Hartmann', 'Lange', 'Schmitt',
           'Werner', 'Krause', 'Meier', 'Lehmann', 'Huber', 'Kaiser',
           'Fuchs', 'Peters', 'Lang', 'Scholz', 'Moeller', 'Weiss', 'Jung',
           'Hahn', 'Schubert', 'Vogel', 'Friedrich', 'Keller', 'Guenther',
           'Frank', 'Berger', 'Winkler', 'Roth', 'Beck'])
      [1 + ins_hash('ln' || p) % 48] AS ln
  FROM generate_series(1, 68700) AS p
  WHERE p % 4 <> 0
) n
JOIN ins_policies pol ON pol.policy_id = 'POL-' || lpad(p::text, 6, '0');

-- -------------------------------------------------------------
-- 3. Repair network -- exactly the 10 partners of the storyline.
-- -------------------------------------------------------------
INSERT INTO ins_repair_partners VALUES
('P-BRAENDLE',           'Braendle Drive-In Hail Center',        'Sindelfingen', '71063', 'DRIVE_IN',   'ACTIVE',   '2025-01-01', 'contract PC-BRAENDLE-2025; second-shift option +60 scans/day on 24 h notice; overflow clause',          'PREMIUM',  120,  118.00, 96.00, NULL),
('P-DELLENDOC',          'Dellen-Doktor Sindelfingen',           'Sindelfingen', '71065', 'DRIVE_IN',   'INACTIVE', '2026-01-01', 'tier renegotiation — parts-channel clause PC-4 unsigned',                                            'STANDARD',  90,  118.00, 96.00, NULL),
('P-KAROSSERIE-SCHNELL', 'Karosserie Schnell GmbH',              'Boeblingen',   '71032', 'BODY_SHOP',  'ACTIVE',   '2025-03-01', 'workshop code W-0471; body shop at PC-RATES-2026 contracted rates (hourly 118 / paint 96)',           'STANDARD', NULL, 118.00, 96.00, NULL),
('P-AUTOWERK-BB',        'Autowerk Boeblingen',                  'Boeblingen',   '71034', 'BODY_SHOP',  'ACTIVE',   '2024-06-01', 'body shop at PC-RATES-2026 contracted rates',                                                         'STANDARD', NULL, 118.00, 96.00, NULL),
('P-LACKPROFI-LEO',      'Lackprofi Leonberg',                   'Leonberg',     '71229', 'BODY_SHOP',  'ACTIVE',   '2024-09-01', 'body shop at PC-RATES-2026 contracted rates; paint specialist',                                       'PREMIUM',  NULL, 118.00, 96.00, NULL),
('P-ROADASSIST',         'RoadAssist Pick-up and Remote Valuation', 'Stuttgart', '70173', 'ASSISTANCE', 'ACTIVE',   '2025-01-01', 'contract PC-ROADASSIST-2025: pick-up + remote valuation for total losses, 200 vehicles/day',           'PREMIUM',  NULL, NULL,   NULL,  NULL),
('P-HAGELPOINT-LB',      'Hagelpoint Ludwigsburg',               'Ludwigsburg',  '71634', 'DRIVE_IN',   'ACTIVE',   '2025-05-01', 'drive-in hail center, Landkreis Ludwigsburg',                                                         'STANDARD', 100,  118.00, 96.00, NULL),
('P-DELLENFIX-LB',       'Dellenfix Ludwigsburg',                'Ludwigsburg',  '71638', 'DRIVE_IN',   'ACTIVE',   '2025-05-01', 'drive-in hail center, Landkreis Ludwigsburg',                                                         'STANDARD',  80,  118.00, 96.00, NULL),
('P-RENTAFLEET',         'RentaFleet Ludwigsburg',               'Ludwigsburg',  '71636', 'RENTAL',     'ACTIVE',   '2026-01-01', 'contract PC-RENTAFLEET-2026: rental pre-booking on 24 h notice, up to 150 cars',                       'STANDARD', NULL, NULL,   NULL,  35);

-- -------------------------------------------------------------
-- 4. Claims (10,400) -- category by claim-id range (see header).
-- -------------------------------------------------------------
INSERT INTO ins_claims
WITH lay AS (
  SELECT c,
    CASE WHEN c <= 9650 THEN 'MOTOR' ELSE 'PROPERTY' END AS line,
    CASE WHEN c <= 5750 THEN 'MINOR'
         WHEN c BETWEEN 6001 AND 6158 OR c BETWEEN 6413 AND 6454
           OR c BETWEEN 9291 AND 9650 THEN 'SEVERE'
         WHEN c <= 9290 THEN 'MODERATE'
         WHEN c <= 10100 THEN 'MINOR'
         WHEN c <= 10360 THEN 'MODERATE'
         ELSE 'SEVERE' END AS severity,
    CASE WHEN c <= 100 THEN 'RECEIVED'
         WHEN c <= 4500 THEN 'CONFIRMED'
         WHEN c <= 5400 THEN 'AWAITING_WORKSHOP_SLOT'
         WHEN c <= 5750 THEN 'IN_REPAIR'
         WHEN c <= 6989 THEN 'AWAITING_WORKSHOP_SLOT'
         WHEN c <= 7982 THEN 'IN_REPAIR'
         WHEN c = 8103 THEN 'AWAITING_WORKSHOP_SLOT'
         WHEN c BETWEEN 8401 AND 8417 THEN 'IN_REPAIR'
         WHEN c <= 8890 THEN 'CONFIRMED'
         WHEN c <= 9290 THEN 'RECEIVED'
         WHEN c <= 9500 THEN 'TOTAL_LOSS_FASTLANE'
         WHEN c <= 9580 THEN 'IN_REPAIR'
         WHEN c <= 9620 THEN 'RECEIVED'
         WHEN c <= 9650 THEN 'CONFIRMED'
         WHEN c <= 10050 THEN 'CONFIRMED'
         WHEN c <= 10100 THEN 'RECEIVED'
         WHEN c <= 10270 THEN 'CONFIRMED'
         WHEN c <= 10340 THEN 'IN_REPAIR'
         WHEN c <= 10360 THEN 'RECEIVED'
         WHEN c <= 10370 THEN 'CONFIRMED'
         WHEN c <= 10390 THEN 'IN_REPAIR'
         ELSE 'RECEIVED' END AS status,
    (c BETWEEN 6001 AND 6412) AS is_cohort,
    (c BETWEEN 4501 AND 4727 OR c = 8103) AS is_braendle_fresh,
    -- channel scatter index: night pool (sample + cohort) ...
    ((CASE WHEN c <= 40 THEN c ELSE c - 5960 END) * 2731) % 452 AS m_night,
    -- ... and the other non-forced motor claims
    ((c - CASE WHEN c >= 8418 THEN 510 WHEN c >= 8312 THEN 493
               WHEN c >= 8212 THEN 482 WHEN c >= 8120 THEN 471
               WHEN c >= 6413 THEN 452 ELSE 40 END) * 2731) % 9140 AS m,
    ins_hash('rep' || c) AS h1,
    ins_hash('since' || c) AS h2,
    ins_hash('est' || c) AS h3
  FROM generate_series(1, 10400) AS c
), cat AS (
  SELECT lay.*,
    CASE WHEN status = 'AWAITING_WORKSHOP_SLOT'
              AND (is_cohort OR is_braendle_fresh) THEN 'P-BRAENDLE'
         WHEN c BETWEEN 8401 AND 8417 THEN 'P-KAROSSERIE-SCHNELL'
         WHEN status = 'TOTAL_LOSS_FASTLANE' THEN 'P-ROADASSIST'
         WHEN line = 'MOTOR'
              AND status IN ('AWAITING_WORKSHOP_SLOT', 'IN_REPAIR') THEN
           (ARRAY['P-AUTOWERK-BB', 'P-LACKPROFI-LEO',
                  'P-KAROSSERIE-SCHNELL'])[1 + c % 3]
         ELSE NULL END AS partner,
    CASE WHEN c = 8103 THEN 'DRIVE_IN_SCANNER'
         WHEN c BETWEEN 8101 AND 8119 OR c BETWEEN 8201 AND 8211 THEN 'APP'
         WHEN c BETWEEN 8301 AND 8311 THEN 'VOICE_AGENT'
         WHEN c BETWEEN 8401 AND 8417 THEN 'WORKSHOP_PORTAL'
         -- Fast Lane anchor compensation: 00001..00008 are pinned in
         -- section 6 (4 APP / 2 VOICE_AGENT / 2 AGENCY_EMAIL); these
         -- four night-pool flips keep every channel total exact
         WHEN c IN (11, 12, 19, 20) THEN 'APP'
         WHEN c <= 40 OR is_cohort THEN
           CASE WHEN m_night < 200 THEN 'APP'
                WHEN m_night < 360 THEN 'VOICE_AGENT'
                ELSE 'AGENCY_EMAIL' END
         WHEN line = 'PROPERTY' THEN
           CASE WHEN ((c - 9650) * 7) % 750 < 300 THEN 'APP'
                WHEN ((c - 9650) * 7) % 750 < 550 THEN 'VOICE_AGENT'
                ELSE 'AGENCY_EMAIL' END
         WHEN m < 3631 THEN 'APP'
         WHEN m < 5810 THEN 'VOICE_AGENT'
         WHEN m < 7353 THEN 'WORKSHOP_PORTAL'
         WHEN m < 8392 THEN 'DRIVE_IN_SCANNER'
         ELSE 'AGENCY_EMAIL' END AS channel,
    -- timestamps, step 1: the independent side of each pair
    CASE WHEN status = 'RECEIVED' THEN
           timestamp '2026-07-20 08:00' + (h1 % 115) * interval '1 minute'
         WHEN is_cohort THEN
           timestamp '2026-07-18 18:50' + (h1 % 780) * interval '1 minute'
         ELSE timestamp '2026-07-18 18:45' + (h1 % 2280) * interval '1 minute'
    END AS rep0,
    CASE WHEN is_cohort THEN
           timestamp '2026-07-19 09:00' + (h2 % 180) * interval '1 minute'
         WHEN is_braendle_fresh THEN
           timestamp '2026-07-20 06:30' + (h2 % 200) * interval '1 minute'
         WHEN status = 'AWAITING_WORKSHOP_SLOT' THEN
           timestamp '2026-07-20 06:15' + (h2 % 220) * interval '1 minute'
    END AS since0
  FROM lay
), ts AS (
  SELECT cat.*,
    CASE WHEN status = 'AWAITING_WORKSHOP_SLOT' AND NOT is_cohort THEN
           since0 - (60 + h1 % 900) * interval '1 minute'
         ELSE rep0 END AS reported_at,
    CASE WHEN status = 'AWAITING_WORKSHOP_SLOT' THEN since0
         WHEN status = 'RECEIVED' THEN rep0
         WHEN status = 'CONFIRMED' THEN
           rep0 + (2 + h2 % 45) * interval '1 minute'
         ELSE LEAST(rep0 + (3 + h2 % 20) * interval '1 hour',
                    timestamp '2026-07-20 09:55') END AS status_since,
    CASE WHEN severity = 'MINOR' THEN 180 + h3 % 771
         WHEN status = 'RECEIVED' THEN NULL
         WHEN status = 'TOTAL_LOSS_FASTLANE' THEN 14000 + (h3 % 181) * 100
         WHEN severity = 'MODERATE' THEN 1200 + (h3 % 660) * 10
         ELSE 8500 + (h3 % 156) * 100 END AS estimate
  FROM cat
)
SELECT 'CLM-0913-' || lpad(c::text, 5, '0'),
       'POL-' || lpad((CASE
          WHEN line = 'PROPERTY' THEN 31600 + ((c - 9651) * 7919) % 1900 + 1
          WHEN c BETWEEN 8301 AND 8311 THEN ((c - 100) * 7919) % 15800 + 1
          ELSE (c * 7919) % 15800 + 1 END)::text, 6, '0'),
       'HZ-0913', line, channel, reported_at, severity, status,
       status_since, partner, estimate,
       COALESCE((ROUND(estimate * 1.15 / 50) * 50)::int,
                CASE severity WHEN 'MINOR' THEN 900
                              WHEN 'MODERATE' THEN 5000 ELSE 18000 END),
       CASE WHEN line = 'PROPERTY' THEN NULL
            WHEN severity = 'MINOR' THEN true
            WHEN severity = 'MODERATE' THEN (h3 % 10 <> 0)
            ELSE false END
FROM ts;

-- -------------------------------------------------------------
-- 5. Workshop estimates (1,600 = 1,440 motor IN_REPAIR + 160
--    AWAITING claims 05751..05910) at contracted rates; W-0471
--    anchors 08401..08417 at +38 % (162.84 / 132.48) and
--    08401..08409 sharing one line-item text.
-- -------------------------------------------------------------
INSERT INTO ins_workshop_estimates
SELECT 'EST-' || substr(claim_id, 10),
       claim_id, assigned_partner_id, hours, hourly, paint,
       ROUND(hours * (hourly + paint), 2),
       CASE WHEN c BETWEEN 8401 AND 8409 THEN
              'PDR roof + bonnet, 62 dents, blend A-pillars, polish complete'
            ELSE (ARRAY['PDR roof + bonnet, ', 'PDR roof, boot lid and rear wings, ',
                        'windscreen replacement, PDR bonnet, ',
                        'PDR complete body, blend A-pillars, ',
                        'PDR bonnet and both front wings, ',
                        'PDR roof, glass check, '])[1 + h % 6]
                 || dents || ' dents, ' || 2 + (h / 7) % 5 || ' panels, '
                 || hours || ' h, ' || vehicle_model
                 -- the claim ref keeps every bulk text unique:
                 -- ONLY the nine W-0471 anchors share a text
                 || ' (ref ' || substr(claim_id, 10) || ')' END,
       GREATEST(reported_at + interval '30 minutes',
                status_since - (1 + h % 6) * interval '1 hour')
FROM (
  SELECT cl.*, p.vehicle_model,
    substr(claim_id, 10)::int AS c, ins_hash('wse' || claim_id) AS h,
    CASE WHEN substr(claim_id, 10)::int BETWEEN 8401 AND 8417
           THEN 17 + ((substr(claim_id, 10)::int - 8401) % 19) * 0.5
         WHEN severity = 'MINOR'    THEN 3 + (ins_hash('hrs' || claim_id) % 4) * 0.5
         WHEN severity = 'MODERATE' THEN 6 + (ins_hash('hrs' || claim_id) % 61) * 0.5
         ELSE 38 + (ins_hash('hrs' || claim_id) % 65) * 0.5 END AS hours,
    CASE WHEN substr(claim_id, 10)::int BETWEEN 8401 AND 8417
           THEN 162.84 ELSE 118.00 END AS hourly,
    CASE WHEN substr(claim_id, 10)::int BETWEEN 8401 AND 8417
           THEN 132.48 ELSE 96.00 END AS paint,
    CASE WHEN severity = 'MINOR' THEN 4 + ins_hash('dnt' || claim_id) % 25
         WHEN severity = 'MODERATE' THEN 30 + ins_hash('dnt' || claim_id) % 91
         ELSE 120 + ins_hash('dnt' || claim_id) % 81 END AS dents
  FROM ins_claims cl
  JOIN ins_policies p ON p.policy_id = cl.policy_id
  WHERE (cl.line = 'MOTOR' AND cl.status = 'IN_REPAIR')
     OR substr(cl.claim_id, 10)::int BETWEEN 5751 AND 5910
) e;

-- claim estimate = workshop estimate where one exists
UPDATE ins_claims cl
SET estimate_eur = ROUND(e.total_eur)::int,
    reserve_eur  = (ROUND(e.total_eur * 1.15 / 50) * 50)::int
FROM ins_workshop_estimates e
WHERE e.claim_id = cl.claim_id;

-- -------------------------------------------------------------
-- 6. Story anchors.
-- -------------------------------------------------------------
-- Fast Lane sample anchor -- cross-store contract with the MongoDB
-- intake seed and the cockpit's 8 MINOR FNOL events. The bulk
-- policy the claim formula yields for c = 1..8 is RE-KEYED to the
-- pinned policy id and gets the anchor attributes (68,700 / 31,600 /
-- 15,800 stay exact by construction); its holder gets the anchor
-- name and address (the holder's sibling policy, if any, follows
-- the address); the claim gets the pinned channel, estimate and
-- reported_at (status_since = reported_at, still RECEIVED). The
-- anchor table is session-local (TEMP), feeds the self-check in
-- section 8 and is dropped at the end of the file. Statement order
-- matters: the holder lookups go through old_policy_id, so they
-- run BEFORE the re-key.
CREATE TEMP TABLE ins_fastlane_anchor AS
SELECT * FROM (VALUES
  (1, 'POL-007920', 'POL-104211', 'Lena Hartmann',   'APP',          640, '71063', 'Sindelfingen',   'VW Golf',       300, true,  timestamp '2026-07-18 19:12'),
  (2, 'POL-000039', 'POL-118902', 'Jonas Keller',    'VOICE_AGENT',  420, '71032', 'Boeblingen',     'Skoda Octavia', 150, false, timestamp '2026-07-18 19:40'),
  (3, 'POL-007958', 'POL-121377', 'Miriam Schaefer', 'APP',          890, '71083', 'Herrenberg',     'BMW 3 Series',  500, true,  timestamp '2026-07-18 20:05'),
  (4, 'POL-000077', 'POL-109654', 'Tobias Wagner',   'AGENCY_EMAIL', 310, '71229', 'Leonberg',       'Opel Corsa',    150, true,  timestamp '2026-07-19 08:15'),
  (5, 'POL-007996', 'POL-133018', 'Selin Aydin',     'APP',          760, '71065', 'Sindelfingen',   'Audi A4',       300, false, timestamp '2026-07-19 09:02'),
  (6, 'POL-000115', 'POL-115486', 'Markus Brandt',   'AGENCY_EMAIL', 540, '71034', 'Boeblingen',     'Ford Focus',    300, true,  timestamp '2026-07-19 10:48'),
  (7, 'POL-008034', 'POL-127730', 'Anna Fischer',    'APP',          950, '71093', 'Weil der Stadt', 'Toyota Yaris',  150, true,  timestamp '2026-07-19 15:30'),
  (8, 'POL-000153', 'POL-112245', 'Daniel Roth',     'VOICE_AGENT',  180, '71032', 'Boeblingen',     'Fiat 500',      500, false, timestamp '2026-07-20 07:55')
) AS v (c, old_policy_id, policy_id, full_name, channel, estimate_eur,
        postal_code, city, vehicle_model, deductible_eur,
        repair_network_clause, reported_at);

-- holder: anchor name, address, preferred channel
UPDATE ins_customers cu
SET full_name = a.full_name, city = a.city, postal_code = a.postal_code,
    segment = 'PRIVATE', preferred_channel = a.channel
FROM ins_fastlane_anchor a
JOIN ins_policies p ON p.policy_id = a.old_policy_id
WHERE cu.customer_id = p.customer_id;

-- the holder's sibling policy (p mod 4 pairs) follows the address
UPDATE ins_policies s
SET postal_code = a.postal_code, city = a.city
FROM ins_fastlane_anchor a
JOIN ins_policies p ON p.policy_id = a.old_policy_id
WHERE s.customer_id = p.customer_id AND s.policy_id <> a.old_policy_id;

-- re-key the bulk policy to the pinned id + anchor attributes
UPDATE ins_policies p
SET policy_id = a.policy_id, product = 'MOTOR_COMPREHENSIVE',
    vehicle_model = a.vehicle_model, garage_parking = false,
    postal_code = a.postal_code, city = a.city, district = 'BOEBLINGEN',
    hail_cover = true, deductible_eur = a.deductible_eur,
    repair_network_clause = a.repair_network_clause, status = 'ACTIVE'
FROM ins_fastlane_anchor a
WHERE p.policy_id = a.old_policy_id;

-- the claim: pinned policy, channel, estimate, reported_at
UPDATE ins_claims cl
SET policy_id = a.policy_id, fnol_channel = a.channel,
    reported_at = a.reported_at, status_since = a.reported_at,
    severity = 'MINOR', status = 'RECEIVED', assigned_partner_id = NULL,
    estimate_eur = a.estimate_eur,
    reserve_eur = (ROUND(a.estimate_eur * 1.15 / 50) * 50)::int,
    drivable = true
FROM ins_fastlane_anchor a
WHERE cl.claim_id = 'CLM-0913-' || lpad(a.c::text, 5, '0');

-- Cohort RN-3 share: 293 of 412 policies carry the clause.
UPDATE ins_policies p
SET repair_network_clause = (substr(cl.claim_id, 10)::int <= 6293)
FROM ins_claims cl
WHERE cl.policy_id = p.policy_id
  AND cl.claim_id BETWEEN 'CLM-0913-06001' AND 'CLM-0913-06412';

-- 4 cohort customers with a formal complaint (CLM-0913-06001..06004).
UPDATE ins_customers cu
SET complaint_flag = true
FROM ins_policies p
JOIN ins_claims cl ON cl.policy_id = p.policy_id
WHERE p.customer_id = cu.customer_id
  AND cl.claim_id BETWEEN 'CLM-0913-06001' AND 'CLM-0913-06004';

-- Scanner mismatch claim: customer claimed 60 dents, scanner counted
-- 14 (MongoDB scanner_results); drive-in estimate 6,800.
UPDATE ins_claims
SET estimate_eur = 6800, reserve_eur = 7800, drivable = true
WHERE claim_id = 'CLM-0913-08103';

-- -------------------------------------------------------------
-- 7. Payment run PR-2026-30 (Fri 2026-07-24 16:00): 3,900 items =
--    1,440 WORKSHOP items (all motor IN_REPAIR claims, amount =
--    workshop estimate, incl. the 17 W-0471 claims) + 2,460
--    CUSTOMER items (210 total losses, MINOR CONFIRMED odd ids
--    00101..04079, MODERATE CONFIRMED 08046..08306 incl. the
--    duplicates 08301..08306). Fraud-act items in the run: the 18
--    pattern-A items, the 6 duplicates and the 17 W-0471 items sum
--    to exactly EUR 218,000.00 at risk (08306 takes the remainder
--    of that block). All other customer amounts are scaled so the
--    run sums to EUR 14,200,000.00; items are numbered WORKSHOP
--    first, then CUSTOMER, and the last row absorbs the cents.
-- -------------------------------------------------------------
INSERT INTO ins_payment_items
WITH frd AS (
  SELECT claim_id,
         ROUND(3500 + ins_hash('frd' || claim_id) % 2400
               + (ins_hash('frd' || claim_id) / 2400 % 100) / 100.0, 2) AS amt
  FROM ins_claims
  WHERE (claim_id BETWEEN 'CLM-0913-08101' AND 'CLM-0913-08119'
         AND claim_id <> 'CLM-0913-08103')
     OR claim_id BETWEEN 'CLM-0913-08301' AND 'CLM-0913-08306'
), pay AS (
  SELECT cl.claim_id, p.customer_id, 'WORKSHOP' AS payee_type,
         cl.assigned_partner_id AS payee_partner_id,
         e.total_eur AS fixed_amt, NULL::numeric AS w
  FROM ins_claims cl
  JOIN ins_policies p ON p.policy_id = cl.policy_id
  JOIN ins_workshop_estimates e ON e.claim_id = cl.claim_id
  WHERE cl.line = 'MOTOR' AND cl.status = 'IN_REPAIR'
  UNION ALL
  SELECT cl.claim_id, p.customer_id, 'CUSTOMER', NULL,
         CASE WHEN cl.claim_id = 'CLM-0913-08306' THEN ROUND(
                218000.00
                - (SELECT SUM(total_eur) FROM ins_workshop_estimates
                   WHERE claim_id BETWEEN 'CLM-0913-08401' AND 'CLM-0913-08417')
                - (SELECT SUM(amt) FROM frd WHERE claim_id <> 'CLM-0913-08306'), 2)
              ELSE f.amt END,
         CASE WHEN f.claim_id IS NOT NULL THEN NULL
              WHEN cl.status = 'TOTAL_LOSS_FASTLANE'
                THEN 20000 + ins_hash('pay' || cl.claim_id) % 17000
              WHEN cl.severity = 'MINOR'
                THEN 420 + ins_hash('pay' || cl.claim_id) % 530
              ELSE 2400 + ins_hash('pay' || cl.claim_id) % 4500 END
  FROM ins_claims cl
  JOIN ins_policies p ON p.policy_id = cl.policy_id
  LEFT JOIN frd f ON f.claim_id = cl.claim_id
  WHERE cl.status = 'TOTAL_LOSS_FASTLANE'
     OR (cl.status = 'CONFIRMED'
         AND ((substr(cl.claim_id, 10)::int BETWEEN 101 AND 4080
               AND substr(cl.claim_id, 10)::int % 2 = 1)
              OR substr(cl.claim_id, 10)::int BETWEEN 8046 AND 8306))
), scaled AS (
  SELECT pay.*,
         (14200000 - SUM(fixed_amt) OVER ()) / SUM(w) OVER () AS k
  FROM pay
)
SELECT 'PI-30-' || lpad((row_number() OVER
           (ORDER BY payee_type DESC, claim_id))::text, 5, '0'),
       'PR-2026-30', claim_id, payee_type, payee_partner_id,
       md5('iban:' || COALESCE(payee_partner_id, customer_id)),
       COALESCE(fixed_amt, ROUND(w * k, 2)),
       'SCHEDULED', timestamp '2026-07-24 16:00'
FROM scaled;

UPDATE ins_payment_items
SET amount_eur = ROUND(amount_eur
    + (14200000.00 - (SELECT SUM(amount_eur) FROM ins_payment_items)), 2)
WHERE payment_item_id = 'PI-30-03900';

DROP FUNCTION ins_hash(text);

-- -------------------------------------------------------------
-- 8. Self-check: the storyline numbers, printed as NOTICEs.
-- -------------------------------------------------------------
DO $$
DECLARE
  n_claims int; n_motor int; n_minor int; n_moderate int; n_severe int;
  n_conf int; n_await int; n_repair int; n_tl int; n_recv int;
  n_app int; n_voice int; n_portal int; n_scan int; n_mail int;
  n_cohort int; n_rn3 int; n_braendle int; n_bb int; n_lb int;
  n_lbprop int; n_est int; n_w0471 int; n_items int; sum_items numeric;
  n_pol int; n_cus int; n_fl int;
BEGIN
  SELECT count(*), count(*) FILTER (WHERE line = 'MOTOR'),
         count(*) FILTER (WHERE severity = 'MINOR'),
         count(*) FILTER (WHERE severity = 'MODERATE'),
         count(*) FILTER (WHERE severity = 'SEVERE'),
         count(*) FILTER (WHERE status = 'CONFIRMED'),
         count(*) FILTER (WHERE status = 'AWAITING_WORKSHOP_SLOT'),
         count(*) FILTER (WHERE status = 'IN_REPAIR'),
         count(*) FILTER (WHERE status = 'TOTAL_LOSS_FASTLANE'),
         count(*) FILTER (WHERE status = 'RECEIVED'),
         count(*) FILTER (WHERE fnol_channel = 'APP'),
         count(*) FILTER (WHERE fnol_channel = 'VOICE_AGENT'),
         count(*) FILTER (WHERE fnol_channel = 'WORKSHOP_PORTAL'),
         count(*) FILTER (WHERE fnol_channel = 'DRIVE_IN_SCANNER'),
         count(*) FILTER (WHERE fnol_channel = 'AGENCY_EMAIL'),
         count(*) FILTER (WHERE status = 'AWAITING_WORKSHOP_SLOT'
                            AND status_since < timestamp '2026-07-20 06:00'),
         count(*) FILTER (WHERE assigned_partner_id = 'P-BRAENDLE'
                            AND status = 'AWAITING_WORKSHOP_SLOT')
    INTO n_claims, n_motor, n_minor, n_moderate, n_severe, n_conf, n_await,
         n_repair, n_tl, n_recv, n_app, n_voice, n_portal, n_scan, n_mail,
         n_cohort, n_braendle
  FROM ins_claims;
  SELECT count(*) INTO n_rn3
  FROM ins_claims cl JOIN ins_policies p ON p.policy_id = cl.policy_id
  WHERE cl.claim_id BETWEEN 'CLM-0913-06001' AND 'CLM-0913-06412'
    AND p.repair_network_clause;
  SELECT count(*) FILTER (WHERE district = 'BOEBLINGEN' AND NOT garage_parking),
         count(*) FILTER (WHERE district = 'LUDWIGSBURG' AND NOT garage_parking),
         count(*) FILTER (WHERE district = 'LUDWIGSBURG' AND product = 'PROPERTY')
    INTO n_bb, n_lb, n_lbprop
  FROM ins_policies;
  SELECT count(*), count(*) FILTER (WHERE partner_id = 'P-KAROSSERIE-SCHNELL'
                                      AND hourly_rate_eur > 118)
    INTO n_est, n_w0471 FROM ins_workshop_estimates;
  SELECT count(*), sum(amount_eur) INTO n_items, sum_items
  FROM ins_payment_items WHERE payment_run_id = 'PR-2026-30';
  SELECT count(*) INTO n_pol FROM ins_policies;
  SELECT count(*) INTO n_cus FROM ins_customers;
  -- Fast Lane sample anchor (section 6): every pinned attribute of
  -- claim, policy and holder as the cockpit publishes them (8 expected)
  SELECT count(*) INTO n_fl
  FROM ins_fastlane_anchor a
  JOIN ins_claims cl ON cl.claim_id = 'CLM-0913-' || lpad(a.c::text, 5, '0')
  JOIN ins_policies p ON p.policy_id = cl.policy_id
  JOIN ins_customers cu ON cu.customer_id = p.customer_id
  WHERE cl.policy_id = a.policy_id AND cl.fnol_channel = a.channel
    AND cl.estimate_eur = a.estimate_eur AND cl.reported_at = a.reported_at
    AND cl.status_since = cl.reported_at
    AND cl.severity = 'MINOR' AND cl.status = 'RECEIVED'
    AND cu.full_name = a.full_name
    AND p.product = 'MOTOR_COMPREHENSIVE' AND p.district = 'BOEBLINGEN'
    AND p.hail_cover AND NOT p.garage_parking
    AND p.vehicle_model = a.vehicle_model AND p.city = a.city
    AND p.postal_code = a.postal_code
    AND p.deductible_eur = a.deductible_eur
    AND p.repair_network_clause = a.repair_network_clause;
  RAISE NOTICE 'acme_insurance: % claims (% motor); severity %/%/%; status C %/A %/R %/TL %/RC %',
    n_claims, n_motor, n_minor, n_moderate, n_severe, n_conf, n_await,
    n_repair, n_tl, n_recv;
  RAISE NOTICE 'acme_insurance: channels APP % / VOICE % / PORTAL % / SCANNER % / EMAIL %',
    n_app, n_voice, n_portal, n_scan, n_mail;
  RAISE NOTICE 'acme_insurance: stalled cohort % (RN-3 %), P-BRAENDLE awaiting %, W-0471 estimates %, estimates total %',
    n_cohort, n_rn3, n_braendle, n_w0471, n_est;
  RAISE NOTICE 'acme_insurance: no-garage motor policies BOEBLINGEN % / LUDWIGSBURG % (property LB %); PR-2026-30 % items EUR %',
    n_bb, n_lb, n_lbprop, n_items, sum_items;
  RAISE NOTICE 'acme_insurance: policies % / customers %; Fast Lane anchor 00001..00008 (pinned policy, holder, channel, estimate): % of 8',
    n_pol, n_cus, n_fl;
END $$;

DROP TABLE ins_fastlane_anchor;
