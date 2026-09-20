#!/usr/bin/env node
/* fire-claim.js -- publish ONE FNOL event onto the sam VPN exactly
   as the triage cockpit does (cockpit/index.html) and wait for the
   claim-triage decision on the result topics. Used by preflight.sh
   (dry fire, warms the agents) and for stopwatch rehearsals.

   usage: node tools/fire-claim.js [--claim CLM-0913-00002]
                                   [--wait 90] [--url ws://localhost:8008]
   exit codes: 0 = a decision arrived and was printed
               1 = timeout, failed workflow, broker error
               2 = usage error (unknown claim / option)

   The payload is the cockpit's (spec section 7): event_type,
   event_id, cell_start, claim_id, policy_id, severity, line,
   channel, estimate_eur, reported_at, postal_code, city,
   published_at -- published PERSISTENT on
   acmeins/claims/fnol/received/<severity lowercase>/<claim_id>.
   The result is the A2A task JSON (responseType full, spec 0.1):
   status.state completed|failed, status.message.parts[] with one
   {"kind": "data", "data": <workflow output>} part and one text
   part; metadata.duration_seconds is the workflow's own duration.
   Uses the browser build of solclientjs from ../cockpit (works in
   node; the WebSocket URL points at solace-1's web transport). */
"use strict";
const path = require("path");
const solace = require(path.join(__dirname, "..", "cockpit", "solclient.js"));

/* The anchors (postgres/sql/01-acme_insurance.sql + mongodb/seed,
   the cross-store contract). policy_id / channel / estimate / place /
   reported_at are the ins_claims + ins_policies values, so the
   policy node's lookup agrees with the event it received; 08103's
   reported_at is the drive-in intake instant the cockpit uses. */
const CLAIMS = {
  "CLM-0913-00001": {
    policy_id: "POL-104211", severity: "MINOR", channel: "APP",
    estimate_eur: 640, postal_code: "71063", city: "Sindelfingen",
    reported_at: "2026-07-18T19:12:00Z",
    note: "clean hero: Lena Hartmann, VW Golf, 16 dents, RN-3, " +
      "deductible 300 -> APPROVE / FAST_LANE at P-BRAENDLE",
  },
  "CLM-0913-00002": {
    policy_id: "POL-118902", severity: "MINOR", channel: "VOICE_AGENT",
    estimate_eur: 420, postal_code: "71032", city: "Boeblingen",
    reported_at: "2026-07-18T19:40:00Z",
    note: "dry fire: Jonas Keller, Skoda Octavia, 11 dents, no RN-3, " +
      "deductible 150 -> APPROVE / FAST_LANE (slot as an offer)",
  },
  "CLM-0913-08103": {
    policy_id: "POL-003858", severity: "MODERATE", channel: "DRIVE_IN_SCANNER",
    estimate_eur: 6800, postal_code: "71063", city: "Sindelfingen",
    reported_at: "2026-07-20T09:20:00Z",
    note: "suspicious: Ben Meier, 60 dents claimed / 14 scanned, " +
      "photos 7 days before the cell -> HOLD / SPECIAL_INVESTIGATIONS",
  },
};
/* Only CROSS-STORE anchors belong here: a claim whose Postgres row and
   Mongo intake document describe the same car. CLM-0913-08891 was
   removed for that reason -- Postgres has a Ford Focus reported via
   the app in Herrenberg, the seeded intake a Mercedes A-Class from an
   agency e-mail in Holzgerlingen, so its decision card would honestly
   report the contradiction and drop its confidence. */

/* ---------- options ---------- */
const opts = { claim: "CLM-0913-00002", wait: 90, url: "ws://localhost:8008" };
const argv = process.argv.slice(2);
for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (a === "--claim") opts.claim = argv[++i];
  else if (a === "--wait") opts.wait = Number(argv[++i]);
  else if (a === "--url") opts.url = argv[++i];
  else if (a === "-h" || a === "--help") { usage(); process.exit(0); }
  else { console.error(`unknown option: ${a}`); usage(); process.exit(2); }
}
function usage() {
  console.error("usage: node tools/fire-claim.js [--claim <id>] [--wait <s>] [--url <ws url>]");
  console.error("known claims:");
  for (const [id, c] of Object.entries(CLAIMS)) console.error(`  ${id}  ${c.note}`);
}
const anchor = CLAIMS[opts.claim];
if (!anchor) { console.error(`unknown claim: ${opts.claim}`); usage(); process.exit(2); }
if (!(opts.wait > 0)) { console.error("--wait must be a positive number of seconds"); process.exit(2); }

/* ---------- payload + topics (identical to the cockpit) ---------- */
const RESULT_SUB = "acmeins/claims/result/>";
const topic = `acmeins/claims/fnol/received/${anchor.severity.toLowerCase()}/${opts.claim}`;
const payload = {
  event_type: "fnol_received", event_id: "HZ-0913",
  cell_start: "2026-07-18T18:40:00Z",
  claim_id: opts.claim, policy_id: anchor.policy_id,
  severity: anchor.severity, line: "MOTOR", channel: anchor.channel,
  estimate_eur: anchor.estimate_eur, reported_at: anchor.reported_at,
  postal_code: anchor.postal_code, city: anchor.city,
  published_at: new Date().toISOString(),
};

/* ---------- result parsing (spec 0.1 / section 7, robust) ---------- */
function decodeBody(msg) {
  let body = msg.getBinaryAttachment();
  if (body && typeof body !== "string") body = new TextDecoder("utf-8").decode(body);
  if (!body && msg.getSdtContainer()) body = String(msg.getSdtContainer().getValue());
  return body || "";
}
function findDecision(obj, depth) {
  // depth-first search for any object with a "decision" key
  if (!obj || typeof obj !== "object" || depth > 12) return null;
  if (Object.prototype.hasOwnProperty.call(obj, "decision")) return obj;
  for (const v of Object.values(obj)) {
    const hit = findDecision(v, depth + 1);
    if (hit) return hit;
  }
  return null;
}
function parseResult(topicName, raw) {
  // -> { kind: "decision", output, meta } | { kind: "failed", error, meta }
  //    | { kind: "other", note }
  let task;
  try { task = JSON.parse(raw); } catch (e) {
    return { kind: "other", note: `not JSON (${e.message})` };
  }
  const meta = (task && task.metadata) || {};
  const state = task && task.status && task.status.state;
  const parts = (task && task.status && task.status.message &&
    task.status.message.parts) || [];
  const textPart = parts.find((p) => p && p.kind === "text" && typeof p.text === "string");
  if (topicName.endsWith("/result/error") || state === "failed") {
    return { kind: "failed", meta,
      error: meta.error || (textPart && textPart.text) || raw.slice(0, 400) };
  }
  const dataPart = parts.find((p) => p && p.kind === "data" && p.data && typeof p.data === "object");
  let output = dataPart ? dataPart.data : null;
  if (!output || !("decision" in output)) output = findDecision(task, 0);
  if (!output && textPart) {
    // last resort: a JSON object with a decision key inside the text part
    const m = textPart.text.match(/\{[\s\S]*"decision"[\s\S]*\}/);
    if (m) { try { output = JSON.parse(m[0]); } catch (e) { /* ignore */ } }
  }
  if (output && output.decision) return { kind: "decision", output, meta };
  return { kind: "other", meta,
    note: `no decision in payload (state ${state || "?"}; ` +
      `${dataPart ? "data part without decision" : "no data part"})` };
}

/* ---------- session ---------- */
const f = new solace.SolclientFactoryProperties();
f.profile = solace.SolclientFactoryProfiles.version10;
solace.SolclientFactory.init(f);
solace.SolclientFactory.setLogLevel(solace.LogLevel.WARN);
const session = solace.SolclientFactory.createSession({
  url: opts.url, vpnName: "sam", userName: "default", password: "default",
});

const tStart = Date.now();
let tFire = 0, landed = false, timer = null;
const ts = () => ((Date.now() - tStart) / 1000).toFixed(1).padStart(6) + "s";
const log = (m) => console.log(`[${ts()}] ${m}`);

function finish(code) {
  if (timer) clearTimeout(timer);
  try { session.disconnect(); } catch (e) { /* ignore */ }
  setTimeout(() => process.exit(code), 300);
}

session.on(solace.SessionEventCode.UP_NOTICE, () => {
  log(`connected ${opts.url} (vpn sam)`);
  session.subscribe(solace.SolclientFactory.createTopicDestination(RESULT_SUB),
    true, RESULT_SUB, 5000);
});
session.on(solace.SessionEventCode.SUBSCRIPTION_OK, () => {
  log(`subscribed ${RESULT_SUB}`);
  const msg = solace.SolclientFactory.createMessage();
  msg.setDestination(solace.SolclientFactory.createTopicDestination(topic));
  msg.setBinaryAttachment(JSON.stringify(payload));
  msg.setDeliveryMode(solace.MessageDeliveryModeType.PERSISTENT);
  try { session.send(msg); } catch (e) { log(`publish error: ${e.message}`); finish(1); return; }
  tFire = Date.now();
  log(`>>> ${topic}`);
  console.log(JSON.stringify(payload, null, 2));
  log(`waiting up to ${opts.wait}s for the decision ...`);
  timer = setTimeout(() => {
    log(`TIMEOUT: no decision for ${opts.claim} within ${opts.wait}s`);
    finish(1);
  }, opts.wait * 1000);
});
session.on(solace.SessionEventCode.SUBSCRIPTION_ERROR, (e) => {
  log(`subscription error: ${e.infoStr || e}`); finish(1);
});
session.on(solace.SessionEventCode.CONNECT_FAILED_ERROR, (e) => {
  log(`connect failed: ${e.infoStr || e}`); finish(1);
});
session.on(solace.SessionEventCode.DOWN_ERROR, (e) => {
  if (!landed) { log(`session down: ${e.infoStr || e}`); finish(1); }
});
session.on(solace.SessionEventCode.MESSAGE, (msg) => {
  if (landed) return;                       // a late duplicate never overwrites
  const t = msg.getDestination().getName();
  const res = parseResult(t, decodeBody(msg));
  const elapsed = ((Date.now() - tFire) / 1000).toFixed(1);
  if (res.kind === "decision") {
    const out = res.output;
    if (out.claim_id && out.claim_id !== opts.claim) {
      log(`<<< ${t}: decision for ${out.claim_id}, not ours -- ignored`);
      return;
    }
    landed = true;
    log(`<<< ${t}`);
    console.log(JSON.stringify(out, null, 2));
    const wf = res.meta && res.meta.duration_seconds;
    log(`DECISION ${out.decision} / ${out.lane} for ${opts.claim} -- decided in ` +
      `${elapsed}s (workflow duration_seconds ` +
      `${typeof wf === "number" ? wf.toFixed(1) : "n/a"}, ` +
      `workflow ${res.meta && res.meta.workflow_name || "?"})`);
    finish(0);
  } else if (res.kind === "failed") {
    landed = true;
    log(`<<< ${t}`);
    log(`FAILED after ${elapsed}s: ${res.error}`);
    finish(1);
  } else {
    log(`<<< ${t}: ${res.note} -- still waiting`);
  }
});

log(`firing ${opts.claim} (${anchor.note})`);
session.connect();
