// Seed 1/2 for the acme_claims MongoDB store (Acme Insurance demo):
// read-only user + deterministic bulk generator. Runs once, on the
// first init of the mongo volume, via /docker-entrypoint-initdb.d
// (mongosh, alphabetical order, root user). 02-anchors.js then
// re-asserts the story anchor documents and creates the indexes.
//
// No checked-in ndjson: everything is generated here with a seeded
// PRNG (mulberry32, seed 913), so every run produces the identical
// documents. Runtime is a few seconds (insertMany in 1,000-doc
// batches). All Dates are the story's wall-clock times stored as
// UTC ("today" in the demo = Mon 2026-07-20 10:00).
//
// Storyline (hail cell HZ-0913):
//
// - Sat 2026-07-18 18:40 hail cell HZ-0913 (3.5 cm, warning level
//   3) crosses Landkreis Boeblingen. By Monday 10:00 Acme has
//   10,400 first notices of loss: 9,650 motor + 750 property, one
//   fnol_intake document per claim CLM-0913-00001..10400 (the same
//   claim ids as acme_insurance.ins_claims in Postgres) PLUS 63
//   second-call documents (is_repeat_contact: true, VOICE_AGENT)
//   for the stalled cohort -> 10,463 documents.
// - Stalled cohort CLM-0913-06001..06412 (waiting at P-BRAENDLE):
//   06001..06158 carry the total-loss signature (glass shattered
//   AND roof deformed AND > 150 dents), 06001..06063 called a
//   second time on Monday morning, 06001..06004 filed a formal
//   complaint during that second call.
// - Fraud patterns (act 2): 08101..08119 photos with EXIF 6-9 days
//   BEFORE the cell (08103 = the scanner-mismatch claim, "about 60
//   dents" claimed, 14 scanned); 08201..08211 (APP) and
//   08301..08311 (VOICE_AGENT) share a VIN pairwise with dent
//   counts 20-40 apart, reported within 48 h; 08401..08417 come
//   with a workshop estimate from W-0471 (P-KAROSSERIE-SCHNELL),
//   08401..08409 with an identical line-item text.
// - weather_cells: HZ-0913 (observed), HZ-0914 (forecast for Tue
//   2026-07-21 over Landkreis Ludwigsburg), HZ-0907 (historic
//   2 cm cell, conversion 0.28).
// - scanner_results: one document per DRIVE_IN_SCANNER claim
//   (1,040), mismatch_flag only on CLM-0913-08103.
//
// Channel / severity rule (deterministic, exact story totals):
//   line      motor = CLM-0913-00001..09650, property = 09651..10400
//   channel   motor    APP 3,860 | VOICE_AGENT 2,350 |
//                      WORKSHOP_PORTAL 1,560 | DRIVE_IN_SCANNER 1,040
//                      | AGENCY_EMAIL 840
//             property APP 300 | VOICE_AGENT 250 | AGENCY_EMAIL 200
//             (totals APP 4,160 / VOICE_AGENT 2,600 / WORKSHOP_PORTAL
//              1,560 / DRIVE_IN_SCANNER 1,040 / AGENCY_EMAIL 1,040)
//   severity  motor    MINOR 5,750 | MODERATE 3,340 | SEVERE 560
//             property MINOR 450 | MODERATE 260 | SEVERE 40
//             (totals MINOR 6,200 / MODERATE 3,600 / SEVERE 600)
//   Anchor claims are pinned first; the remaining quota of each
//   line is shuffled with the seeded PRNG over the non-anchor
//   claims. The 452 claims with pinned intake times (Fast Lane
//   sample 00001..00040 + cohort 06001..06412, Saturday night /
//   Sunday dawn) only use APP / VOICE_AGENT / AGENCY_EMAIL (200 /
//   160 / 92 in total: the 8 sample anchors 00001..00008 carry
//   fixed channels 4 / 2 / 2, the other 444 draw from the
//   sub-quota 196 / 158 / 90): drive-ins and workshops are closed
//   at night, and an undrivable total-loss car does not visit a
//   drive-in. Pinned anchors:
//     00001..00008  MINOR (Fast Lane sample published by the
//                   cockpit): channel, intake time, place, vehicle
//                   and customer fixed (MINOR_SAMPLE below)
//     00009..00040  MINOR (Fast Lane sample), channel free
//     06001..06158  SEVERE + total-loss signature (cohort)
//     06159..06412  MODERATE, no total-loss signature (cohort)
//     08101..08119  pattern A: APP, MODERATE -- except 08103 =
//                   DRIVE_IN_SCANNER (the scanner-mismatch claim)
//     08201..08211  pattern B primaries: APP, MODERATE
//     08301..08311  pattern B duplicates: VOICE_AGENT, MODERATE
//     08401..08417  pattern C: WORKSHOP_PORTAL, MODERATE
//   Intake times follow a per-channel curve (Sat evening peak, Sun
//   morning peak, Monday-morning wave for agencies / workshops);
//   anchors carry fixed times (cohort before Sun 09:00, second
//   calls Mon 07:00-09:45, pattern B duplicates 13-29 h after the
//   primary, pattern C Mon 07:10-09:20).

db = db.getSiblingDB('acme_claims');

// Read-only user for the SAM MongoDB connectors (demo creds).
if (!db.getUser('sam_ro')) {
  db.createUser({
    user: 'sam_ro',
    pwd: 'sam_ro',
    roles: [ { role: 'read', db: 'acme_claims' } ]
  });
}

// Fresh collections (initdb runs once; this keeps manual re-runs
// of the file idempotent as well).
db.fnol_intake.drop();
db.scanner_results.drop();
db.weather_cells.drop();

const t0 = Date.now();

// ---- deterministic PRNG (mulberry32, seed 913) -------------------
function mulberry32(seed) {
  let a = seed | 0;
  return function () {
    a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const rand = mulberry32(913);
function rint(lo, hi) { return lo + Math.floor(rand() * (hi - lo + 1)); }
function pick(arr) { return arr[Math.floor(rand() * arr.length)]; }
function chance(p) { return rand() < p; }
function shuffle(arr) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    const tmp = arr[i]; arr[i] = arr[j]; arr[j] = tmp;
  }
  return arr;
}
function hex(n) {
  let s = '';
  for (let i = 0; i < n; i++) s += Math.floor(rand() * 16).toString(16);
  return s;
}
function fakeHash(s) {
  // FNV-1a twice -> 16 hex chars, deterministic (same as 02-anchors.js)
  let h1 = 0x811c9dc5, h2 = 0x01000193;
  for (const ch of s) {
    h1 = Math.imul(h1 ^ ch.charCodeAt(0), 0x01000193) >>> 0;
    h2 = Math.imul(h2 ^ ch.charCodeAt(0), 0x811c9dc5) >>> 0;
  }
  return h1.toString(16).padStart(8, '0') + h2.toString(16).padStart(8, '0');
}
function pad5(i) { return String(i).padStart(5, '0'); }
function claimId(i) { return 'CLM-0913-' + pad5(i); }
function round10(x) { return Math.round(x / 10) * 10; }

// ---- time helpers ------------------------------------------------
const SEC = 1000, MIN = 60 * SEC, HOUR = 60 * MIN, DAY = 24 * HOUR;
function utc(s) { return new Date(s); }
function at(d, ms) { return new Date(d.getTime() + ms); }
function between(a, b) {
  return at(a, Math.floor(rand() * (b.getTime() - a.getTime())));
}
const CELL_START = utc('2026-07-18T18:40:00Z');
const CELL_END   = utc('2026-07-18T19:25:00Z');
const NOW        = utc('2026-07-20T10:00:00Z');

// Intake curves per channel: [start, end, weight]. APP and the
// 24/7 voice agent see the Saturday-evening and Sunday peaks;
// agencies, workshops and drive-ins work Sunday daytime and the
// Monday-morning wave.
function curve(rows) {
  return rows.map(r => [utc(r[0]), utc(r[1]), r[2]]);
}
const CURVE_247 = curve([
  ['2026-07-18T18:50:00Z', '2026-07-19T00:00:00Z', 18],
  ['2026-07-19T00:00:00Z', '2026-07-19T07:00:00Z', 4],
  ['2026-07-19T07:00:00Z', '2026-07-19T12:00:00Z', 24],
  ['2026-07-19T12:00:00Z', '2026-07-19T18:00:00Z', 22],
  ['2026-07-19T18:00:00Z', '2026-07-20T00:00:00Z', 12],
  ['2026-07-20T00:00:00Z', '2026-07-20T06:00:00Z', 3],
  ['2026-07-20T06:00:00Z', '2026-07-20T09:55:00Z', 17],
]);
const CURVES = {
  APP: CURVE_247,
  VOICE_AGENT: CURVE_247,
  AGENCY_EMAIL: curve([
    ['2026-07-18T19:00:00Z', '2026-07-18T22:00:00Z', 3],
    ['2026-07-19T09:00:00Z', '2026-07-19T20:00:00Z', 10],
    ['2026-07-20T07:00:00Z', '2026-07-20T09:55:00Z', 12],
  ]),
  WORKSHOP_PORTAL: curve([
    ['2026-07-19T09:00:00Z', '2026-07-19T17:00:00Z', 8],
    ['2026-07-20T06:30:00Z', '2026-07-20T09:55:00Z', 14],
  ]),
  DRIVE_IN_SCANNER: curve([
    ['2026-07-19T08:00:00Z', '2026-07-19T18:00:00Z', 10],
    ['2026-07-20T07:00:00Z', '2026-07-20T09:55:00Z', 6],
  ]),
};
function drawTime(rows) {
  let total = 0;
  for (const r of rows) total += r[2];
  let x = rand() * total;
  for (const r of rows) {
    if (x < r[2]) return between(r[0], r[1]);
    x -= r[2];
  }
  return between(rows[rows.length - 1][0], rows[rows.length - 1][1]);
}

// ---- geography ---------------------------------------------------
// Landkreis Boeblingen (HZ-0913): [postal_code, city, lat, lon].
// Fictional postal-code to city mapping restricted to the eight
// story cities (71093 = Weil der Stadt as in the Fast Lane sample
// contract, CLM-0913-00007).
const BB_PLACES = [
  ['71032', 'Boeblingen', 48.6856, 9.0153],
  ['71034', 'Boeblingen', 48.6790, 9.0300],
  ['71063', 'Sindelfingen', 48.7134, 9.0030],
  ['71065', 'Sindelfingen', 48.7080, 9.0210],
  ['71067', 'Sindelfingen', 48.7220, 8.9870],
  ['71069', 'Sindelfingen', 48.7000, 8.9650],
  ['71083', 'Herrenberg', 48.5960, 8.8700],
  ['71093', 'Weil der Stadt', 48.7530, 8.8880],
  ['71101', 'Schoenaich', 48.6600, 9.0610],
  ['71229', 'Leonberg', 48.8000, 9.0130],
  ['71263', 'Weil der Stadt', 48.7510, 8.8700],
  ['71272', 'Leonberg', 48.7660, 8.9330],
  ['71277', 'Leonberg', 48.8080, 8.9450],
  ['71287', 'Weil der Stadt', 48.7470, 8.9270],
  ['71296', 'Holzgerlingen', 48.6400, 9.0120],
  ['71297', 'Gaertringen', 48.6400, 8.9000],
];
const BB_POSTAL = BB_PLACES.map(p => p[0]);
const BB_CITIES = ['Boeblingen', 'Sindelfingen', 'Herrenberg', 'Leonberg',
  'Weil der Stadt', 'Schoenaich', 'Holzgerlingen', 'Gaertringen'];
// Landkreis Ludwigsburg (HZ-0914 forecast, HZ-0907 historic).
const LB_POSTAL = ['71634', '71636', '71638', '71640', '71642', '71672',
  '71679', '71686', '71691', '71701', '71706', '71711', '71723', '71726',
  '71729', '71732'];
const LB_CITIES = ['Ludwigsburg', 'Kornwestheim', 'Bietigheim-Bissingen',
  'Marbach', 'Remseck', 'Freiberg', 'Asperg', 'Ditzingen'];

function location() {
  const p = pick(BB_PLACES);
  return {
    postal_code: p[0], city: p[1], district: 'BOEBLINGEN',
    lat: Math.round((p[2] + (rand() - 0.5) * 0.02) * 10000) / 10000,
    lon: Math.round((p[3] + (rand() - 0.5) * 0.03) * 10000) / 10000,
  };
}

// ---- vehicles ----------------------------------------------------
// [WMI, model code, model name]; VIN = WMI + 'ZZZ' + code + 'ZRW' +
// 6-digit serial derived from the claim index (unique by
// construction -> the only duplicate VINs are the 11 pattern-B
// pairs).
const MODELS = [
  ['WVW', '1K', 'VW Golf'], ['WVG', '5N', 'VW Tiguan'],
  ['WVW', '3C', 'VW Passat'], ['WDD', '17', 'Mercedes A-Class'],
  ['WDD', '20', 'Mercedes C-Class'], ['WDC', '25', 'Mercedes GLC'],
  ['WBA', '3A', 'BMW 3 Series'], ['WBA', 'X1', 'BMW X1'],
  ['WAU', '8W', 'Audi A4'], ['WAU', 'F3', 'Audi Q3'],
  ['TMB', 'NX', 'Skoda Octavia'], ['W0V', 'BK', 'Opel Astra'],
  ['W0V', 'SD', 'Opel Corsa'], ['WF0', 'KX', 'Ford Focus'],
  ['VSS', 'KL', 'Seat Leon'], ['TMA', 'PD', 'Hyundai i30'],
  ['WP1', '95', 'Porsche Macan'], ['SB1', 'KF', 'Toyota Yaris'],
  ['WMW', 'LN', 'Mini Cooper'], ['ZFA', '31', 'Fiat 500'],
  ['VF1', 'RJ', 'Renault Clio'],
];
// modelName pins the model (Fast Lane sample), otherwise the PRNG
// picks one; the VIN prefix always follows the model.
function vehicle(i, modelName) {
  const m = modelName ? MODELS.find(x => x[2] === modelName) : pick(MODELS);
  const serial = String((i * 7919 + 100003) % 1000000).padStart(6, '0');
  return { vin: m[0] + 'ZZZ' + m[1] + 'ZRW' + serial, model: m[2],
           garage_parking: false };
}
function customerRef(i) {
  return 'CUST-' + String(100000 + ((i * 6007) % 52000));
}

// ---- Fast Lane sample anchors CLM-0913-00001..00008 --------------
// The cockpit publishes these eight MINOR claims as fnol events and
// the Fast Lane Clerk confirms them from Postgres, so channel,
// intake time (= reported_at), place, vehicle and customer are a
// cross-store contract: identical values in acme_insurance
// (ins_claims / ins_policies / ins_customers) and cockpit/index.html.
// Postgres estimates for the record: 640 / 420 / 890 / 310 / 760 /
// 540 / 950 / 180 EUR (all < 1,000 -> MINOR, 5-25 dents, no glass,
// drivable). 02-anchors.js re-asserts the same documents (same
// table and text builders there, no PRNG involved). Columns:
// c, channel, received_at, postal_code, city, lat, lon, model,
// dents, customer, panels, agency (AGENCY_EMAIL only).
const MINOR_SAMPLE = [
  [1, 'APP', '2026-07-18T19:12:00Z', '71063', 'Sindelfingen', 48.7134, 9.0030,
   'VW Golf', 16, 'Lena Hartmann', 'roof and bonnet', null],
  [2, 'VOICE_AGENT', '2026-07-18T19:40:00Z', '71032', 'Boeblingen', 48.6856, 9.0153,
   'Skoda Octavia', 11, 'Jonas Keller', 'roof and bonnet', null],
  [3, 'APP', '2026-07-18T20:05:00Z', '71083', 'Herrenberg', 48.5960, 8.8700,
   'BMW 3 Series', 22, 'Miriam Schaefer', 'roof, bonnet and boot lid', null],
  [4, 'AGENCY_EMAIL', '2026-07-19T08:15:00Z', '71229', 'Leonberg', 48.8000, 9.0130,
   'Opel Corsa', 8, 'Tobias Wagner', 'bonnet and both front wings',
   'Acme Agency Leonberg'],
  [5, 'APP', '2026-07-19T09:02:00Z', '71065', 'Sindelfingen', 48.7080, 9.0210,
   'Audi A4', 19, 'Selin Aydin', 'roof and boot lid', null],
  [6, 'AGENCY_EMAIL', '2026-07-19T10:48:00Z', '71034', 'Boeblingen', 48.6790, 9.0300,
   'Ford Focus', 14, 'Markus Brandt', 'roof and bonnet',
   'Acme Agency Boeblingen'],
  [7, 'APP', '2026-07-19T15:30:00Z', '71093', 'Weil der Stadt', 48.7530, 8.8880,
   'Toyota Yaris', 24, 'Anna Fischer', 'roof, bonnet and boot lid', null],
  [8, 'VOICE_AGENT', '2026-07-20T07:55:00Z', '71032', 'Boeblingen', 48.6856, 9.0153,
   'Fiat 500', 5, 'Daniel Roth', 'bonnet', null],
].map(r => ({ c: r[0], channel: r[1], received_at: utc(r[2]),
              location: { postal_code: r[3], city: r[4], district: 'BOEBLINGEN',
                          lat: r[5], lon: r[6] },
              model: r[7], dents: r[8], customer: r[9], panels: r[10],
              agency: r[11] }));
const SAMPLE_BY_ID = {};
MINOR_SAMPLE.forEach(r => { SAMPLE_BY_ID[r.c] = r; });
function isSampleAnchor(i) { return i >= 1 && i <= 8; }
const SAMPLE_PHOTOS = { APP: 3, AGENCY_EMAIL: 2, VOICE_AGENT: 0 };
// Photos taken 25 / 22 / 19 min before the report (after the cell),
// a few dents each; the voice channel carries none.
function samplePhotos(r) {
  const n = SAMPLE_PHOTOS[r.channel], out = [];
  for (let k = 1; k <= n; k++) {
    out.push({
      photo_id: 'PH-' + pad5(r.c) + '-' + k,
      exif_taken_at: at(r.received_at, -(28 - 3 * k) * MIN),
      gps: { lat: Math.round((r.location.lat + (k - 2) * 0.0003) * 10000) / 10000,
             lon: Math.round((r.location.lon + (k - 2) * 0.0004) * 10000) / 10000 },
      dent_count_est: Math.max(1, Math.round(r.dents / n) + (k - 2)),
      image_hash: fakeHash(claimId(r.c) + '/' + k),
    });
  }
  return out;
}
function sampleTexts(r) {
  const where = r.location.city + ' (' + r.location.postal_code + ')';
  const dmg = 'about ' + r.dents + ' small dents on ' + r.panels
    + ', no glass damage, car drives fine';
  if (r.channel === 'APP') {
    return { narrative: 'Hail damage from Saturday evening on my ' + r.model
      + ' parked in the street in ' + where + ': ' + dmg
      + '. Photos attached. Reported by ' + r.customer + ' via the Acme app.' };
  }
  if (r.channel === 'AGENCY_EMAIL') {
    return { narrative: 'Agency ' + r.agency + ' forwards a customer notice from '
      + r.customer + ': ' + r.model + ' damaged by hail on 18 July in ' + where + ', '
      + dmg + '. Customer asks for a partner-workshop appointment.' };
  }
  return {
    narrative: 'Voice agent summary: ' + r.customer + ' reports hail damage on a '
      + r.model + ' parked in the street in ' + where + ': ' + dmg
      + '; roof intact. Drive-in appointment requested.',
    voice_transcript:
      'Agent: Acme Insurance claims line, this is the voice assistant. How can I help you?\n'
      + 'Caller: My name is ' + r.customer
      + ', my car got hit by the hail on Saturday evening in ' + r.location.city + '.\n'
      + 'Agent: I am sorry to hear that. Where was the vehicle parked and how bad is the damage?\n'
      + 'Caller: In the street outside our house, no garage. It is a ' + r.model
      + ', I count about ' + r.dents + ' small dents on ' + r.panels
      + ', the glass is fine and I can still drive it.\n'
      + 'Agent: Thank you. I have opened claim ' + claimId(r.c) + ' for your ' + r.model
      + '. A drive-in appointment proposal will follow by SMS.',
  };
}

// ---- partners / agencies (names as in acme_insurance) ------------
const DRIVE_INS = [
  ['P-BRAENDLE', 'Braendle Drive-In Hail Center', 60],
  ['P-HAGELPOINT-LB', 'Hagelpoint Ludwigsburg', 25],
  ['P-DELLENFIX-LB', 'Dellenfix Ludwigsburg', 15],
];
const BODY_SHOPS = [
  ['P-AUTOWERK-BB', 'Autowerk Boeblingen', null],
  ['P-LACKPROFI-LEO', 'Lackprofi Leonberg', null],
  ['P-KAROSSERIE-SCHNELL', 'Karosserie Schnell GmbH', 'W-0471'],
];
const AGENCIES = ['Acme Agency Boeblingen', 'Acme Agency Sindelfingen',
  'Acme Agency Herrenberg', 'Acme Agency Leonberg',
  'Acme Agency Weil der Stadt'];
function weightedPick(rows) {
  let total = 0;
  for (const r of rows) total += r[2];
  let x = rand() * total;
  for (const r of rows) { if (x < r[2]) return r; x -= r[2]; }
  return rows[rows.length - 1];
}

// ---- channel / severity quotas ----------------------------------
const N_CLAIMS = 10400, N_MOTOR = 9650;
const CHANNEL_TOTALS = {
  MOTOR: { APP: 3860, VOICE_AGENT: 2350, WORKSHOP_PORTAL: 1560,
           DRIVE_IN_SCANNER: 1040, AGENCY_EMAIL: 840 },
  PROPERTY: { APP: 300, VOICE_AGENT: 250, AGENCY_EMAIL: 200 },
};
const SEVERITY_TOTALS = {
  MOTOR: { MINOR: 5750, MODERATE: 3340, SEVERE: 560 },
  PROPERTY: { MINOR: 450, MODERATE: 260, SEVERE: 40 },
};
// Channel sub-quota for the 444 free claims with pinned off-hours
// intake times (Fast Lane sample 00009..00040 + cohort 06001..06412):
// no drive-in / workshop intake at night, none for an undrivable
// car. Together with the 8 fixed sample anchors (4 APP / 2
// VOICE_AGENT / 2 AGENCY_EMAIL) the pinned-time pool is 200 / 160 /
// 92, so the line totals above hold by construction.
const PINNED_CHANNELS = { APP: 196, VOICE_AGENT: 158, AGENCY_EMAIL: 90 };

const channelOf = new Array(N_CLAIMS + 1);
const severityOf = new Array(N_CLAIMS + 1);
function inRange(i, lo, hi) { return i >= lo && i <= hi; }
function isMotor(i) { return i <= N_MOTOR; }
function isTotalLoss(i) { return inRange(i, 6001, 6158); }
function isCohort(i) { return inRange(i, 6001, 6412); }
function isPatternA(i) { return inRange(i, 8101, 8119); }
function isPatternBPrimary(i) { return inRange(i, 8201, 8211); }
function isPatternBDup(i) { return inRange(i, 8301, 8311); }
function isPatternC(i) { return inRange(i, 8401, 8417); }
function isMinorSample(i) { return inRange(i, 1, 40); }

// 1. pin the anchors
for (let i = 1; i <= N_CLAIMS; i++) {
  if (isMinorSample(i)) severityOf[i] = 'MINOR';
  if (isSampleAnchor(i)) channelOf[i] = SAMPLE_BY_ID[i].channel;
  if (isTotalLoss(i)) severityOf[i] = 'SEVERE';
  else if (isCohort(i)) severityOf[i] = 'MODERATE';
  if (isPatternA(i)) {
    channelOf[i] = (i === 8103) ? 'DRIVE_IN_SCANNER' : 'APP';
    severityOf[i] = 'MODERATE';
  }
  if (isPatternBPrimary(i)) { channelOf[i] = 'APP'; severityOf[i] = 'MODERATE'; }
  if (isPatternBDup(i)) { channelOf[i] = 'VOICE_AGENT'; severityOf[i] = 'MODERATE'; }
  if (isPatternC(i)) { channelOf[i] = 'WORKSHOP_PORTAL'; severityOf[i] = 'MODERATE'; }
}

// 2. shuffle the remaining quota over the free claims of each line
function assignQuota(ids, quota, target) {
  const labels = [];
  for (const label in quota) {
    if (quota[label] < 0) throw new Error('negative quota for ' + label);
    for (let k = 0; k < quota[label]; k++) labels.push(label);
  }
  if (labels.length !== ids.length) {
    throw new Error('quota ' + labels.length + ' != ids ' + ids.length);
  }
  shuffle(labels);
  ids.forEach((id, k) => { target[id] = labels[k]; });
}
function remaining(totals, lo, hi, target) {
  const q = Object.assign({}, totals);
  for (let i = lo; i <= hi; i++) if (target[i]) q[target[i]] -= 1;
  return q;
}
function freeIds(lo, hi, target, filter) {
  const ids = [];
  for (let i = lo; i <= hi; i++) {
    if (!target[i] && (!filter || filter(i))) ids.push(i);
  }
  return ids;
}
// motor channels: pinned-time claims first, then everything else
const motorChannelQ = remaining(CHANNEL_TOTALS.MOTOR, 1, N_MOTOR, channelOf);
for (const c in PINNED_CHANNELS) motorChannelQ[c] -= PINNED_CHANNELS[c];
assignQuota(freeIds(1, N_MOTOR, channelOf, i => isMinorSample(i) || isCohort(i)),
            PINNED_CHANNELS, channelOf);
assignQuota(freeIds(1, N_MOTOR, channelOf), motorChannelQ, channelOf);
// motor severities
assignQuota(freeIds(1, N_MOTOR, severityOf),
            remaining(SEVERITY_TOTALS.MOTOR, 1, N_MOTOR, severityOf),
            severityOf);
// property
assignQuota(freeIds(N_MOTOR + 1, N_CLAIMS, channelOf),
            CHANNEL_TOTALS.PROPERTY, channelOf);
assignQuota(freeIds(N_MOTOR + 1, N_CLAIMS, severityOf),
            SEVERITY_TOTALS.PROPERTY, severityOf);

// ---- received_at per claim --------------------------------------
const SAT_2000 = utc('2026-07-18T20:00:00Z');
const MON_0710 = utc('2026-07-20T07:10:00Z');
const receivedAtOf = new Array(N_CLAIMS + 1);
for (let i = 1; i <= N_CLAIMS; i++) {
  let t;
  if (isSampleAnchor(i)) {
    t = SAMPLE_BY_ID[i].received_at;
  } else if (isMinorSample(i)) {
    t = at(CELL_START, 12 * MIN + (i - 1) * 2 * MIN + rint(0, 90) * SEC);
  } else if (isCohort(i)) {
    t = between(utc('2026-07-18T19:30:00Z'), utc('2026-07-19T08:30:00Z'));
  } else if (i === 8103) {
    t = utc('2026-07-20T09:20:00Z');
  } else if (isPatternA(i)) {
    t = between(utc('2026-07-19T10:00:00Z'), utc('2026-07-19T16:00:00Z'));
  } else if (isPatternBPrimary(i)) {
    t = at(SAT_2000, (i - 8201) * 25 * MIN);
  } else if (isPatternBDup(i)) {
    const k = i - 8300;
    t = at(receivedAtOf[i - 100], 12 * HOUR + Math.round(k * 1.5 * HOUR));
  } else if (isPatternC(i)) {
    t = at(MON_0710, (i - 8401) * 8 * MIN);
  } else {
    t = drawTime(CURVES[channelOf[i]]);
  }
  receivedAtOf[i] = t;
}

// ---- damage signals ----------------------------------------------
// Total-loss cohort dent count 160..240 (same formula in
// 02-anchors.js); pattern B primary 30..70, duplicate +20..40.
function tlDents(k) { return 160 + ((k * 37) % 81); }
function pbDents(k) { return 30 + ((k * 7) % 41); }
function pbDelta(k) { return 20 + ((k * 3) % 21); }

function motorDamage(i, sev, channel) {
  let dents, glass, roof, drivable;
  if (isTotalLoss(i)) {
    return { glass_shattered: true, roof_deformed: true,
             dent_count_est: tlDents(i - 6000), drivable: false };
  }
  if (i === 8103) {
    return { glass_shattered: false, roof_deformed: false,
             dent_count_est: 60, drivable: true };
  }
  if (isPatternBPrimary(i)) {
    return { glass_shattered: false, roof_deformed: false,
             dent_count_est: pbDents(i - 8200), drivable: true };
  }
  if (isPatternBDup(i)) {
    const k = i - 8300;
    return { glass_shattered: false, roof_deformed: false,
             dent_count_est: pbDents(k) + pbDelta(k), drivable: true };
  }
  if (sev === 'MINOR') {
    if (chance(0.2)) { glass = true; dents = rint(0, 6); }
    else { glass = false; dents = rint(3, 24); }
    roof = false; drivable = true;
  } else if (sev === 'MODERATE') {
    dents = rint(25, 120); glass = chance(0.15); roof = chance(0.2);
    drivable = chance(0.95);
  } else {
    dents = rint(120, 260); glass = chance(0.6); roof = chance(0.7);
    drivable = chance(0.45);
  }
  if (channel === 'DRIVE_IN_SCANNER') drivable = true;
  return { glass_shattered: glass, roof_deformed: roof,
           dent_count_est: dents, drivable: drivable };
}
function propertyDamage(sev) {
  if (sev === 'MINOR') {
    return { glass_shattered: chance(0.1), roof_deformed: false,
             dent_count_est: rint(0, 10), drivable: null,
             roof_tiles_broken: rint(3, 20), water_ingress: false };
  }
  if (sev === 'MODERATE') {
    return { glass_shattered: chance(0.5), roof_deformed: chance(0.3),
             dent_count_est: rint(0, 40), drivable: null,
             roof_tiles_broken: rint(20, 80), water_ingress: chance(0.5) };
  }
  return { glass_shattered: true, roof_deformed: true,
           dent_count_est: rint(10, 60), drivable: null,
           roof_tiles_broken: rint(80, 200), water_ingress: true };
}

// ---- photos ------------------------------------------------------
const PHOTOS_PER_CHANNEL = { APP: [1, 4], WORKSHOP_PORTAL: [2, 6],
  AGENCY_EMAIL: [1, 3], DRIVE_IN_SCANNER: [0, 2], VOICE_AGENT: [0, 0] };
function photos(i, channel, loc, dents, receivedAt) {
  const range = PHOTOS_PER_CHANNEL[channel];
  // pattern A claims always carry three photos (the EXIF evidence)
  const n = isPatternA(i) ? 3 : rint(range[0], range[1]);
  const out = [];
  for (let k = 1; k <= n; k++) {
    let exif;
    if (isPatternA(i)) {
      // 6-9 days BEFORE the cell: 2026-07-09 .. 2026-07-12
      exif = at(utc('2026-07-09T00:00:00Z'),
                ((i - 8101) % 4) * DAY + rint(8 * 60, 20 * 60) * MIN
                + (k - 1) * rint(1, 4) * MIN);
    } else {
      // taken after the cell hit, before the report
      exif = at(receivedAt, -rint(3, 180) * MIN);
      const floor = at(CELL_START, 2 * MIN);
      if (exif.getTime() < floor.getTime()) exif = floor;
    }
    out.push({
      photo_id: 'PH-' + pad5(i) + '-' + k,
      exif_taken_at: exif,
      gps: { lat: Math.round((loc.lat + (rand() - 0.5) * 0.002) * 10000) / 10000,
             lon: Math.round((loc.lon + (rand() - 0.5) * 0.003) * 10000) / 10000 },
      dent_count_est: Math.max(0, Math.round(dents / n) + rint(-2, 2)),
      image_hash: hex(16),
    });
  }
  return out;
}

// ---- narratives --------------------------------------------------
function fill(tpl, v) {
  return tpl.replace(/\{(\w+)\}/g, (m, key) => (key in v ? v[key] : m));
}
const PANEL_SETS = ['roof and bonnet', 'roof, bonnet and boot lid',
  'bonnet and both front wings', 'roof, bonnet and left side',
  'roof, boot lid and right side', 'all upper panels'];

const NARR = {
  APP_MINOR: [
    'Hail on my {model} last Saturday evening in {city}, about {n} small dents on roof and bonnet. Car drives fine.',
    'Found roughly {n} dents on the roof and boot lid of my {model} after the storm ({city}, {plz}). No glass damage.',
    'Hail damage {city}: {n} dents, mostly on the bonnet of my {model}. Car was parked in the street, no garage.',
  ],
  APP_MINOR_GLASS: [
    'Windscreen cracked by hail on my {model} in {city}, only a couple of small dents otherwise.',
    'Rear window shattered during the hail in {city}. {model}, hardly any dents on the body.',
  ],
  APP_MODERATE: [
    'Massive hail on Saturday in {city}. My {model} has around {n} dents on {panels}{glass}. {drive}',
    'Car ({model}) was parked outside in {city} during the storm, counted about {n} dents so far{glass}. Need a repair appointment.',
    'Hail damage all over my {model}: {panels}, about {n} dents{glass}. Photos attached. {drive}',
  ],
  APP_SEVERE: [
    'Severe hail damage in {city}: my {model} has {n}+ dents, {roof}{glass}. {drive}',
    'My {model} looks like a golf ball after the storm in {city}: about {n} dents, {roof}{glass}. {drive}',
  ],
  VOICE_SUMMARY: [
    'Voice agent summary: caller reports about {n} dents on a {model} parked in {city} ({plz}){glass}; {roof}; vehicle {drive_v}. Call-back requested.',
    'Voice agent summary: hail damage reported for a {model}, {city} {plz}, approx. {n} dents{glass}; {roof}; vehicle {drive_v}.',
  ],
  VOICE_OPENING: [
    'My car got hit by the hail on Saturday evening.',
    'I need to report hail damage on my car.',
    'Hello, the hail storm on Saturday wrecked my car.',
    'I am calling about the hail in {city}, my car is damaged.',
  ],
  VOICE_DETAIL: [
    'It was in the street in {city}, I count about {n} dents on {panels}{glass_sp}. {drive_sp}',
    'Outside our house in {city}, no garage. Roughly {n} dents{glass_sp}, {roof_sp}. {drive_sp}',
    'On the supermarket car park in {city}. Maybe {n} dents, {roof_sp}{glass_sp}. {drive_sp}',
  ],
  VOICE_CLOSING: [
    'A drive-in appointment proposal will follow by SMS.',
    'Please upload photos in the app when you can.',
    'An adjuster will contact you within two working days.',
    'You will receive a confirmation by SMS in a few minutes.',
  ],
  WORKSHOP: [
    'Workshop intake by {partner}: {model}, about {n} hail dents on {panels}{glass}. Estimate attached, customer requests partner repair.',
    '{partner} reports a hail-damaged {model} brought in by the customer: {n} dents on {panels}{glass}. Estimate attached.',
  ],
  DRIVE_IN: [
    'Drive-in intake at {partner}: customer states about {n} dents on a {model}{glass}; scanner run booked.',
    'Drive-in intake at {partner}: {model} from {city}, customer estimate {n} dents{glass}; scanner run booked.',
  ],
  EMAIL: [
    'Agency {agency} forwards a customer notice: {model} damaged by hail on 18 July in {city} ({plz}), approx. {n} dents{glass}. Customer asks for a partner-workshop appointment.',
    '{agency} forwards an email from the policy holder: hail damage on a {model} parked in {city}, about {n} dents{glass}. {drive}',
  ],
  PROP_MINOR: [
    'Hail broke about {tiles} roof tiles on our {building} in {city}; no water ingress so far.',
    'A few roof tiles ({tiles}) and the garden-shed skylight broken by hail in {city}, {building}.',
  ],
  PROP_MODERATE: [
    'Hail damaged the roof of our {building} in {city}: about {tiles} broken tiles{sky}{water}.',
    '{building} in {city} ({plz}): roughly {tiles} roof tiles broken, rolling shutters dented{sky}{water}.',
  ],
  PROP_SEVERE: [
    'Roof of the {building} in {city} heavily damaged: {tiles}+ tiles gone, skylights shattered, water ingress into two rooms; emergency tarpaulin needed.',
    'Severe hail damage to our {building} in {city} ({plz}): roof partly stripped ({tiles} tiles), all skylights broken, attic flooded.',
  ],
  PROP_VOICE_DETAIL: [
    'It is our {building} in {city}. About {tiles} roof tiles are broken{sky_sp}{water_sp}.',
    'The {building} in {city}, the roof took the worst of it, roughly {tiles} tiles{sky_sp}{water_sp}.',
  ],
};
const BUILDINGS = ['detached house', 'semi-detached house', 'terraced house',
  'apartment building', 'farmhouse'];
const ROOF_TYPES = ['CLAY_TILES', 'CONCRETE_TILES', 'METAL_SHEET', 'FLAT_BITUMEN'];

function motorVars(doc) {
  const d = doc.damage_signals;
  return {
    model: doc.vehicle.model, city: doc.location.city,
    plz: doc.location.postal_code, n: d.dent_count_est,
    panels: pick(PANEL_SETS),
    glass: d.glass_shattered ? ', windscreen shattered' : '',
    glass_sp: d.glass_shattered ? ' and the windscreen is shattered' : '',
    roof: d.roof_deformed ? 'roof pushed in' : 'roof intact',
    roof_sp: d.roof_deformed ? 'the roof is pushed in' : 'the roof is okay',
    drive: d.drivable ? 'Car still drives.' : 'Car cannot be driven.',
    drive_v: d.drivable ? 'still drivable' : 'not drivable',
    drive_sp: d.drivable ? 'I can still drive it.' : 'It cannot be driven.',
  };
}
function voiceTranscript(doc, v) {
  return 'Agent: Acme Insurance claims line, this is the voice assistant. How can I help you?\n'
    + 'Caller: ' + fill(pick(NARR.VOICE_OPENING), v) + '\n'
    + 'Agent: I am sorry to hear that. Where was the vehicle parked and how bad is the damage?\n'
    + 'Caller: ' + fill(pick(NARR.VOICE_DETAIL), v) + '\n'
    + 'Agent: Thank you. I have opened claim ' + doc.claim_id + ' for your '
    + v.model + '. ' + pick(NARR.VOICE_CLOSING);
}
function propertyVoiceTranscript(doc, v) {
  return 'Agent: Acme Insurance claims line, this is the voice assistant. How can I help you?\n'
    + 'Caller: The hail on Saturday damaged our roof in ' + v.city + '.\n'
    + 'Agent: I am sorry to hear that. Which building and how bad is the damage?\n'
    + 'Caller: ' + fill(pick(NARR.PROP_VOICE_DETAIL), v) + '\n'
    + 'Agent: Thank you. I have opened claim ' + doc.claim_id
    + ' for your property. A roofer from the partner network will call you within two working days.';
}

// Workshop estimate texts: unique per claim outside pattern C (so the
// only identical texts are the nine W-0471 anchors).
const LINE_ITEM_C = 'PDR roof + bonnet, 62 dents, blend A-pillars, polish complete';
const LINE_ITEMS_C_TAIL = [
  'PDR roof + boot lid, 58 dents, blend C-pillars, polish complete',
  'PDR bonnet + both wings, 71 dents, replace bonnet, polish complete',
  'PDR roof, 49 dents, blend A-pillars, headliner removal',
  'Conventional repair roof + bonnet, 84 dents, full respray roof',
  'PDR roof + bonnet + boot lid, 66 dents, blend both A-pillars',
  'PDR all upper panels, 93 dents, replace roof skin, polish complete',
  'PDR bonnet + left side, 55 dents, blend A-pillar, polish complete',
  'PDR roof + right side, 61 dents, blend C-pillar, polish complete',
];
const USED_TEXTS = new Set([LINE_ITEM_C].concat(LINE_ITEMS_C_TAIL));
const METHODS = ['PDR', 'PDR + push-to-paint', 'Conventional repair'];
function workshopText(d, panels) {
  let hours = Math.round((d.dent_count_est * 0.12 + rint(0, 4) * 0.5) * 2) / 2;
  const method = pick(METHODS);
  const glass = d.glass_shattered ? ', windscreen replacement' : '';
  let text;
  for (;;) {
    text = method + ' ' + panels + ', ' + d.dent_count_est + ' dents, '
      + hours.toFixed(1) + ' h' + glass;
    if (!USED_TEXTS.has(text)) break;
    hours += 0.5;
  }
  USED_TEXTS.add(text);
  return text;
}

// ---- document builders -------------------------------------------
// Fast Lane sample anchor: every field fixed by the MINOR_SAMPLE
// contract (no PRNG draw at all).
function sampleDoc(i) {
  const r = SAMPLE_BY_ID[i];
  const texts = sampleTexts(r);
  const doc = {
    _id: 'FNOL-0913-' + pad5(i),
    claim_id: claimId(i),
    event_id: 'HZ-0913',
    line: 'MOTOR',
    channel: r.channel,
    received_at: r.received_at,
    customer_ref: customerRef(i),
    vehicle: vehicle(i, r.model),
    location: r.location,
    narrative: texts.narrative,
    photos: samplePhotos(r),
    damage_signals: { glass_shattered: false, roof_deformed: false,
                      dent_count_est: r.dents, drivable: true },
    severity_est: 'MINOR',
    is_repeat_contact: false,
    complaint_flag: false,
  };
  if (texts.voice_transcript) doc.voice_transcript = texts.voice_transcript;
  return doc;
}

function motorDoc(i) {
  const channel = channelOf[i], sev = severityOf[i];
  const loc = location();
  const veh = vehicle(i);
  if (isPatternBDup(i)) {
    // same vehicle and customer as the APP primary 100 ids earlier
    const primary = fnol[i - 101];
    veh.vin = primary.vehicle.vin;
    veh.model = primary.vehicle.model;
  } else if (!isCohort(i) && chance(0.05)) {
    veh.garage_parking = true;   // caught on the road
  }
  const doc = {
    _id: 'FNOL-0913-' + pad5(i),
    claim_id: claimId(i),
    event_id: 'HZ-0913',
    line: 'MOTOR',
    channel: channel,
    received_at: receivedAtOf[i],
    customer_ref: isPatternBDup(i) ? fnol[i - 101].customer_ref : customerRef(i),
    vehicle: veh,
    location: loc,
    narrative: '',
    photos: [],
    damage_signals: motorDamage(i, sev, channel),
    severity_est: sev,
    is_repeat_contact: false,
    complaint_flag: false,
  };
  const d = doc.damage_signals;
  doc.photos = photos(i, channel, loc, d.dent_count_est, doc.received_at);
  const v = motorVars(doc);
  if (channel === 'APP') {
    const key = sev === 'MINOR' ? (d.glass_shattered ? 'APP_MINOR_GLASS' : 'APP_MINOR')
      : 'APP_' + sev;
    doc.narrative = fill(pick(NARR[key]), v);
  } else if (channel === 'VOICE_AGENT') {
    doc.narrative = fill(pick(NARR.VOICE_SUMMARY), v);
    doc.voice_transcript = voiceTranscript(doc, v);
  } else if (channel === 'WORKSHOP_PORTAL') {
    const shop = isPatternC(i) ? BODY_SHOPS[2] : pick(BODY_SHOPS);
    v.partner = shop[1] + (shop[2] ? ' (' + shop[2] + ')' : '');
    doc.narrative = fill(pick(NARR.WORKSHOP), v);
    doc.workshop_partner_id = shop[0];
    if (shop[2]) doc.workshop_id = shop[2];
    if (isPatternC(i)) {
      const k = i - 8400;
      doc.workshop_estimate_text = k <= 9 ? LINE_ITEM_C : LINE_ITEMS_C_TAIL[k - 10];
    } else {
      doc.workshop_estimate_text = workshopText(d, v.panels);
    }
  } else if (channel === 'DRIVE_IN_SCANNER') {
    const di = (i === 8103) ? DRIVE_INS[0] : weightedPick(DRIVE_INS);
    v.partner = di[1];
    doc.drive_in_partner_id = di[0];
    if (i === 8103) {
      doc.narrative = 'Drive-in intake at Braendle Drive-In Hail Center: customer states about 60 dents on roof and bonnet of a '
        + v.model + ', photos uploaded via the app beforehand; scanner run booked.';
    } else {
      doc.narrative = fill(pick(NARR.DRIVE_IN), v);
    }
  } else {
    v.agency = pick(AGENCIES);
    doc.narrative = fill(pick(NARR.EMAIL), v);
  }
  return doc;
}

function propertyDoc(i) {
  const channel = channelOf[i], sev = severityOf[i];
  const loc = location();
  const dmg = propertyDamage(sev);
  const doc = {
    _id: 'FNOL-0913-' + pad5(i),
    claim_id: claimId(i),
    event_id: 'HZ-0913',
    line: 'PROPERTY',
    channel: channel,
    received_at: receivedAtOf[i],
    customer_ref: customerRef(i),
    vehicle: null,
    property: { building_type: pick(BUILDINGS).toUpperCase().replace(/ /g, '_'),
                roof_type: pick(ROOF_TYPES), skylights: rint(0, 4) },
    location: loc,
    narrative: '',
    photos: [],
    damage_signals: dmg,
    severity_est: sev,
    is_repeat_contact: false,
    complaint_flag: false,
  };
  doc.photos = photos(i, channel, loc, dmg.dent_count_est, doc.received_at);
  const v = {
    building: doc.property.building_type.toLowerCase().replace(/_/g, ' '),
    city: loc.city, plz: loc.postal_code, tiles: dmg.roof_tiles_broken,
    sky: dmg.glass_shattered ? ', one skylight shattered' : '',
    sky_sp: dmg.glass_shattered ? ' and a skylight is shattered' : '',
    water: dmg.water_ingress ? ', some water in the attic' : '',
    water_sp: dmg.water_ingress ? ', water is coming in' : '',
  };
  const text = fill(pick(NARR['PROP_' + sev]), v);
  if (channel === 'VOICE_AGENT') {
    doc.narrative = 'Voice agent summary: ' + text;
    doc.voice_transcript = propertyVoiceTranscript(doc, v);
  } else if (channel === 'AGENCY_EMAIL') {
    doc.narrative = 'Agency ' + pick(AGENCIES) + ' forwards a customer notice: ' + text;
  } else {
    doc.narrative = text;
  }
  return doc;
}

// ---- generate fnol_intake ----------------------------------------
const fnol = [];
for (let i = 1; i <= N_CLAIMS; i++) {
  fnol.push(isSampleAnchor(i) ? sampleDoc(i)
            : isMotor(i) ? motorDoc(i) : propertyDoc(i));
}

// Second-call documents for cohort 06001..06063 (Mon 07:00-09:45),
// formal complaint on 06001..06004.
const REPEAT_EXTRA = [
  'Nobody called me back.',
  'The app just says waiting for workshop slot.',
  'My car is not even drivable, why a drive-in?',
  'I have the repair-network clause, you promised a partner slot.',
  'I need the car for work, I cannot wait another week.',
];
const REPEAT_CLOSING = [
  'I have flagged your claim for a call-back by the claims team today.',
  'The claims team has been notified of your second call.',
];
const REPEAT_REACTION = [
  'This is the second time I am calling, please hurry.',
  'Fine, but I expect a call today.',
  'Please do, I have been waiting since Sunday morning.',
];
const MON_0700 = utc('2026-07-20T07:00:00Z');
for (let k = 1; k <= 63; k++) {
  const i = 6000 + k;
  const p = fnol[i - 1];
  const complaint = k <= 4;
  const reaction = complaint
    ? 'I want to file a formal complaint about this. Please note it on the claim.'
    : pick(REPEAT_REACTION);
  const extra = pick(REPEAT_EXTRA);
  fnol.push({
    _id: 'FNOL-0913-' + pad5(i) + '-R',
    claim_id: p.claim_id,
    event_id: 'HZ-0913',
    line: 'MOTOR',
    channel: 'VOICE_AGENT',
    received_at: at(MON_0700, Math.round((k - 1) * 2.6 * MIN)),
    first_contact_at: p.received_at,
    customer_ref: p.customer_ref,
    vehicle: p.vehicle,
    location: p.location,
    narrative: 'Second call on claim ' + p.claim_id + ': customer chases the workshop slot at Braendle Drive-In Hail Center'
      + (complaint ? ' and files a formal complaint.' : '.') + ' ' + extra,
    photos: [],
    damage_signals: p.damage_signals,
    severity_est: p.severity_est,
    is_repeat_contact: true,
    complaint_flag: complaint,
    voice_transcript:
      'Agent: Acme Insurance claims line, this is the voice assistant. How can I help you?\n'
      + 'Caller: I already reported my hail damage on the weekend, claim ' + p.claim_id
      + ', and I still have no workshop appointment. ' + extra + '\n'
      + 'Agent: I can see the claim; it is waiting for a slot at Braendle Drive-In Hail Center. '
      + pick(REPEAT_CLOSING) + '\n'
      + 'Caller: ' + reaction,
  });
}

// ---- scanner_results: one per DRIVE_IN_SCANNER claim -------------
const PANELS = ['roof', 'bonnet', 'boot_lid', 'left_wing', 'right_wing',
  'left_doors', 'right_doors', 'tailgate'];
const scans = [];
for (let i = 1; i <= N_MOTOR; i++) {
  if (channelOf[i] !== 'DRIVE_IN_SCANNER') continue;
  const doc = fnol[i - 1];
  const claimed = doc.damage_signals.dent_count_est;
  const partnerId = doc.drive_in_partner_id;
  if (i === 8103) {
    scans.push({
      _id: 'SCAN-0913-' + pad5(i),
      claim_id: doc.claim_id, event_id: 'HZ-0913', partner_id: 'P-BRAENDLE',
      scanned_at: utc('2026-07-20T09:35:00Z'),
      dent_count_claimed: 60, dent_count_scanned: 14,
      panels: ['roof', 'bonnet'],
      estimate_eur: 6800, scanner_estimate_eur: 1190,
      mismatch_flag: true, mismatch_ratio: 0.77,
      note: 'Customer claimed about 60 dents, scanner counted 14; workshop estimate on file EUR 6,800.',
    });
    continue;
  }
  const scanned = claimed < 10 ? claimed
    : Math.round(claimed * (0.85 + rand() * 0.3));
  const nPanels = Math.min(PANELS.length, Math.max(1, Math.ceil(scanned / 30)));
  const panels = shuffle(PANELS.slice()).slice(0, nPanels).sort();
  const estimate = round10(scanned * rint(75, 110)
    + (doc.damage_signals.glass_shattered ? 850 : 0));
  // scanned a few minutes after the drive-in intake, never after
  // the demo's "now"
  const scannedAt = new Date(Math.min(
    at(doc.received_at, rint(5, 25) * MIN).getTime(), at(NOW, -2 * MIN).getTime()));
  scans.push({
    _id: 'SCAN-0913-' + pad5(i),
    claim_id: doc.claim_id, event_id: 'HZ-0913', partner_id: partnerId,
    scanned_at: scannedAt,
    dent_count_claimed: claimed, dent_count_scanned: scanned,
    panels: panels,
    estimate_eur: estimate,
    mismatch_flag: claimed > 0 && Math.abs(scanned - claimed) / claimed > 0.5,
  });
}

// ---- weather_cells -----------------------------------------------
const cells = [
  {
    _id: 'HZ-0913', cell_id: 'HZ-0913', status: 'OBSERVED', kind: 'hail',
    hail_size_cm: 3.5, warning_level: 3,
    start: CELL_START, end: CELL_END,
    district: 'BOEBLINGEN', postal_codes: BB_POSTAL, cities: BB_CITIES,
    track: { type: 'Polygon', coordinates: [[
      [8.80, 48.55], [9.16, 48.72], [9.10, 48.86], [8.74, 48.69], [8.80, 48.55]]] },
    exposure_motor_policies: 31600,
    exposure_vehicles_no_garage: 15800,
    exposure_property: 1900,
    source: 'Acme weather feed (radar composite)',
    observed_at: utc('2026-07-18T19:30:00Z'),
  },
  {
    _id: 'HZ-0914', cell_id: 'HZ-0914', status: 'FORECAST', kind: 'hail',
    hail_size_cm_forecast: 3.0, warning_level: 3, probability: 0.7,
    start: utc('2026-07-21T16:00:00Z'), end: utc('2026-07-21T19:00:00Z'),
    window_start: utc('2026-07-21T16:00:00Z'), window_end: utc('2026-07-21T19:00:00Z'),
    forecast_issued_at: utc('2026-07-20T06:00:00Z'),
    district: 'LUDWIGSBURG', postal_codes: LB_POSTAL, cities: LB_CITIES,
    track: { type: 'Polygon', coordinates: [[
      [9.05, 48.80], [9.35, 48.86], [9.32, 49.02], [9.02, 48.96], [9.05, 48.80]]] },
    exposure_motor_policies: 17400,
    exposure_vehicles_no_garage: 8900,
    exposure_property: 2300,
    source: 'Acme weather feed (convective forecast)',
  },
  {
    _id: 'HZ-0907', cell_id: 'HZ-0907', status: 'OBSERVED', kind: 'hail',
    hail_size_cm: 2.0, warning_level: 2,
    start: utc('2026-07-04T15:10:00Z'), end: utc('2026-07-04T15:40:00Z'),
    district: 'LUDWIGSBURG',
    postal_codes: ['71634', '71636', '71638', '71640', '71642', '71672'],
    cities: ['Ludwigsburg', 'Kornwestheim', 'Marbach'],
    track: { type: 'Polygon', coordinates: [[
      [9.15, 48.86], [9.28, 48.88], [9.26, 48.95], [9.13, 48.93], [9.15, 48.86]]] },
    exposure_motor_policies: 8200,
    exposure_vehicles_no_garage: 4400,
    exposure_property: 900,
    claims: 1240,
    claims_property: 60,
    conversion: 0.28,
    source: 'Acme weather feed (radar composite)',
    observed_at: utc('2026-07-04T15:50:00Z'),
    note: 'Small 2 cm cell; basis of the NatCat playbook planning assumption (0.30).',
  },
];

// ---- insert in batches of 1,000 ----------------------------------
function insertBatches(coll, docs) {
  for (let s = 0; s < docs.length; s += 1000) {
    coll.insertMany(docs.slice(s, s + 1000));
  }
}
insertBatches(db.fnol_intake, fnol);
insertBatches(db.scanner_results, scans);
db.weather_cells.insertMany(cells);

// ---- counts ------------------------------------------------------
const byChannel = {};
const bySeverity = {};
for (let i = 1; i <= N_CLAIMS; i++) {
  byChannel[channelOf[i]] = (byChannel[channelOf[i]] || 0) + 1;
  bySeverity[severityOf[i]] = (bySeverity[severityOf[i]] || 0) + 1;
}
print('Claims seed complete in ' + Math.round((Date.now() - t0) / 100) / 10 + ' s: '
  + db.fnol_intake.countDocuments({}) + ' fnol_intake docs ('
  + db.fnol_intake.countDocuments({ is_repeat_contact: false }) + ' claims + '
  + db.fnol_intake.countDocuments({ is_repeat_contact: true }) + ' repeat contacts), '
  + db.scanner_results.countDocuments({}) + ' scanner_results docs, '
  + db.weather_cells.countDocuments({}) + ' weather_cells docs');
print('  channels:   ' + JSON.stringify(byChannel));
print('  severities: ' + JSON.stringify(bySeverity));
