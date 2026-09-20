// Seed 2/2 for the acme_claims MongoDB store: the story anchor
// documents, re-asserted EXACTLY as the demo storyline demands,
// plus indexes and a count report. Runs after 01-init.js (same
// initdb mechanism, alphabetical order). Every write is an upsert
// / $set, so the file is idempotent and also repairs a store whose
// generator output drifted. Numbers and ids below are the demo
// contract (see 01-init.js header and the README storyline):
//
//   Fast Lane sample 00001..00008   the eight MINOR claims the
//                                  cockpit publishes: channel,
//                                  intake time, place, vehicle and
//                                  customer fixed (MINOR_SAMPLE),
//                                  5-25 dents, no glass, drivable
//   cohort CLM-0913-06001..06412   stalled at P-BRAENDLE
//     06001..06158                 total-loss signature (glass
//                                  shattered + roof deformed +
//                                  dents 160..240), SEVERE
//     06159..06412                 MODERATE, NO total-loss signature
//     06001..06063                 second VOICE_AGENT call Monday
//                                  07:00-09:45 (is_repeat_contact)
//     06001..06004                 formal complaint (complaint_flag
//                                  on the second-call document)
//   pattern A 08101..08119          photo EXIF 2026-07-09..07-12,
//                                  6-9 days BEFORE the cell; 08103
//                                  = DRIVE_IN_SCANNER, "about 60
//                                  dents", dent_count_est 60
//   pattern B 08201..08211 (APP) <-> 08301..08311 (VOICE_AGENT)
//                                  same VIN / model / customer,
//                                  dents +20..40, 13-29 h apart
//   pattern C 08401..08417          workshop_estimate_text from
//                                  W-0471; 08401..08409 identical
//   scanner_results CLM-0913-08103 claimed 60 / scanned 14 /
//                                  mismatch_flag true
//   weather_cells                  HZ-0913 15,800 no-garage
//                                  vehicles; HZ-0914 8,900 + 2,300
//                                  property; HZ-0907 1,240 claims /
//                                  4,400 exposure / 0.28

db = db.getSiblingDB('acme_claims');
const F = db.fnol_intake, S = db.scanner_results, W = db.weather_cells;

// ---- helpers (no PRNG here: anchors are explicit formulas) --------
const MIN = 60000, HOUR = 60 * MIN, DAY = 24 * HOUR;
function utc(s) { return new Date(s); }
function at(d, ms) { return new Date(d.getTime() + ms); }
function pad5(i) { return String(i).padStart(5, '0'); }
function claimId(i) { return 'CLM-0913-' + pad5(i); }
function fnolId(i) { return 'FNOL-0913-' + pad5(i); }
function fakeHash(s) {
  // FNV-1a twice -> 16 hex chars, deterministic
  let h1 = 0x811c9dc5, h2 = 0x01000193;
  for (const ch of s) {
    h1 = Math.imul(h1 ^ ch.charCodeAt(0), 0x01000193) >>> 0;
    h2 = Math.imul(h2 ^ ch.charCodeAt(0), 0x811c9dc5) >>> 0;
  }
  return h1.toString(16).padStart(8, '0') + h2.toString(16).padStart(8, '0');
}
const CELL_START = utc('2026-07-18T18:40:00Z');
const CELL_END   = utc('2026-07-18T19:25:00Z');
const SINDELFINGEN = { postal_code: '71063', city: 'Sindelfingen',
  district: 'BOEBLINGEN', lat: 48.7134, lon: 9.0030 };

// Skeleton for an anchor that 01-init.js did not create (should
// never happen; keeps the upserts self-sufficient).
function skeleton(i, channel) {
  return {
    _id: fnolId(i), claim_id: claimId(i), event_id: 'HZ-0913', line: 'MOTOR',
    channel: channel, received_at: utc('2026-07-19T09:00:00Z'),
    customer_ref: 'CUST-' + String(100000 + ((i * 6007) % 52000)),
    vehicle: { vin: 'WVWZZZ1KZRW' + String((i * 7919 + 100003) % 1000000).padStart(6, '0'),
               model: 'VW Golf', garage_parking: false },
    location: SINDELFINGEN, narrative: '', photos: [],
    damage_signals: { glass_shattered: false, roof_deformed: false,
                      dent_count_est: 40, drivable: true },
    severity_est: 'MODERATE', is_repeat_contact: false, complaint_flag: false,
  };
}
function primaryFilter(i) { return { claim_id: claimId(i), is_repeat_contact: false }; }
function setPrimary(i, channel, set) {
  const base = skeleton(i, channel);
  const setOnInsert = {};
  // a $setOnInsert key must not be a prefix of a dotted $set path
  // ('damage_signals' vs 'damage_signals.dent_count_est')
  const setKeys = Object.keys(set);
  for (const k in base) {
    if (setKeys.some(s => s === k || s.startsWith(k + '.'))) continue;
    setOnInsert[k] = base[k];
  }
  F.updateOne(primaryFilter(i), { $set: set, $setOnInsert: setOnInsert },
              { upsert: true });
}
function primary(i) { return F.findOne(primaryFilter(i)); }

// ---- Fast Lane sample anchors CLM-0913-00001..00008 --------------
// Cross-store contract with acme_insurance (ins_claims /
// ins_policies / ins_customers) and cockpit/index.html; the table
// and the text builders are identical to 01-init.js, so this pass
// is a pure re-assert on a fresh store. Postgres estimates for the
// record: 640 / 420 / 890 / 310 / 760 / 540 / 950 / 180 EUR.
// Columns: c, channel, received_at, postal_code, city, lat, lon,
// model, dents, customer, panels, agency (AGENCY_EMAIL only).
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
// VIN = WMI + 'ZZZ' + model code + 'ZRW' + serial, as in 01-init.js
const SAMPLE_VIN_PREFIX = {
  'VW Golf': 'WVWZZZ1K', 'Skoda Octavia': 'TMBZZZNX', 'BMW 3 Series': 'WBAZZZ3A',
  'Opel Corsa': 'W0VZZZSD', 'Audi A4': 'WAUZZZ8W', 'Ford Focus': 'WF0ZZZKX',
  'Toyota Yaris': 'SB1ZZZKF', 'Fiat 500': 'ZFAZZZ31',
};
function sampleVin(r) {
  return SAMPLE_VIN_PREFIX[r.model] + 'ZRW'
    + String((r.c * 7919 + 100003) % 1000000).padStart(6, '0');
}
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

// ---- 1. Fast Lane sample 00001..00008: the cockpit's claims ------
for (const r of MINOR_SAMPLE) {
  const texts = sampleTexts(r);
  const set = {
    channel: r.channel, received_at: r.received_at, line: 'MOTOR', event_id: 'HZ-0913',
    'vehicle.vin': sampleVin(r), 'vehicle.model': r.model,
    'vehicle.garage_parking': false,
    location: r.location,
    narrative: texts.narrative,
    photos: samplePhotos(r),
    damage_signals: { glass_shattered: false, roof_deformed: false,
                      dent_count_est: r.dents, drivable: true },
    severity_est: 'MINOR', complaint_flag: false,
  };
  // no workshop / drive-in fields on these channels; the transcript
  // only on the voice channel
  const unset = { workshop_partner_id: '', workshop_id: '',
                  workshop_estimate_text: '', drive_in_partner_id: '' };
  if (texts.voice_transcript) set.voice_transcript = texts.voice_transcript;
  else unset.voice_transcript = '';
  setPrimary(r.c, r.channel, set);
  F.updateOne(primaryFilter(r.c), { $unset: unset });
}
// the whole Fast Lane sample is MINOR
const sampleIds = [];
for (let i = 1; i <= 40; i++) sampleIds.push(claimId(i));
F.updateMany({ claim_id: { $in: sampleIds }, is_repeat_contact: false },
             { $set: { severity_est: 'MINOR', line: 'MOTOR', event_id: 'HZ-0913' } });

// ---- 2. stalled cohort: total-loss signature 06001..06158 --------
function tlDents(k) { return 160 + ((k * 37) % 81); }   // 160..240
for (let k = 1; k <= 158; k++) {
  const i = 6000 + k;
  setPrimary(i, 'APP', {
    'damage_signals.glass_shattered': true,
    'damage_signals.roof_deformed': true,
    'damage_signals.dent_count_est': tlDents(k),
    'damage_signals.drivable': false,
    severity_est: 'SEVERE',
    line: 'MOTOR',
    event_id: 'HZ-0913',
  });
}
// 06159..06412: MODERATE and never the full signature
const restCohort = [];
for (let i = 6159; i <= 6412; i++) restCohort.push(claimId(i));
F.updateMany({ claim_id: { $in: restCohort }, is_repeat_contact: false },
             { $set: { severity_est: 'MODERATE', line: 'MOTOR', event_id: 'HZ-0913' } });
F.updateMany({ claim_id: { $in: restCohort }, is_repeat_contact: false,
               'damage_signals.dent_count_est': { $gt: 150 } },
             { $set: { 'damage_signals.dent_count_est': 120 } });

// ---- 3. second calls 06001..06063, complaints 06001..06004 -------
const REPEAT_EXTRA = [
  'Nobody called me back.',
  'The app just says waiting for workshop slot.',
  'My car is not even drivable, why a drive-in?',
  'I have the repair-network clause, you promised a partner slot.',
  'I need the car for work, I cannot wait another week.',
];
const MON_0700 = utc('2026-07-20T07:00:00Z');
for (let k = 1; k <= 63; k++) {
  const i = 6000 + k;
  const p = primary(i) || skeleton(i, 'APP');
  const complaint = k <= 4;
  const extra = REPEAT_EXTRA[k % REPEAT_EXTRA.length];
  const reaction = complaint
    ? 'I want to file a formal complaint about this. Please note it on the claim.'
    : (k % 2 ? 'This is the second time I am calling, please hurry.'
             : 'Fine, but I expect a call today.');
  F.replaceOne({ _id: fnolId(i) + '-R' }, {
    _id: fnolId(i) + '-R',
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
      + 'I have flagged your claim for a call-back by the claims team today.\n'
      + 'Caller: ' + reaction,
  }, { upsert: true });
}
// only the four second-call documents carry the complaint flag
F.updateMany({ is_repeat_contact: true, claim_id: { $nin: [claimId(6001), claimId(6002),
               claimId(6003), claimId(6004)] } }, { $set: { complaint_flag: false } });

// ---- 4. pattern A: EXIF 6-9 days before the cell -----------------
for (let k = 1; k <= 19; k++) {
  const i = 8100 + k;
  const p = primary(i);
  const loc = (p && p.location) || SINDELFINGEN;
  const dents = (i === 8103) ? 60 : ((p && p.damage_signals.dent_count_est) || 45);
  const photos = [];
  for (let n = 1; n <= 3; n++) {
    // 2026-07-09 .. 2026-07-12, daytime
    const exif = at(utc('2026-07-09T00:00:00Z'),
      ((k - 1) % 4) * DAY + (9 + ((k * 7) % 9)) * HOUR + (n - 1) * 3 * MIN);
    photos.push({
      photo_id: 'PH-' + pad5(i) + '-' + n,
      exif_taken_at: exif,
      gps: { lat: Math.round((loc.lat + (n - 2) * 0.0003) * 10000) / 10000,
             lon: Math.round((loc.lon + (n - 2) * 0.0004) * 10000) / 10000 },
      dent_count_est: Math.round(dents / 3),
      image_hash: fakeHash(claimId(i) + '/' + n),
    });
  }
  const set = { photos: photos, severity_est: 'MODERATE', line: 'MOTOR',
                event_id: 'HZ-0913', channel: (i === 8103) ? 'DRIVE_IN_SCANNER' : 'APP' };
  if (i === 8103) {
    set['damage_signals.dent_count_est'] = 60;
    set['damage_signals.glass_shattered'] = false;
    set['damage_signals.roof_deformed'] = false;
    set['damage_signals.drivable'] = true;
    set.drive_in_partner_id = 'P-BRAENDLE';
    set.received_at = utc('2026-07-20T09:20:00Z');
    set.narrative = 'Drive-in intake at Braendle Drive-In Hail Center: customer states about 60 dents on roof and bonnet of a '
      + ((p && p.vehicle && p.vehicle.model) || 'VW Golf')
      + ', photos uploaded via the app beforehand; scanner run booked.';
  }
  setPrimary(i, set.channel, set);
}

// ---- 5. pattern B: duplicate VIN pairs 082xx (APP) <-> 083xx (VOICE)
function pbDents(k) { return 30 + ((k * 7) % 41); }    // 30..70
function pbDelta(k) { return 20 + ((k * 3) % 21); }    // +20..40
const SAT_2000 = utc('2026-07-18T20:00:00Z');
for (let k = 1; k <= 11; k++) {
  const ip = 8200 + k, id = 8300 + k;
  const receivedP = at(SAT_2000, (k - 1) * 25 * MIN);
  setPrimary(ip, 'APP', {
    channel: 'APP', severity_est: 'MODERATE', line: 'MOTOR', event_id: 'HZ-0913',
    received_at: receivedP,
    'damage_signals.dent_count_est': pbDents(k),
  });
  const p = primary(ip);
  setPrimary(id, 'VOICE_AGENT', {
    channel: 'VOICE_AGENT', severity_est: 'MODERATE', line: 'MOTOR', event_id: 'HZ-0913',
    received_at: at(receivedP, 12 * HOUR + Math.round(k * 1.5 * HOUR)),
    customer_ref: p.customer_ref,
    'vehicle.vin': p.vehicle.vin,
    'vehicle.model': p.vehicle.model,
    'vehicle.garage_parking': p.vehicle.garage_parking,
    'damage_signals.dent_count_est': pbDents(k) + pbDelta(k),
    photos: [],
  });
}

// ---- 6. pattern C: W-0471 estimates, identical text 08401..08409 -
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
for (let k = 1; k <= 17; k++) {
  setPrimary(8400 + k, 'WORKSHOP_PORTAL', {
    channel: 'WORKSHOP_PORTAL', severity_est: 'MODERATE', line: 'MOTOR',
    event_id: 'HZ-0913',
    workshop_partner_id: 'P-KAROSSERIE-SCHNELL',
    workshop_id: 'W-0471',
    workshop_estimate_text: k <= 9 ? LINE_ITEM_C : LINE_ITEMS_C_TAIL[k - 10],
  });
}

// ---- 7. scanner anchor CLM-0913-08103 ----------------------------
S.replaceOne({ _id: 'SCAN-0913-08103' }, {
  _id: 'SCAN-0913-08103',
  claim_id: claimId(8103), event_id: 'HZ-0913', partner_id: 'P-BRAENDLE',
  scanned_at: utc('2026-07-20T09:35:00Z'),
  dent_count_claimed: 60, dent_count_scanned: 14,
  panels: ['roof', 'bonnet'],
  estimate_eur: 6800, scanner_estimate_eur: 1190,
  mismatch_flag: true, mismatch_ratio: 0.77,
  note: 'Customer claimed about 60 dents, scanner counted 14; workshop estimate on file EUR 6,800.',
}, { upsert: true });
// no other scan may carry the mismatch flag
S.updateMany({ _id: { $ne: 'SCAN-0913-08103' } }, { $set: { mismatch_flag: false } });
// The intake document of the scanner anchor must agree with the
// Postgres policy row (POL-003858: Skoda Octavia, Sindelfingen 71063,
// customer Ben Meier) -- the triage demo shows the policy facts and
// the intake facts side by side, so the bulk generator's random
// vehicle/location is pinned here (VIN = ins_policies.vehicle_vin).
F.updateOne({ _id: 'FNOL-0913-08103' }, { $set: {
  'vehicle.vin': 'WACAF158267BEBB51', 'vehicle.model': 'Skoda Octavia',
  'vehicle.garage_parking': false,
  location: { postal_code: '71063', city: 'Sindelfingen',
              district: 'BOEBLINGEN', lat: 48.7134, lon: 9.0030 },
  narrative: 'Drive-in intake at Braendle Drive-In Hail Center: ' +
    'customer Ben Meier states about 60 dents on roof and bonnet of ' +
    'a Skoda Octavia parked in the street in Sindelfingen (71063), ' +
    'photos uploaded via the app beforehand; scanner run booked.',
} });

// ---- 7b. per-claim intake view (claim_intake_facts) --------------
// The triage demo asks ONE question of this store: "give me every
// intake fact of claim X". Expressed as an aggregation it is a
// 900-token pipeline, and the external analyst agent pays for every
// one of those tokens on the critical path of the workflow (it cost
// about 6 s per run). As a view, the joins live in the database and
// the agent's query collapses to {"$match": {"claim_id": "..."}}.
// The cell start comes from weather_cells via event_id, so the photo
// timing is computed against the real cell, not a constant.
db.claim_intake_facts.drop();
db.createView('claim_intake_facts', 'fnol_intake', [
  { $match: { is_repeat_contact: { $ne: true } } },
  { $lookup: { from: 'weather_cells', localField: 'event_id',
      foreignField: '_id', as: 'cell' } },
  { $lookup: { from: 'scanner_results', localField: 'claim_id',
      foreignField: 'claim_id', as: 'scans' } },
  { $lookup: { from: 'fnol_intake', let: { vin: '$vehicle.vin', cid: '$claim_id' },
      pipeline: [ { $match: { $expr: { $and: [
          { $eq: ['$vehicle.vin', '$$vin'] },
          { $ne: ['$claim_id', '$$cid'] },
          { $ne: ['$is_repeat_contact', true] } ] } } },
        { $project: { _id: 0, claim_id: 1 } } ], as: 'same_vin' } },
  { $lookup: { from: 'fnol_intake', let: { cid: '$claim_id' },
      pipeline: [ { $match: { $expr: { $and: [
          { $eq: ['$claim_id', '$$cid'] },
          { $eq: ['$is_repeat_contact', true] } ] } } },
        { $project: { _id: 0, complaint_flag: 1 } } ], as: 'repeats' } },
  { $project: {
      _id: 0, claim_id: 1,
      intake_found: { $literal: true },
      channel: 1, severity_est: 1, narrative: 1,
      model: { $ifNull: ['$vehicle.model', ''] },
      dent_count_est: { $ifNull: ['$damage_signals.dent_count_est', 0] },
      glass_shattered: { $ifNull: ['$damage_signals.glass_shattered', false] },
      roof_deformed: { $ifNull: ['$damage_signals.roof_deformed', false] },
      drivable: { $ifNull: ['$damage_signals.drivable', false] },
      photo_count: { $size: { $ifNull: ['$photos', []] } },
      earliest_photo_at: { $min: '$photos.exif_taken_at' },
      cell_start: { $first: '$cell.start' },
      photos_before_cell: { $cond: [
        { $eq: [{ $size: { $ifNull: ['$photos', []] } }, 0] }, false,
        { $lt: [{ $min: '$photos.exif_taken_at' }, { $first: '$cell.start' }] } ] },
      days_before_cell: { $cond: [
        { $eq: [{ $size: { $ifNull: ['$photos', []] } }, 0] }, 0,
        { $max: [0, { $round: [{ $divide: [
          { $subtract: [{ $first: '$cell.start' }, { $min: '$photos.exif_taken_at' }] },
          86400000] }, 1] }] } ] },
      scanner_found: { $gt: [{ $size: '$scans' }, 0] },
      dent_count_scanned: { $ifNull: [{ $first: '$scans.dent_count_scanned' }, 0] },
      dent_count_claimed: { $ifNull: [{ $first: '$scans.dent_count_claimed' }, 0] },
      scanner_estimate_eur: { $ifNull: [{ $first: '$scans.scanner_estimate_eur' }, 0] },
      scanner_mismatch: { $ifNull: [{ $first: '$scans.mismatch_flag' }, false] },
      duplicate_vin_claims: '$same_vin.claim_id',
      repeat_contact: { $gt: [{ $size: '$repeats' }, 0] },
      complaint_flag: { $or: ['$complaint_flag',
        { $in: [true, '$repeats.complaint_flag'] }] } } },
]);
print('claim_intake_facts: view created');

// ---- 8. weather cells: the exposure and conversion numbers -------
W.updateOne({ _id: 'HZ-0913' }, { $set: {
  cell_id: 'HZ-0913', status: 'OBSERVED', hail_size_cm: 3.5, warning_level: 3,
  start: CELL_START, end: CELL_END, district: 'BOEBLINGEN',
  exposure_motor_policies: 31600, exposure_vehicles_no_garage: 15800,
  exposure_property: 1900,
} }, { upsert: true });
W.updateOne({ _id: 'HZ-0914' }, { $set: {
  cell_id: 'HZ-0914', status: 'FORECAST', hail_size_cm_forecast: 3.0, warning_level: 3,
  start: utc('2026-07-21T16:00:00Z'), end: utc('2026-07-21T19:00:00Z'),
  window_start: utc('2026-07-21T16:00:00Z'), window_end: utc('2026-07-21T19:00:00Z'),
  district: 'LUDWIGSBURG',
  exposure_motor_policies: 17400, exposure_vehicles_no_garage: 8900,
  exposure_property: 2300,
} }, { upsert: true });
W.updateOne({ _id: 'HZ-0907' }, { $set: {
  cell_id: 'HZ-0907', status: 'OBSERVED', hail_size_cm: 2.0, warning_level: 2,
  start: utc('2026-07-04T15:10:00Z'), end: utc('2026-07-04T15:40:00Z'),
  district: 'LUDWIGSBURG',
  exposure_vehicles_no_garage: 4400, claims: 1240, conversion: 0.28,
} }, { upsert: true });

// ---- 9. indexes --------------------------------------------------
F.createIndex({ claim_id: 1 });
F.createIndex({ event_id: 1 });
F.createIndex({ channel: 1 });
F.createIndex({ received_at: 1 });
F.createIndex({ 'vehicle.vin': 1 });
F.createIndex({ is_repeat_contact: 1, complaint_flag: 1 });
F.createIndex({ severity_est: 1 });
S.createIndex({ claim_id: 1 });
S.createIndex({ event_id: 1 });
S.createIndex({ partner_id: 1, mismatch_flag: 1 });
S.createIndex({ scanned_at: 1 });
W.createIndex({ cell_id: 1 });
W.createIndex({ district: 1, status: 1 });

// ---- 10. counts / storyline checks -------------------------------
function check(label, actual, expected) {
  const ok = (actual === expected);
  print('  ' + (ok ? 'ok  ' : 'WARN') + ' ' + label + ': ' + actual
        + (ok ? '' : ' (expected ' + expected + ')'));
  return ok;
}
function ids(lo, hi) { const a = []; for (let i = lo; i <= hi; i++) a.push(claimId(i)); return a; }
const cohortIds = ids(6001, 6412);
print('Anchor seed complete:');
check('fnol_intake documents', F.countDocuments({}), 10463);
check('claims (is_repeat_contact false)', F.countDocuments({ is_repeat_contact: false }), 10400);
check('motor claims (vehicle.vin present)',
      F.countDocuments({ is_repeat_contact: false, 'vehicle.vin': { $exists: true } }), 9650);
check('property claims', F.countDocuments({ is_repeat_contact: false, line: 'PROPERTY' }), 750);
// Fast Lane sample: the eight cockpit claims field by field, then
// the whole 00001..00040 sample as MINOR
const drifted = [];
for (const r of MINOR_SAMPLE) {
  const d = primary(r.c);
  const voice = r.channel === 'VOICE_AGENT';
  const ok = d && d.channel === r.channel && d.line === 'MOTOR'
    && d.received_at instanceof Date
    && d.received_at.getTime() === r.received_at.getTime()
    && d.location.postal_code === r.location.postal_code
    && d.location.city === r.location.city && d.location.district === 'BOEBLINGEN'
    && d.vehicle.model === r.model && d.vehicle.vin === sampleVin(r)
    && d.vehicle.garage_parking === false
    && d.severity_est === 'MINOR'
    && d.damage_signals.glass_shattered === false
    && d.damage_signals.roof_deformed === false
    && d.damage_signals.drivable === true
    && d.damage_signals.dent_count_est >= 5 && d.damage_signals.dent_count_est <= 25
    && d.photos.length === SAMPLE_PHOTOS[r.channel]
    && (voice ? typeof d.voice_transcript === 'string' : d.voice_transcript === undefined)
    && d.narrative.indexOf(r.customer) >= 0
    && d.complaint_flag === false;
  if (!ok) drifted.push(claimId(r.c));
}
check('Fast Lane sample anchors 00001..00008 (channel, time, place, vehicle, customer, MINOR)',
      8 - drifted.length, 8);
if (drifted.length) print('       drifted: ' + drifted.join(', '));
check('Fast Lane sample 00001..00040 MINOR',
      F.countDocuments({ claim_id: { $in: ids(1, 40) }, is_repeat_contact: false,
                         severity_est: 'MINOR' }), 40);
check('cohort claims', F.countDocuments({ claim_id: { $in: cohortIds }, is_repeat_contact: false }), 412);
check('cohort total-loss signature', F.countDocuments({
  claim_id: { $in: cohortIds }, is_repeat_contact: false,
  'damage_signals.glass_shattered': true, 'damage_signals.roof_deformed': true,
  'damage_signals.dent_count_est': { $gt: 150 } }), 158);
check('repeat contacts', F.countDocuments({ is_repeat_contact: true }), 63);
check('complaint flags', F.countDocuments({ complaint_flag: true }), 4);
check('claims with photo EXIF before the cell', F.aggregate([
  { $match: { is_repeat_contact: false } },
  { $unwind: '$photos' },
  { $match: { 'photos.exif_taken_at': { $lt: CELL_START } } },
  { $group: { _id: '$claim_id' } }, { $count: 'n' }]).toArray()[0].n, 19);
check('VINs reported via two channels', F.aggregate([
  { $match: { is_repeat_contact: false, 'vehicle.vin': { $exists: true } } },
  { $group: { _id: '$vehicle.vin', channels: { $addToSet: '$channel' }, n: { $sum: 1 } } },
  { $match: { n: { $gt: 1 } } }, { $count: 'n' }]).toArray()[0].n, 11);
check('identical workshop estimate texts', F.aggregate([
  { $match: { workshop_estimate_text: { $exists: true } } },
  { $group: { _id: '$workshop_estimate_text', n: { $sum: 1 } } },
  { $match: { n: { $gt: 1 } } },
  { $group: { _id: null, docs: { $sum: '$n' } } }]).toArray()[0].docs, 9);
check('scanner_results documents', S.countDocuments({}), 1040);
check('scanner mismatches', S.countDocuments({ mismatch_flag: true }), 1);
check('weather_cells documents', W.countDocuments({}), 3);
const channels = {};
F.aggregate([{ $match: { is_repeat_contact: false } },
  { $group: { _id: '$channel', n: { $sum: 1 } } }]).forEach(r => { channels[r._id] = r.n; });
check('channel APP', channels.APP, 4160);
check('channel VOICE_AGENT', channels.VOICE_AGENT, 2600);
check('channel WORKSHOP_PORTAL', channels.WORKSHOP_PORTAL, 1560);
check('channel DRIVE_IN_SCANNER', channels.DRIVE_IN_SCANNER, 1040);
check('channel AGENCY_EMAIL', channels.AGENCY_EMAIL, 1040);
const sev = {};
F.aggregate([{ $match: { is_repeat_contact: false } },
  { $group: { _id: '$severity_est', n: { $sum: 1 } } }]).forEach(r => { sev[r._id] = r.n; });
check('severity MINOR', sev.MINOR, 6200);
check('severity MODERATE', sev.MODERATE, 3600);
check('severity SEVERE', sev.SEVERE, 600);
