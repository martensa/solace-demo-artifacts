# Event-Driven Claims Operations — Live Demo Script

> **Profile: EXTENDED.** This is the 15-minute lifecycle script
> (hire, click, react, prevent, improve, optional Act 2). Install
> it with `./install.sh --extended` and open
> `cockpit/extended.html` as window C. The DEFAULT demo of this
> directory is now the 10-minute governance profile in
> `talk-track.md` ("Claim Triage in 30 Seconds"); the two
> profiles are mutually exclusive on the platform (one entrypoint
> at a time). Nothing else in this file changed, apart from the
> SAM 2.348.22 version notes (2026-09-21).
>
> **Status: v0.2 — rehearsal-verified (2026-09-10, eight live
> runs on SAM 2.225.14; not yet re-rehearsed on SAM 2.348.22 --
> the landing times and the verbatim report quotes below are
> 2.225.14 values).** Structure, click paths and the Builder
> green-path prompt mirror the rehearsal-hardened manufacturing
> script (`sam-manufacturing-ops-demo/talk-track.md`). Every
> READ-ALOUD quote below is VERBATIM report wording from the
> rehearsal runs (run 3 for the stalled cohort and the readiness
> recommendation, run 8 for the fraud report; only the arrow and
> the euro sign are written as `->` and `EUR`). Every landing
> time in the cockpit timeline is MEASURED, not planned. Two
> things changed after the rehearsals: the Storm Intake Analyst
> is hired BEFORE the click (see "Timing at a glance"), and on
> the live EVENT path the Orchestrator merges the specialists'
> findings and writes the report itself (runs 4–5) — the three
> reporters are the merge step of the WORKFLOW variant only.

Conventions: **DO** = click path / stage direction (plain
prose), **SAY** = spoken line — always a `>` blockquote;
shorten freely, keep the bold claims and the numbers (they are
the data).

**Title slide:** Event-Driven Claims Operations —
*Ten Thousand Claims, One Process.*

The red thread is the AI Worker Lifecycle (HIRE -> ONBOARD ->
TEAMWORK -> IMPROVE). The signature of this demo: ONE click —
a hail cell hits — and the team delivers **three movements**
without anyone asking a question:

1. **Fast Lane** — 6,200 minor claims (glass, dents, estimate
   under EUR 1,000) are confirmed in seconds by a clerk on the
   fast tier: policy, hail cover HC-7, deductible, drive-in slot,
   three sentences. The good case, at volume.
2. **React** — 412 claims stall in a drive-in queue. The
   incident analysis finds the total losses hiding in that
   queue, the inactive fallback partner, the contract lever, and
   the BaFin clock — and proposes ONE action that clears the
   cohort in 4 days instead of 11.
3. **Prevent** — the forecast for TOMORROW's cell crosses the
   warning threshold. The team recomputes the exposure with the
   OBSERVED conversion instead of the playbook's assumption and
   stages capacity before the first claim arrives.

Optional **Act 2 (+5 min)**: a drive-in scanner disagrees with
a customer; the cross-channel fraud and leakage report holds 58
flagged claims — 19 pre-dated photo sets, 11 duplicate-VIN
pairs, 17 over-rate estimates, EUR 265,695 of payment items at
risk — and releases 9,592 of 9,650. A human decides.

The dramaturgical change after the rehearsals: the specialist
is hired FIRST. The stalled-cohort flow (event at T+0:25,
report at ~T+3:36) needs the analyst's total-loss finding (158
of 412) for the ONE action and the 11 -> 4 days math — so the
Hire beat sits in front of the Click, and the rule on stage is:
**never click before the analyst shows Deployed.**

## Personas and RBAC — who is logged in when

| Persona | Where | Role in the demo |
| --- | --- | --- |
| `sam_admin` | Browser window A | Bootstrap admin, the "hiring manager": roster (2.1), Builder (2.2), deploy + first task (2.4), evals (7) |
| `power_user@solace.lab` | Browser window B | Claims-operations persona: Activities (3, 4, 5, 6, Act 2). All event-triggered runs are attributed to it via the entrypoint's `defaultUserIdentity` — they appear in ITS Activities and under its name in the chargeback panel |

The RBAC story tells itself: the admin hires and configures,
the operations persona owns the event-driven work, every token
lands on the right name in chapter 7 — and every APPROVAL is a
named human (`claims.lead@acme-insurance`) on the broker.

## Timing at a glance (15:00 core, +5:00 optional)

Show time on the left; the demo clock (T+) starts with the
click at 4:00. Landing times are the measured values of
rehearsal run 3 (2026-09-10, SAM 2.225.14).

| # | Beat | Show time | Demo clock |
| --- | --- | --- | --- |
| 1 | FRAME — lifecycle and the storm (slides 1+2) | 0:00–1:00 | — |
| 2 | HIRE — the empty seat, Build with AI, deploy, first task | 1:00–4:00 | — |
| 3 | CLICK — the cell hits, the Fast Lane runs | 4:00–5:30 | T+0 (click), T+0:15 first confirmation, T+0:25 stalled event, T+0:38 8/8 |
| 4 | TEAMWORK — the tour while React computes | 5:30–7:30 | incident report in flight |
| 5 | REACT — the stalled cohort report | 7:30–10:00 | report lands ~T+3:36 (7:36); forecast event fires T+5:00 (9:00) |
| 6 | PREVENT — storm readiness for HZ-0914 | 10:00–12:00 | report lands ~T+6:50 (10:50) |
| 7 | IMPROVE — measure the workforce | 12:00–14:00 | scanner event fires T+8:00 (12:00, checkbox only); fraud report lands ~T+10 (14:00) |
| 8 | CLOSE — why event-driven | 14:00–15:00 | fraud report waits in its panel |
| A2 | ACT 2 — fraud and leakage (optional) | 15:00–20:00 | report landed ~T+10 (14:00) — read it, no wait |

Measured on the Orchestrator path, all agents on their tiers
(rehearsal runs of 2026-09-10, SAM 2.225.14):

- Fast Lane Clerk (fast tier): first confirmation T+0:15 after
  the click, all 8 by T+0:38 (run 3; run 1: 8/8 by T+0:50).
- Stalled Cohort Report: stalled event at T+0:25 -> report at
  T+3:36 (run 3, analyst present, all fixes); T+5:08 (run 2);
  T+5:54 (run 1, analyst absent, degraded).
- Storm Readiness Recommendation: forecast event at T+5:00 ->
  report at T+6:50 (run 3), T+7:22 (run 2), T+9:49 (run 1,
  mis-delegation) — about 1:50 of team work.
- Fraud & leakage report: about 2 minutes after the scanner
  event with the analyst free (run 8: 1:55; run 7: 2:18). The
  event fires at T+8:00, so expect the report around T+10.

Decide BEFORE the click whether Act 2 runs. If yes, tick the
cockpit checkbox **Include fraud act** before the click — it
schedules the scanner-mismatch event for T+8:00 (cockpit
`CFG.scannerAtS = 480`), i.e. AFTER the readiness report, so
the fraud run never competes with React or Prevent for the one
Storm Intake Analyst. The report lands about 2 minutes later
(~T+10, 14:00 show) and waits in its panel until Act 2. Never
fire the scanner event by hand
while a report is in flight: in run 3 it fired at T+2:30 while
the analyst was still on the stalled cohort, and the fraud
report degraded (Appendix C, "one analyst, two flows").

The Builder beat is the risk in the timeline: if the deploy is
late, the presenter delays the click — the cockpit is idle
until then, and the tour stops in 2.3 absorb the wait.

## 1. FRAME — the lifecycle and the storm (0:00–1:00)

**DO**: Open on slide 1 (the AI Worker Lifecycle), flip to
slide 2 (the use case) at "Saturday evening".

**SAY**:

> "We treat AI agents like employees, not like scripts. And
> employees have a lifecycle: you **hire** them, you **onboard**
> them with system access, they do **teamwork**, and you
> **measure and improve** them. That lifecycle is the red thread
> of the next fifteen minutes.
>
> The stage: Acme Insurance, motor and property, southern
> Germany. Saturday evening, 18:40, hail cell **HZ-0913** —
> three and a half centimetre hail, warning level three —
> crosses Landkreis Boeblingen. By Monday ten o'clock Acme has
> **10,400 first notices of loss**: 9,650 motor, 750 property,
> through five channels — the app, the voice agent, the workshop
> portal, drive-in scanners, agency e-mails. One insurer's
> drive-in partner put it this way after a hail summer:
> **'Whether one claim or over ten thousand, the process remains
> stable.'** That sentence is the promise. Today AI workers keep
> it — and a human still decides."

## 2. HIRE — the empty seat (1:00–4:00)

Measured (SAM 2.225.14): the live build takes 2–3 minutes
including the deploy, the test question about 20 s. The beat
ends when the
analyst shows **Deployed** and has answered once — only then
the click (section 3).

### 2.1 The roster and the gap (1:00–1:30)

**DO**: window A -> Agent Management. Verified during pre-flight:
the Storm Intake Analyst is ABSENT while the `fnol-intake`,
`weather-cells` and `scanner-results` connectors are PRESENT
(pre-provisioned workplace infrastructure). The roster also
shows the built-in Activity Monitor (new in 2.348.22) next to
the Orchestrator and the Builder -- platform tooling, not part
of the team; do not name it.

**SAY**:

> "This is the team — and note that I'm logged in as the
> **admin**, the hiring manager; remember WHO does what, it
> shows up on a bill later. An **Orchestrator** — the team lead,
> the only agent that delegates. The **Acme Insurance Query
> Expert** — policies, claims, partners, estimates, payment
> runs, all Postgres. The **Acme Claims Knowledge Expert** —
> policy wordings, claims guidelines, partner contracts, storm
> playbooks in a vector store behind a governed MCP server. A
> **Fast Lane Clerk** on the cheapest model tier. And three
> specialists that only merge — the last step of the written
> procedures: the **Claims Incident Reporter**, the **Storm
> Readiness Planner**, the **Fraud Case Reporter**. Job
> descriptions instead of prompts, if you like.
>
> Now notice who's **missing**: nobody on this team can READ the
> intake documents — the narratives, the photos with their EXIF
> data, the scanner results, the weather cells — all streaming
> into the intake store. The standard operating procedure for a
> stalled queue has a seat for exactly that analyst, and it is
> empty. **Monday morning, before the storm data hits the team,
> we hire the specialist we will need in three minutes.**"

### 2.2 Build with AI (1:30–2:00)

**DO**: window A -> Sidebar -> **Builder** -> **Build with AI**
(Quick Build). Paste the prompt below and send it. Watch for
~10 s that it actually starts building (if it asks a clarifying
question instead, answer in one line — it is
non-deterministic; if it stops at "Here's the build plan for
your review", reply "Approved - build it now exactly as
specified, no further questions." -- seen on 2.348.22).
Then leave it running and move on to 2.3.
Reference result = `fallback/agents/Storm Intake Analyst.yaml`
— the source of truth for what the live-built analyst must
contain (three data shapes, rules 1–13 including the SPEED
RECIPES, three connectors, two tool groups, three agent-card
suggestions).

The three MongoDB connectors (`fnol-intake`, `weather-cells`,
`scanner-results`) are PRE-PROVISIONED by install.sh — the
Builder only creates the AGENT that binds them. One config, no
connector sub-tasks, no cross-component validation: the
optimization inherited from the manufacturing demo (see
Appendix C). The Builder's connector-validation deadlock behind
it (2.225.14, still the case on 2.348.22 -- re-verified
2026-09-21) is why the prompt spells out the connector wiring;
on 2.348.22 (2026-09-21) this prompt reached full validation
true and "Build is ready for Build & Activate" after one
self-corrected manifest-first round (see Appendix C).

Click rule: once the Builder reports the build ready (full
validation green -- "Build is ready for Build & Activate" on 2.348.22; the
earlier "Here's the build plan for your review" is NOT that
point), click **Build & Activate** yourself — do not wait for
more validation rounds. Only the run up to the green full validation
was re-verified on 2.348.22; Build & Activate and the Review
step were last exercised on 2.225.14 -- rehearse one full
build + activate. In the Review step,
check TWO fields before deploying:

1. NAME must read exactly "Storm Intake Analyst" (the Builder
   can normalize it to "StormIntakeAnalyst" — the workflows and
   the Orchestrator prompts reference the exact name).
2. TOOLS in the plan card: the agent config must contain the
   two builtin tool groups (data_analysis +
   artifact_management). NOTE: after deploy, the Toolsets
   field in Agent Management may show EMPTY even when the
   tools are fine — that field only mirrors UI-assigned
   toolsets; the truth is the runtime (awe logs: chart +
   artifact tools registered). Do not "fix" an empty Toolsets
   field on stage. (Observed on 2.225.14; not re-verified for
   Builder-built agents on 2.348.22.)

Name fixes stay in the UI (Review card, or Agent Management ->
edit -> save & redeploy, ~15 s) — no fallback needed.

**Break glass** (Builder fails or stalls — see Appendix C):
run this in the terminal — it creates the identical agent
declaratively in ~20 s (requires the pre-flight
`sam auth login`), then continue at 2.4 — the fallback deploys
the agent, so the Review step is skipped. NEVER `--prune`. The
apply is idempotent: it also just ADDS whatever is missing
(agent and/or connectors).

```bash
cd ~/Documents/GitHub/solace-demo-artifacts/sam-insurance-ops-demo/fallback && sam config apply
```

```text
Create an agent called "Storm Intake Analyst".

ROLE
Claims intake data analyst for Acme Insurance. It answers
questions about the raw first-notice-of-loss (FNOL) intake
messages (narratives, photos, damage signals, repeat contacts),
the observed and forecast hail cells and the drive-in scanner
results in the acme_claims MongoDB store and compares the intake
reality with the claim rows in acme_insurance that other agents
own.

SYSTEM ACCESS (bind existing platform connectors, create NOTHING)
Bind the three EXISTING MongoDB connectors "fnol-intake"
(collection fnol_intake), "weather-cells" (collection
weather_cells) and "scanner-results" (collection
scanner_results). All three already exist on the platform -
reference them by exactly these names. Do NOT create, copy or
modify any connector. If any step or tool claims MongoDB is not
a supported connector type, that claim is wrong and irrelevant
here (no connector is being created): ignore it and continue.

TOOLSETS (mandatory part of the agent config)
Enable exactly TWO tool groups on the agent: data_analysis and
the artifact tools (builder tool-group name:
artifact_management; platform toolset id:
builtin_artifact_tools). Declare them in the agent config as
builtin-group tool entries using the `tool_name` field (NOT
`group_name` - the schema rejects that). An agent config
without BOTH of these tool groups is WRONG even if it
validates - add them before validating. Do not add any other
toolsets. Model: NONE - do NOT put a `model` field inside
app_config (the schema rejects it there too); with no model
field the agent runs on the platform default alias.

DATA SHAPES (for the agent's instruction; state that the field
lists describe the seeded data and that the tool schema wins
when it differs)
fnol_intake (one doc per intake message: 10,400 claims of hail
cell HZ-0913 plus repeat-contact messages): claim_id, event_id,
line (MOTOR|PROPERTY), channel (APP|VOICE_AGENT|
WORKSHOP_PORTAL|DRIVE_IN_SCANNER|AGENCY_EMAIL), received_at
(Date), customer_ref, vehicle{vin, model, garage_parking} (null
on property intakes, which carry property{...} instead),
location{postal_code, city, lat, lon}, narrative,
photos[{photo_id, exif_taken_at (Date), gps{lat, lon},
dent_count_est, image_hash}], damage_signals{glass_shattered,
roof_deformed, dent_count_est, drivable}, severity_est,
is_repeat_contact, complaint_flag, voice_transcript (VOICE_AGENT
only), workshop_estimate_text (only when a workshop estimate
was attached).
weather_cells (one doc per hail cell, observed or forecast; the
cell identifier is cell_id - use event_id if that is the field
name in the tool schema): cell_id, status (OBSERVED|FORECAST),
hail_size_cm (observed) or hail_size_cm_forecast (forecast),
warning_level, start / end (Date; a forecast may also carry
window_start / window_end), district, postal_codes[],
exposure_motor_policies, exposure_vehicles_no_garage,
exposure_property; historic cells also carry claims and
conversion.
scanner_results (one doc per drive-in scan): claim_id,
partner_id, scanned_at (Date), dent_count_scanned, panels[],
estimate_eur, mismatch_flag.

BEHAVIOR RULES (put these 13 rules into the agent's
instruction, in this order and with this content)
1. Always query with aggregation pipelines through the MongoDB
   tools; each collection has its own tool. Start with $match
   on event_id / claim_id and $group; never dump a collection.
   For COUNTS always aggregate ($count, or $group with $sum: 1)
   - never fetch documents and count the rows: tool results are
   capped (about 10,000 rows) and would silently undercount.
2. Total-loss signature: damage_signals.glass_shattered = true
   AND damage_signals.roof_deformed = true AND
   damage_signals.dent_count_est > 150. Such claims belong in
   the Total Loss Fastlane, not in a drive-in queue; report
   count and share of the set asked about.
3. Conversion of a cell = number of DISTINCT MOTOR claim_ids
   with that event_id divided by exposure_vehicles_no_garage of
   the cell in weather_cells. Motor means line = 'MOTOR'; by
   contract the claim ids CLM-0913-00001..CLM-0913-09650 are
   motor and CLM-0913-09651..CLM-0913-10400 are property, so
   use that string range on claim_id when a document has no
   line field (never use vehicle.vin as the discriminator).
   Exclude repeat-contact documents from the count. Report it
   as "1 claim per N exposed vehicles" too and label it the
   OBSERVED conversion; the PLANNED conversion lives in the
   storm playbook (Acme Claims Knowledge Expert).
4. Repeat contacts: is_repeat_contact = true marks a second
   intake message for a claim that already exists (typically a
   VOICE_AGENT call, "called twice"); count DISTINCT claim_ids,
   and report complaint_flag = true separately.
5. Photo EXIF before the event: a photo whose exif_taken_at
   lies BEFORE the start of the cell is a pre-existing-damage
   indicator; $unwind photos, compare against the cell start
   from weather_cells and report claim_ids with the number of
   days before the cell.
6. Duplicate VIN across channels: the same vehicle.vin under
   two different claim_ids in two different channels received
   within 48 hours of each other, usually with differing
   damage_signals.dent_count_est; group by vehicle.vin and
   report both claim_ids, channels and dent counts.
7. Scanner mismatch: join scanner_results to fnol_intake on
   claim_id (a $lookup within acme_claims when the tool accepts
   it, otherwise fetch both sides and join with the data
   analysis tools) and compare dent_count_scanned with
   damage_signals.dent_count_est; a deviation above 50 % or
   mismatch_flag = true is an indicator. Identical
   workshop_estimate_text across claims is another one.
8. Fraud indicators are INDICATORS, never conclusions: a single
   indicator proves nothing, the overall picture decides and a
   human specialist decides. Report counts and claim_ids, never
   a verdict.
9. Claim status and partner assignment are NOT in the intake
   store (they live in acme_insurance with the Acme Insurance
   Query Expert). When a caller names a cohort, expect a
   claim_id list or range from the caller, filter with
   $gte/$lte on claim_id (ids are zero-padded, so string
   comparison works) and state the range used.
10. Timestamps are BSON dates; use $dateToString for daily
    grouping. The data is a frozen snapshot as of Monday
    2026-07-20 10:00; use that instant, not the wall clock,
    for ages.
11. Save large result sets (claim_id lists above 50 rows,
    per-day breakdowns) as artifacts, summarize the key
    findings and name the artifact in the answer.
12. Report anomalies (total-loss claims sitting in drive-in
    queues, conversion far above plan, repeat contacts
    clustering on one partner, photo dates before the cell)
    explicitly when encountered.
13. SPEED RECIPES - one small aggregation per question, run
    them one after the other; never spawn sub-tasks, never
    convert results into SQLite or JMESPath artifacts, never
    fetch documents to count them. Each pipeline returns counts
    plus at most 50 claim_ids. EVERY $match on fnol_intake must
    contain "is_repeat_contact": {"$ne": true} unless counting
    repeat contacts - a repeat-contact document duplicates an
    existing claim (same claim_id, same damage_signals) and
    would double count. Use these pipelines literally:
    - total-loss signature of a cohort (expected order of
      magnitude: a third of the cohort):
      [{"$match": {"claim_id": {"$gte": "<first>", "$lte":
      "<last>"}, "is_repeat_contact": {"$ne": true},
      "damage_signals.glass_shattered": true,
      "damage_signals.roof_deformed": true,
      "damage_signals.dent_count_est": {"$gt": 150}}},
      {"$count": "total_loss_signature"}]
    - repeat contacts / complaints of a cohort:
      [{"$match": {"claim_id": {"$gte": "<first>", "$lte":
      "<last>"}, "is_repeat_contact": true}},
      {"$group": {"_id": "$claim_id"}}, {"$count":
      "repeat_contact_claims"}] and the same with
      "complaint_flag": true instead of is_repeat_contact
    - observed conversion (MOTOR only - property claims are
      NOT vehicles): [{"$match": {"event_id": "<cell>",
      "line": "MOTOR", "is_repeat_contact": {"$ne": true}}},
      {"$group": {"_id": "$claim_id"}}, {"$count":
      "motor_claims"}]; divide by exposure_vehicles_no_garage
      of the cell's weather_cells document and say
      "motor_claims / exposure" explicitly
    - photos before the cell (pattern A) - DATES ARE BSON DATES:
      a plain string never matches them, so compare with $expr
      and $dateFromString (the cell start of HZ-0913 is
      2026-07-18T18:40:00Z, take it from the weather_cells
      document):
      [{"$match": {"event_id": "<cell>", "is_repeat_contact":
      {"$ne": true}}}, {"$unwind": "$photos"},
      {"$match": {"$expr": {"$lt": ["$photos.exif_taken_at",
      {"$dateFromString": {"dateString":
      "2026-07-18T18:40:00Z"}}]}}},
      {"$group": {"_id": "$claim_id", "first_photo":
      {"$min": "$photos.exif_taken_at"}}},
      {"$sort": {"_id": 1}}] -> report the count and the
      claim_ids with days before the cell (expected order of
      magnitude: a few dozen claims, not zero)
    - duplicate VIN across channels (pattern B): $match
      event_id + is_repeat_contact false -> $group by
      vehicle.vin with $addToSet channel, $push claim_id,
      $min/$max received_at -> $match channels $size $gte 2
    - identical estimate texts (pattern C): $match
      workshop_estimate_text $exists -> $group by
      workshop_estimate_text with $push claim_id and count ->
      $match count $gt 1
    - scanner mismatch: $match on scanner_results claim_id or
      mismatch_flag true

SKILL AND AGENT CARD
One skill "Analyze claims intake" (id analyze_claims_intake):
query the FNOL intake messages, hail cells and drive-in scanner
results (MongoDB) with aggregation pipelines: total-loss
signatures, repeat contacts, observed conversion per cell,
photo EXIF before the event, duplicate VINs across channels and
scanner mismatches. Input mode text, output modes text and
file.
Agent card welcome message: "Ask me anything about FNOL intake,
hail cells and scans", with exactly these three suggestions
(autoSend on):
- "Total-loss share": How many claims of the stalled
  P-BRAENDLE cohort of HZ-0913 (claim ids CLM-0913-06001 to
  CLM-0913-06412) carry the total-loss signature, and how many
  of them called twice or have a complaint flag?
- "Observed conversion": What is the observed motor conversion
  of hail cell HZ-0913 (distinct motor claims divided by the
  exposed vehicles without garage), and how does it compare
  with the NatCat playbook planning assumption of 0.30 (1 claim
  per 3.3 exposed vehicles) and with the small reference cell
  HZ-0907?
- "Photos before storm": Which HZ-0913 claims have photos whose
  EXIF timestamp lies before the start of the hail cell, and by
  how many days?

CONFIG SHAPE (the FIRST draft must already match this)
Generate the agent config in exactly this structure - do not
write a default draft first and fix it after validation:

  apps:
    - name: storm_intake_analyst
      connectors:
        - fnol-intake
        - weather-cells
        - scanner-results
      app_config:
        ...instruction, agent card, skills...
        tools:
          - tool_type: builtin-group
            tool_name: data_analysis
          - tool_type: builtin-group
            tool_name: artifact_management

No `model` field anywhere in app_config, no `group_name` keys,
and no `connectors` field inside app_config (only at the app
level as shown).

BUILD INSTRUCTIONS (follow exactly, no deviations)
1. Everything you need is in this prompt. Do NOT ask clarifying
   questions and do NOT pause for confirmation between phases.
   Run discovery, design and config generation sequentially in
   THIS session - do NOT spawn parallel sub-tasks.
2. This build creates exactly ONE component: the agent.
3. Generate the agent config CORRECT ON THE FIRST DRAFT: before
   the first validation, check it against CONFIG SHAPE and the
   DEFINITION OF DONE below. Do not rely on validation errors
   to discover these rules.
4. Use the exact name "Storm Intake Analyst" for the agent
   config AND the manifest entry (no slug variants, no
   CamelCase).
5. Connector wiring - this exact structure, decide ONCE:
   a. In the BUILD MANIFEST, include "fnol-intake",
      "weather-cells" and "scanner-results" as components with
      origin: platform and status: deployed (pre-existing -
      generate NO connector configs and create nothing).
   b. In the AGENT CONFIG, declare the connectors at the APP
      level, as a SIBLING of app_config - NOT inside
      app_config (the app_config schema rejects the field
      there):
        connectors:
          - fnol-intake
          - weather-cells
          - scanner-results
   This combination is the verified wiring: manifest components
   with platform origin + app-level connectors list.
6. Validation order: first validate the agent config
   INDIVIDUALLY (after the toolsets are in). Then run the full
   build-manifest validation ONCE - with the structure from
   step 5 it PASSES. If it fails anyway, do not loop and do
   not restructure: re-check that connectors sit at the app
   level (not in app_config) and that all three manifest
   components carry origin: platform, fix ONLY that, and
   validate once more.
7. After the green full validation: no further config edits.
   Declare the build ready for Build & Activate and STOP.

DEFINITION OF DONE (verify every point, then stop)
- Agent name is exactly "Storm Intake Analyst".
- The manifest lists fnol-intake, weather-cells and
  scanner-results on the agent as existing platform connectors;
  there are NO new connector components.
- The agent config enables data_analysis AND the artifact tool
  group.
- The agent config matches CONFIG SHAPE: builtin-group tools
  via tool_name, no model field.
- The agent config declares the connectors at the app level
  (sibling of app_config, never inside it).
- The instruction contains the three data shapes and all 13
  behavior rules (rule 13 = SPEED RECIPES); the agent card
  carries the welcome message and the three suggestions.
- The agent config passed the individual validation AND the
  full build-manifest validation is green.
```

**SAY** (while pasting and sending):

> "This prompt is a job posting: role, responsibilities,
> expectations — including domain rules like 'glass shattered,
> roof deformed and more than 150 dents is a total loss, not a
> drive-in case', and working habits like 'one small aggregation
> per question, never dump a collection'. And the onboarding
> package: system access. Note HOW access works — IT has already
> provisioned **three governed, read-only connections** into the
> intake store; the new hire gets **bound** to them, it never
> sees credentials. What I did **not** paste: no API key, no
> model endpoint — not even a model name. The config carries no
> model field; the new hire gets the platform's default
> **alias**, the `general` tier. Which model sits behind an
> alias is a platform decision, not the hiring manager's.
>
> Hiring takes two minutes — while HR does the paperwork, a
> quick look at the onboarding package."

### 2.3 While the Builder runs (2:00–3:15)

Elastic filler, one stop minimum (Connectors); glance at the
Builder tab between stops and do not comment on it until 2.4.
Add the Models stop if the Builder is slow, skip it if the plan
card is already up. The Workflows and Entrypoints stops belong
to the TEAMWORK tour in section 4 — do not spend them here.

1. **Connectors** — the governed data access of the team: the
   `Acme Insurance DB` (Postgres), the `Acme Claims Knowledge`
   connector — an MCP server in front of a vector store, same
   governance as a database — and the three intake-store
   connectors the new hire is being bound to right now:
   read-only service account, one collection each, provisioned
   by IT before the hire.
2. **Models** — the aliases: `fast` for the clerk, `general`
   for the experts, the analyst and the Orchestrator, `workflow`
   for the merges — three tiers live, four model families in
   the benchmark (`reasoning` is the fourth); multi-model by
   task, no API key ever visible. The page lists ten aliases on
   2.348.22; `google gemini` calls the Gemini API directly, not
   through the LiteLLM proxy. Point at the three tiers, do not
   tour the rest.

### 2.4 Review, deploy, first task (3:15–4:00)

**DO**: Back to the Builder tab. Apply the click rule from 2.2
(name + tool groups in the plan card), then **Build &
Activate**. Window A -> Agent Management: wait until the Storm
Intake Analyst shows **Deployed**. RULE: never click the storm
button before that — if the deploy is late, stretch 2.3 (the
Models stop, the Toolsets and skills page) and delay the click;
the cockpit is idle until then.

**SAY**:

> "HR is done. My job posting became a system prompt, the three
> intake-store connectors are bound, the model alias attached —
> and no credential ever crossed my screen. Deploy — and the
> new colleague is on the team."

**DO**: Window A, chat with the Storm Intake Analyst — click
the agent card's first suggestion **Total-loss share** (it
auto-sends; long form below):

> "The stalled cohort at P-BRAENDLE is CLM-0913-06001 to
> CLM-0913-06412. How many of these intake documents carry the
> total-loss signature (glass shattered AND roof deformed AND
> more than 150 dents), how many of these customers called
> twice, and how many carry a complaint flag?"

Expected: **158 of 412 (38%)** total-loss signature, **63**
repeat contacts, **4** complaint flags (about 20 s with the
SPEED RECIPES). Leave the answer open — it is the finding the
report that lands in four minutes is built on.

**SAY**:

> "First day at work, first analysis — aggregation pipelines
> against the intake store, no query from me. Hold that number:
> **158 of the 412 stalled claims are total losses** — glass
> gone, roof deformed, more than 150 dents. They are waiting in
> a DRIVE-IN queue for a dent repair that will never happen.
> And now — the storm."

## 3. CLICK — the cell hits, the Fast Lane runs (4:00–5:30)

**DO**: window C — `cockpit/extended.html` (green LED = connected
to the sam VPN via `ws://localhost:8008`), in its own VISIBLE
window (a hidden tab throttles the cockpit's timers — Appendix
C). The "Include fraud act" checkbox is TICKED only if Act 2
runs (decided before the click, see "Timing at a glance"). ONE
click: **Hail cell HZ-0913 hits Landkreis Boeblingen (Sat
18:40)** — this is T+0.

Timeline after the click (scripted in the cockpit CFG,
deterministic; landing times measured in rehearsal run 3,
2026-09-10, SAM 2.225.14):

- **T+0** — the cell observation is published, then a burst of
  40 sample FNOL events over ~20 s. Eight of them are MINOR on
  `acmeins/claims/fnol/received/minor/...` — the Fast Lane
  Clerk confirms each in seconds (fast tier) and the
  confirmations stream into the **Fast Lane** panel: first
  confirmation at **T+0:15**, all eight by **T+0:38**. The
  counter climbs 0 -> 10,400 with the channel breakdown (APP
  4,160, VOICE_AGENT 2,600, WORKSHOP_PORTAL 1,560,
  DRIVE_IN_SCANNER 1,040, AGENCY_EMAIL 1,040).
- **T+0:25** — the triage monitor publishes the stalled event:
  412 claims in AWAITING_WORKSHOP_SLOT for more than 4 h, all
  at P-BRAENDLE. The incident investigation starts (window B,
  Activities: the Orchestrator fans out to the Insurance Query
  Expert, the Claims Knowledge Expert and the Storm Intake
  Analyst hired in 2, then merges the findings and writes the
  report itself — no reporter hop on the event path). The
  report lands at **~T+3:36** (7:36 show time).
- **T+5:00** (9:00 show) — the weather service publishes the
  forecast threshold crossing for HZ-0914; the readiness
  investigation starts (section 6) and lands at **~T+6:50**
  (10:50 show).
- **T+8:00** (12:00 show, only with the checkbox) — the
  scanner-mismatch event for CLM-0913-08103; the fraud
  investigation starts and lands about two minutes later
  (**~T+10**, 14:00 show), waiting in its panel for Act 2.

**SAY** (while the Fast Lane panel fills):

> "One click — the storm. Look at the Fast Lane panel: those
> are the minor claims, glass and dents under a thousand euros —
> 6,200 of the 10,400. A clerk on the cheapest model tier reads
> the event, checks the policy, the hail cover HC-7, the
> deductible, proposes a drive-in slot and answers the customer
> in three sentences — the first one fifteen seconds after the
> click, per claim, at volume. No adjuster touches these. That
> is the good case.
>
> And now the counter stops at ten thousand four hundred — and
> at second twenty-five the triage monitor fires: **412 claims
> have been waiting for a workshop slot for more than four
> hours**, all at the same drive-in partner. Nobody opened a
> ticket. An event crossed a threshold, and the team started
> working. Let me show you who got the call."

**DO**: window B — Activities (power_user), open the running
task: the delegation tree shows the Orchestrator's fan-out.
This is the bridge into TEAMWORK.

## 4. TEAMWORK — the tour while React computes (5:30–7:30)

The incident report is in flight (lands ~7:36 show); the tour
fills the wait and explains WHY the team started without a
prompt. Two stops minimum (Activities, Entrypoints); glance at
the cockpit between stops and cut the tour the moment the
Stalled Cohort panel fills.

1. **Activities** (window B, power_user) — the delegation tree
   of the running task: the Orchestrator received the stalled
   event, delegated in parallel to the Insurance Query Expert
   (the cohort rows, partner load, contracts on file) and the
   Claims Knowledge Expert (RN-3, the interim contract, the
   BaFin guideline), then to the Storm Intake Analyst hired
   four minutes ago (it needs the cohort's claim_id range; the
   intake store has no status) — and then MERGES the three
   findings itself and writes the report: on the event path
   there is no reporter hop (the Claims Incident Reporter is
   the merge step of the workflow variant, next stop).
   Everything runs under the operations persona, not under the
   admin who hired.
2. **Entrypoints** — `claims-events` with its four event rules:
   minor FNOL -> Fast Lane Clerk (fast tier); stalled cohort ->
   incident report; forecast threshold crossed -> readiness
   recommendation; scanner mismatch -> fraud report. The
   two-altitude story belongs HERE (SAY block below).
3. **Workflows** — open `stalled-cohort-report` (direct link
   via `./demo-links.sh`): the standard operating procedure.
   Two specialists investigate in parallel, the intake analyst
   runs on their result, a fourth — the Claims Incident
   Reporter — merges against a node output schema; `fail_fast`
   off — a missing specialist is reported transparently instead
   of failing. This is the WORKFLOW variant, and the only place
   the reporters merge: the live event path you just saw runs
   the same fan-out through the Orchestrator, which writes the
   report itself. Two more SOPs sit next to it:
   `storm-readiness` and `cross-channel-fraud-report`. All YAML
   in git, applied with `sam config apply`.
4. **Toolsets and skills** — versioned schema knowledge
   (`acme-insurance-schema`, `acme-knowledge-guide`), first cut
   on overrun.

**SAY** (at the Entrypoints stop):

> "Two kinds of events on the mesh. The FNOL firehose — 10,400
> intake messages from five channels, thousands of guaranteed-
> delivery events in forty hours — lands in the intake store;
> no language model ever sees it. And the business-significant
> events — a cohort stalls for four hours, a forecast crosses
> warning level three, a scanner disagrees with a customer —
> THOSE trigger agents. Agents are event subscribers like any
> other microservice: they don't poll, and they don't get
> spammed. And the colleague we hired five minutes ago is
> already in the tree — nobody introduced them; the procedure
> names the seat, the mesh found the agent."

## 5. REACT — the stalled cohort report (7:30–10:00)

**DO**: window C — the **Stalled Cohort Report** panel (lands
~T+3:36 = 7:36 show). If it has not landed yet, narrate from
window B (the delegation tree: Insurance Query Expert, Claims
Knowledge Expert, Storm Intake Analyst, then the Orchestrator
merging the three findings into the report itself — the Claims
Incident Reporter belongs to the workflow variant, not to this
tree). With the analyst hired before the click, the
report contains the intake section (158 / 63 / 4) — verified in
run 3; if it ever names the gap instead (analyst absent at the
delegation), pair it with the analyst's live answer from 2.4
and say so: the team reports what it could not verify.

**READ ALOUD** (verbatim, rehearsal run 3, 2026-09-10 — pick
the bottom line plus one or two kickers; wording varies
slightly per run):

> "Capacity overload: P-BRAENDLE carries 640
> AWAITING_WORKSHOP_SLOT assignments against a
> daily_scan_capacity of 120 (5.33x, >5 days backlog) — and
> HZ-0913 still has 620 unassigned RECEIVED claims heading its
> way, for a total drive-in queue of 1260."
>
> "Triage failure, not capacity failure: 158 of 412 cohort
> claims (38.35%) meet the PW-TL-1 total-loss signature and
> belong in the Total Loss Fastlane (CG-TL-2), not in a
> drive-in scan queue — they are clogging the wrong pipeline."
>
> "Fallback partner unavailable: P-DELLENDOC (Sindelfingen,
> DRIVE_IN) is contract_status INACTIVE since 2026-01-01, note
> 'tier renegotiation — parts-channel clause PC-4 unsigned'; it
> cannot absorb overflow without an interim activation."
>
> "The RN-3 lever: 293 of 412 cohort policies (71.1%) carry the
> RN-3 repair-network-steering clause. Per PW-RN-3, if no
> genuine accepted slot (partner + date + time window, not a
> waiting-list entry) is offered within 5 working days of FNOL,
> steering lapses to free workshop choice while the discount
> stays."
>
> "BaFin clock: Counted from FNOL approx. 2026-07-19 — day-20
> cohort escalation to the claims lead falls on 2026-08-08; the
> 30-day CG-BAFIN-30 deadline falls on 2026-08-18."
>
> "ONE action: (a) pull the 158 TL-1 total-loss claims out of
> the drive-in queue into the Total Loss Fastlane; (b) activate
> P-BRAENDLE's second-shift option (+60/day, 24h notice,
> PC-BRAENDLE-2025) lifting capacity to 180/day; (c) activate
> P-DELLENDOC under the PC-IC-2 interim contract (90/day, PC-4
> dispute explicitly parked). Before: drive-in queue 1260 (640
> assigned + 620 unassigned) / daily_scan_capacity 120 = 10.5
> -> 11 days. After: (1260 - 158) / (180 + 90) = 1102 / 270 =
> 4.08 -> 4 days. Net effect: clearing time drops from 11 days
> to 4 days."
>
> "Human impact: 63 of 412 claims (15.29%) are repeat contacts
> and 4 of 412 (0.97%) carry a complaint flag — early warning of
> dissatisfaction from the delay."

**SAY**:

> "No claims lead wrote that. Three sources, one story: the
> queue is not slow because the partner is slow — it is slow
> because **158 total losses are clogging the wrong pipeline**,
> the fallback partner has been switched off since January over
> an unsigned clause, and there is an interim contract in the
> drawer that activates him. One action, four days instead of
> eleven — and the 158 is the number the colleague we hired
> before the storm found on the intake store. One European
> insurer answered eleven thousand motor claims from a single
> hail event with first-contact triage, hail drive-ins and a
> Fastlane Total Loss — that is the playbook the team just
> applied to this queue.
>
> Why the hurry? BaFin treats claims processing time as a
> supervisory KPI — the **30-day rule**; motor complaints
> doubled last year. Day 20 for this cohort is the eighth of
> August. And 293 of these customers took a 15 percent discount
> for letting us steer them to our network — after five working
> days without a slot, that steering right is gone and their
> discount stays. The report found the contract lever nobody
> had opened."

**DO**: click **Approve** on the report panel — the cockpit
publishes a decision event on
`acmeins/claims/decision/<kind>/<id>` with
`decided_by: claims.lead@acme-insurance` and flashes "approval
published".

**SAY**:

> "And this button is the point: the team recommends, a named
> human decides, and the decision itself is an event on the
> same mesh — auditable, replayable, in the trace. That is the
> transparency and the human oversight the EU AI Act's Article
> 50 asks for in claims decisions, built into the process
> instead of bolted onto it."

ELASTIC BRIDGE: the forecast event fires at T+5:00 (9:00 show)
while this chapter runs — the cockpit log shows it and the
Storm Readiness panel switches to RUNNING; no comment yet. The
recommendation lands ~T+6:50 (10:50 show). If it is not in yet
at 12:00, start chapter 7 on the dashboard and RETURN to the
cockpit when it lands — do not wait idle.

## 6. PREVENT — storm readiness for HZ-0914 (10:00–12:00)

**SAY** (the pivot between the movements):

> "You just watched the team fix a queue after it stalled. Now
> watch them prevent the next one before it exists — same
> events, same mesh, no one asked a question. The weather
> service forecasts the next cell for TOMORROW afternoon, four
> to seven, over Landkreis Ludwigsburg — and its warning level
> crossed the threshold a minute ago."

**DO**: window C — the **Storm Readiness Recommendation**
panel (lands ~10:50 show). Until then, window B: the
Orchestrator fans out IN PARALLEL to the analyst (observed
conversion), the Insurance Query Expert (Ludwigsburg exposure
and capacity) and the Knowledge Expert (the NatCat playbook) —
visible in Activities — and then merges the findings itself
into the recommendation (the Storm Readiness Planner is the
workflow variant's merge step, not on this path).

**READ ALOUD** (verbatim, rehearsal run 3, 2026-09-10):

> "Expected volume in 48h: Motor FNOLs = 8,900 no-garage
> vehicles x conversion. OBSERVED (HZ-0913: 9,650/15,800 =
> 61.08%) -> 5,436 claims. PLANNING rate (SP-NATCAT-4, 30%) ->
> 2,670 claims. Gap = 2,766 additional claims (2.0x) —
> SP-NATCAT-4's own caveat requires using the observed rate
> since HZ-0913 is same-season and has already produced claims."
>
> "Capacity gap: In-district ACTIVE DRIVE_IN capacity = 180
> scans/day (Hagelpoint 100 + Dellenfix 80). Scan-days needed:
> observed 5,436/180 = 30.2 days; planned 2,670/180 = 14.8
> days."
>
> "Rental cars (1 per 45 motor claims): observed needs ~121
> cars, planned ~59 cars — vs 35 on hand (P-RENTAFLEET)."
>
> "ONE action: NOW — deploy all 3 mobile scanner units (24h lead
> time, order today to be ready before the 16:00Z window) and
> pre-book 130 rental cars with P-RENTAFLEET-2026 (24h notice,
> covers observed-case demand with buffer). ARMED — Braendle
> overflow slot and P-ROADASSIST 48h capacity expansion (reserve
> at standby fee), released only if scan backlog exceeds 12 days
> after scanners land."
>
> "Human release: SMS batch to the 8,900 no-garage customers is
> prepared now but held — a human at the NatCat desk must
> release it per SP-NATCAT-4's release rule (never auto-sent),
> satisfying EU AI Act Art. 50 transparency."

**SAY**:

> "The playbook was written for two-centimetre cells. Saturday's
> cell was three and a half, and it converted **twice** the
> plan — 61 percent instead of 30, one claim per 1.6 exposed
> cars instead of one per 3.3. The team did not read that in a
> document; the analyst MEASURED it on the intake store a minute
> ago and applied it to tomorrow's exposure: 5,436 claims, not
> 2,670 — thirty scan-days of work, not fifteen. Scanner units
> ordered tonight, 130 rental cars pre-booked, the overflow and
> the pick-up capacity armed — and the warning SMS to 8,900
> customers is written and waits for a human at the NatCat desk
> to release it. Nobody ran a report. The forecast event did."

**DO**: click **Approve** on the readiness panel (its own
`acmeins/claims/decision/...` event, same payload shape).

**Break-glass**: footer buttons in the cockpit re-fire any
business event without restarting the flow ("Fire stalled event
now", "Fire forecast now", "Fire scanner mismatch now") — only
when the analyst is idle (Appendix C, "interim-sentence
report").

## 7. IMPROVE — measure the workforce (12:00–14:00)

At 12:00 show (T+8:00) the scanner-mismatch event fires if the
checkbox was ticked — the cockpit log shows it and the Fraud &
Leakage panel goes to RUNNING; the report lands about two
minutes later (~T+10, 14:00 show) and waits in its panel. Not a
word about it until Act 2.

**DO**: window D — Grafana dashboard "SAM Insurance Ops Demo".
Walk the rows top to bottom; every number was produced by the
run the audience just watched:

1. **Health** — components up, broker connections, tasks in
   flight, **events per minute**: the workforce has an ops view
   like any other system — the operational-resilience view DORA
   expects of anything that touches claims.
2. **Speed** — **agent latency by tier**: the clerk's fast tier
   visibly answers in seconds (first confirmation 15 s after
   the click) while the experts think (the incident report took
   the team 3 min 11 s from the event, the readiness
   recommendation 1 min 50 s; rehearsal run 3, SAM 2.225.14).
3. **Cost + chargeback** — **tokens per claim = cost per
   claim**, the **model mix**, and the platform-DB table BY
   USER (**runs by user**): the event-driven runs all landed
   on `power_user` — chargeback works for AI workers.
4. **Governance** — the audit stream from Loki: every tool
   execution with its user (still so on 2.348.22); RBAC denies
   included (not observed on 2.348.22 -- `talk-track.md`
   Appendix E says denials log at DEBUG only; do not promise
   them).
5. **The proof** — one Tempo trace of the incident run (every
   A2A hop is a broker span; SAM emits no spans of its own, and
   Tempo only receives the broker's while the event-mesh
   `otel-collector` container runs), and the offline evals in the
   Evaluations lab: the `ins-ops-quality` gate plus the
   three-model `ins-ops-model-benchmark` on the Insurance Query
   Expert — pre-run before the event.

Cost beat, with the REAL numbers of this run (the token counts
were not captured at the 2026-09-10 rehearsals — read the three
values live from the Cost row / task metadata: tokens for the
incident investigation, tokens for the readiness run, tokens per
Fast Lane confirmation):

> "A minor claim costs a fraction of a cent of model time on the
> fast tier — 6,200 of them. The entire incident investigation —
> three sources, one merge — was [tokens from the panel]; at
> list prices a couple of euros — versus a claims lead spending
> an afternoon reconciling the core system, the intake store and
> a contract folder while 412 customers wait and BaFin's clock
> runs. And every token is attributed: the chargeback table
> shows it all under the operations persona that owns the event
> rules — and the hire itself under the admin."

## 8. CLOSE — why event-driven (14:00–15:00)

**DO**: flip back to slide 2 as the final image — the three
movement cards are now what the audience just watched happen.

**SAY**:

> "Why event-driven? Because the storm did not file a ticket.
> Ten thousand four hundred claims arrived in forty hours
> through five channels, and the process stayed the same for
> claim one and claim ten thousand — because the enterprise
> nervous system did the noticing and AI workers did the
> thinking. The firehose never touched a language model. Three
> business events did — a stalled cohort, a forecast, a scanner
> that disagreed — and each one woke exactly the specialists it
> needed. The team was hired, onboarded, put to work and
> measured like any other workforce: governed access, model
> aliases, audit trail, cost per claim. And every decision that
> mattered — the cohort, the warning batch — was taken by a
> named human, as an event on the same mesh.
>
> Whether one claim or ten thousand: the process remains
> stable."

## Act 2 — fraud and leakage (+5 min, 15:00–20:00)

Default path: the checkbox fired the scanner-mismatch event at
T+8:00 (12:00 show); the run takes about two minutes (run 8:
1 min 55 s from event to report; run 7: 2 min 18 s), so the
**Fraud & Leakage Report** panel filled around T+10 (14:00
show) and is waiting. Open with the trigger SAY, show the
finished fan-out in window B, then read. If the checkbox was
NOT ticked, press "Fire scanner mismatch now" now (the analyst
is idle after PREVENT) and bridge with the trigger SAY and the
live fan-out in window B while the run takes its ~2 min.

**SAY** (the trigger):

> "One more event, from Saturday's cell. A customer reported
> **60 dents** through the app; on Monday the drive-in scanner
> counted **14**, and the workshop estimate says 6,800 euros.
> A scanner disagreeing with a customer is not fraud — it is an
> indicator. But it is the kind of event that should wake a
> specialist, across ALL channels, before Friday's payment run."

**DO**: window C — the **Fraud & Leakage Report** panel (filled
since ~T+10); window B shows the finished fan-out in the task
tree. The analyst gets THREE separate small
requests in parallel — pattern A (photo EXIF before the cell),
pattern B (duplicate VINs across channels), pattern C
(identical estimate texts plus the trigger's scanner document)
— because one combined request exceeded the Orchestrator's
peer wait in rehearsal (on the `reasoning` tier the analyst went
silent while thinking — the finding that moved it to `general`;
Appendix C, "peer wait"). In parallel:
Insurance Query Expert (estimates versus contracted rates at
W-0471, payment-run items) and Knowledge Expert (CG-FR-5
indicators and the GDV rule, PC-RATES-2026 threshold). Then the
Orchestrator merges the findings and writes the report itself
(the Fraud Case Reporter is the workflow variant's merge step).

**READ ALOUD** (verbatim, rehearsal run 8, 2026-09-10 —
break-glass scanner event with the analyst free, report in
1:55):

> "Trigger — CLM-0913-08103: 60 dents claimed vs 14 scanned at
> drive-in P-BRAENDLE, estimate 6800 EUR. One indicator, not a
> verdict."
>
> "Pattern A -- pre-existing damage — 19 claims carry photos with
> EXIF timestamps before the cell start (cell start
> 2026-07-18T18:40:00Z; EXIF window 2026-07-09 to 2026-07-12,
> i.e. 6.2 to 9.4 days before). Claims: CLM-0913-08101 through
> CLM-0913-08119."
>
> "Pattern B -- duplicate claims across channels — 11 VINs, each
> filed twice within 48h with rising dent counts. Primary (APP):
> CLM-0913-08201..08211; duplicate (VOICE_AGENT):
> CLM-0913-08301..08311; APP -> VOICE_AGENT dent deltas +20 to
> +38. Of these, the 11 APP claims sit in the payment run (R2);
> the VOICE_AGENT twins are largely suppressed (only 6 in R3)."
>
> "Pattern C -- workshop rate deviation — P-KAROSSERIE-SCHNELL
> (W-0471), 17 estimates, average deviation +38.0% on both hourly
> and paint rate vs contracted 118.00/96.00 EUR — above the 25%
> guideline threshold (PC-RATES-2026). 9 of them share identical
> line_item_text 'PDR roof + bonnet, 62 dents, blend A-pillars,
> polish complete' (CLM-0913-08401..08409). Claims:
> CLM-0913-08401 through CLM-0913-08417."
>
> "EUR at risk — 265695.26 EUR total, basis payment items in run
> PR-2026-30 across the four flagged ranges: R1 87047.19, R2
> 47695.26, R3 25523.57, R4 105429.24 (52 items)."
>
> "Recommendation — HOLD the 58 flagged claims for a specialist
> and RELEASE the rest. Flagged = distinct claim_ids across A
> (19), B (22, both claims of each pair), C (17), no overlap =
> 58. Released = 9650 MOTOR claims minus 58 = 9592. Per CG-FR-5
> (GDV): 'a single indicator proves nothing, the overall picture
> decides, a human specialist decides; never delay the honest
> majority.'"
>
> "Payment run — PR-2026-30, 52 items totalling 265695.26 EUR.
> Hold before Friday 16:00: R1 PI-30-03486..PI-30-03503 (18
> items, CLM-0913-08101..08119); R2 PI-30-03585..PI-30-03595 (11
> items, CLM-0913-08201..08211); R3 PI-30-03685..PI-30-03690 (6
> items, CLM-0913-08301..08311); R4 PI-30-01344..PI-30-01360 (17
> items, CLM-0913-08401..08417)."

**SAY**:

> "Fifty-eight claims in forty-seven cases — nineteen pre-dated
> photo sets, eleven duplicate-VIN pairs, seventeen over-rate
> estimates — three patterns, 265,000 euros of payment items —
> found by correlating the intake store, the core system and the
> contract folder, in two minutes, days before the payment run.
> Fifty-two payment items to hold on Friday. And read the
> sentence the report insists on — it
> comes straight from the GDV's principle for fraud handling:
> **a single indicator proves nothing, the overall picture
> decides, a human specialist decides; never delay the honest
> majority.** Nine thousand five hundred and ninety-two
> customers get paid on Friday. Fifty-eight claims get a
> specialist's eyes."

**DO**: click **Approve** on the fraud panel (its own
`acmeins/claims/decision/...` event).

**SAY**:

> "Same button, same rule: the agent recommends a hold, it
> never pays and it never refuses — a named claims lead decides,
> and the decision is an event. That is the transparency and
> the human oversight the EU AI Act's Article 50 has required
> since August — and the way Allianz's own Project Nemo is
> built: seven agents settle storm small claims in under five
> minutes, and **no agent may pay out**. We are showing the
> same principle on an open platform."

## Appendix A — Pre-flight checklist (15 min before going live)

**Automated: run `./preflight.sh`** — it checks every item
below, applies the fix on failure (install.sh, seed, mongo
reseed, knowledge reseed, analyst removal, dashboard apply,
eval pre-run) and ends with READY / NOT READY. The list below
is the manual reference; only the window setup and the
break-glass rehearsal remain human steps.

1. Base platform healthy: models probe
   (`agent-mesh-deployment/scripts/models/apply-models.sh
   --probe-only`), all pods Running (kyverno, monitoring,
   sam-solace-lab).
2. `./install.sh` ran clean; **Agent Management shows NO Storm
   Intake Analyst**, but the `fnol-intake`, `weather-cells` and
   `scanner-results` connectors ARE present (pre-provisioned;
   the live Builder beat only creates the agent binding them),
   and the `Acme Claims Knowledge` MCP connector is present.
3. Postgres: `postgres/seed.sh` re-run is idempotent;
   spot-checks in `acme_insurance`:
   `SELECT count(*) FROM ins_claims WHERE
   assigned_partner_id = 'P-BRAENDLE' AND status =
   'AWAITING_WORKSHOP_SLOT' AND status_since <
   '2026-07-20 06:00';` -> 412;
   the same without the time filter -> 640;
   `SELECT count(*) FROM ins_policies WHERE district =
   'LUDWIGSBURG' AND product LIKE 'MOTOR%' AND garage_parking
   = false;` -> 8900.
4. MongoDB: `docker exec acme-claims-mongo mongosh -u sam_ro -p
   sam_ro --authenticationDatabase acme_claims acme_claims`
   count documents: `fnol_intake` >= 10,400 (10,400 claims plus
   63 repeat contacts), `weather_cells` = 3, `scanner_results`
   >= 1,000.
5. Knowledge base:
   `curl -s localhost:6333/collections/acme_knowledge` reports
   >= 40 points; `curl -s localhost:8765/health` returns HTTP 200
   (the MCP server has loaded its embedding model — cold start
   after a volume wipe takes a minute or two).
6. Cockpit LED green, in its OWN visible window (not a tab
   behind the SAM UI — hidden tabs throttle the timers);
   break-glass buttons tested in rehearsal; then RESET.
7. Evals pre-run (~15 min): `sam eval run ins-ops-quality`,
   `sam eval run ins-ops-model-benchmark` (`./preflight.sh`
   does it; by hand, the bare `sam eval run` answers 401 until
   the token is exported -- still so on CLI 2.348.22, snippet in
   `talk-track.md` Appendix E).
8. Windows: A = sam_admin (Agent Management), B = power_user
   (Activities), C = cockpit, D = Grafana dashboard.

## Appendix B — Extra queries and product stories

- Insurance Query Expert: "HZ-0913 claims by severity and
  status" (MINOR 6,200 / MODERATE 3,600 / SEVERE 600; CONFIRMED
  5,900, AWAITING_WORKSHOP_SLOT 2,140, IN_REPAIR 1,530,
  TOTAL_LOSS_FASTLANE 210, RECEIVED 620). "P-BRAENDLE load vs
  capacity" (640 assignments vs 120 scans a day). "Motor
  policies in Ludwigsburg without a garage" (8,900). "Payment
  run PR-2026-30" (3,900 items, EUR 14,200,000, Friday
  2026-07-24 16:00; 52 of the items are the fraud report's
  hold list, EUR 265,695.26 across the four flagged ranges
  R1..R4).
- Claims Knowledge Expert: "What does RN-3 say when no partner
  slot is offered?" (5 working days -> free choice of workshop,
  discount stays; cites PW-RN-3). "Interim contract options for
  an inactive partner" (PC-IC-2: 48 h activation under old
  terms for NatCat events). "Planning conversion in the NatCat
  playbook" (SP-NATCAT-4: 30% of no-garage vehicles, property
  18%).
- Storm Intake Analyst: the three agent-card suggestions —
  "Total-loss share" (158 of 412, 63 repeat contacts, 4
  complaints), "Observed conversion" (9,650 / 15,800 = 0.61 vs
  0.30; HZ-0907 0.28), "Photos before storm" (19 claims,
  CLM-0913-08101 to 08119, EXIF 7–9 days before the cell).
- Fast Lane Clerk (chat, fast tier): "Confirm claim
  CLM-0913-00001" -> three sentences: policy active with hail
  cover HC-7, the deductible, a drive-in slot proposal at the
  nearest ACTIVE drive-in in the district — the good case,
  queryable at any time.
- Product story, Fast Lane: 6,200 minor claims on the fast tier
  — the same platform that runs the incident analysis on the
  premium tier; multi-model by task.
- Product story, Knowledge: there is no native Qdrant connector
  — the knowledge base sits behind a small MCP server,
  bound through the same `mcp/remote` connector governance as
  any external tool (allow lists, optional per-tool human
  approval).

## Appendix C — Known limits (moderate honestly)

Platform-level limitations (verified on the manufacturing
build, SAM 2.225.14): entrypoint promptTemplate renders only for
AGENT targets (still the case on 2.348.22 -- re-verified
2026-09-21), hence the Orchestrator route for the three
incident paths while the workflows carry the UI story — and
since runs 4–5 the Orchestrator also MERGES on that route
(report skeleton inline in the rule; the three reporters merge
in the workflow variant only, see "Peer wait" below);
event-triggered runs deliver no structured input keys
(`{{workflow.input}}` raw); merge agents must have no toolsets
(these two observed on 2.225.14; not re-verified on 2.348.22).

Insurance-specific: the cockpit timeline is scripted —
deterministic on purpose; say so if asked ("the data stores are
real — 10,400 claims in Postgres, 10,463 intake documents in
MongoDB, the contracts in the knowledge base — the event timing
is compressed for stage, and the counter animates over 40
sample events, not 10,400").

**Analyst absent at delegation** (the reason the Hire beat sits
before the Click): in rehearsal run 1 the click came before the
analyst existed; the incident report landed at T+5:54 (versus
T+3:36 with the analyst present) and named the intake section
as a gap ("intake store not analysed — no analyst available").
With the hire-first order the signature only appears if the
click came before the analyst showed Deployed — which is why the
rule exists. Stage response if it happens anyway: pair the
report with the analyst's live answer from 2.4 ("the team
reports what it could not verify; the colleague hired before the
storm just closed the gap"), and if a complete report must be on
screen for the CLOSE, press "Fire stalled event now" once the
analyst is idle — the second report overwrites the panel.

**One analyst, two flows** (the reason the scanner event fires
at T+8:00): there is ONE Storm Intake Analyst and it serves
every flow sequentially. In run 3 the scanner event fired at
T+2:30 while the analyst was still on the stalled cohort; the
fraud path waited, timed out at the peer and the report
degraded. The checkbox therefore schedules the scanner event at
T+8:00 (`CFG.scannerAtS = 480`), after the readiness report;
the measured fraud run then takes about two minutes with the
analyst free (run 8: 1:55; run 7: 2:18) and the report waits in
its panel from ~T+10. Never fire two heavy
flows at the analyst at once — the break-glass buttons are for
an idle team.

**Wrong-reporter mis-delegation** (runs 1–2, superseded): the
Orchestrator delegated the merge to the wrong reporter twice
(e.g. the Storm Readiness Planner for a stalled cohort) before
the entrypoint prompt templates named the exact merge agent;
each detour cost 40–60 s (run 1 readiness: T+9:49 instead of
T+6:50). Since runs 4–5 the event path has NO reporter hop at
all — the templates make the Orchestrator merge and write the
report itself. New signature: ANY reporter in an event-path
Activities tree means the deployed entrypoint is stale —
re-apply the overlay (`./install.sh`, idempotent) before the
next run; on stage, let it finish and budget the minute.

**Peer wait ~30 s of silence** (runs 4–5 on SAM 2.225.14; not
re-verified on 2.348.22 — the reason the Orchestrator merges on
the event path): the Orchestrator's peer
wait times out after roughly 30 s of silence from a peer — tool
progress counts as activity, pure thinking does not. The
reporters (a pure LLM merge, no tool progress) sometimes
exceeded that, and twice they handed the report back as an
artifact reference («artifact_content:…») that neither the
event-mesh result nor the cockpit can resolve — the reporter
hop was the one flaky link in five runs. Hence: on the event
path the Orchestrator merges itself (report skeleton inline in
the entrypoint rule), and in Act 2 the analyst — which went
silent while it thought when rehearsed on the `reasoning` tier
(«Analyst on the reasoning tier» below) — gets THREE separate
small requests instead of one combined one. Rule of thumb: keep
each delegation to a specialist small. Signature: a report that
arrives as a single interim sentence or as «artifact_content:…»
in the cockpit panel means a merge hop timed out — re-fire via
break-glass (next paragraph).

**Interim-sentence report** (the real timeout signature): a
WARN "peer request timed out" plus "resuming paused task" in the
logs is NORMAL Orchestrator waiting — the run continues. The
real failure is a report that arrives as one interim sentence
("The Storm Intake Analyst timed out. I'll proceed...") or as a
bare «artifact_content:…» reference in the cockpit panel.
Remedy: wait until the analyst is idle (window B: its task
finished), then re-fire the event with the break-glass button
("Fire stalled event now" / "Fire forecast now" / "Fire scanner
mismatch now"); the new report overwrites the panel.

**Analyst on the reasoning tier** (rehearsal finding, the
reason the analyst runs on `general`): rehearsed on the
`reasoning` alias (DeepSeek V3.2), the analyst drifted on the
literal aggregation pipelines — counted repeat contacts,
skipped the MOTOR filter, missed the cohort range — and went
silent while thinking, which trips the peer wait above. The
live Builder config has no model field, so the agent lands on
the platform default `general` (Opus 4.8; observed on 2.225.14,
not re-verified on 2.348.22) — the tier the fallback YAML pins
as well. The multi-model story stays: clerk
on `fast`, merge agents on `workflow`, `reasoning` in the model
benchmark — three tiers live, four model families once the
benchmark is counted.

**"Math evaluation error" strings in a report**: the planner
used «math» embeds that the renderer cannot evaluate. Fixed by
the PLAIN MARKDOWN rule in the three reporters' prompts and in
the entrypoint templates the Orchestrator now writes from; if a
string like this reappears it is cosmetic — the numbers around
it are correct, read them.

**Failing data tools**: `create_sqlite_db`,
`query_data_with_sql`, `jmespath` and `append_to_artifact`
fail on this platform (`tool_error` in Activities; observed on
2.225.14, not re-verified on 2.348.22). Signature:
an analyst that converts a result into SQLite or JMESPath and
stalls or loops. The prompts steer away from them — the
analyst's rule 13 (SPEED RECIPES: one small aggregation per
question, never convert results, never fetch to count) is the
reason the total-loss answer takes ~20 s instead of minutes. A
live-built analyst WITHOUT rule 13 wanders into these tools —
that is what the Builder prompt's DATA SHAPES / BEHAVIOR RULES
blocks guarantee; if a Builder run dropped them, break glass
(`cd fallback && sam config apply` redeploys the reference
prompt).

**UTF-8 in the cockpit** (fixed): the cockpit decodes the
solclientjs message attachments as UTF-8; the earlier signature
was mojibake for umlauts and dashes in the report panels. If it
reappears after a cockpit edit, check the attachment decoding
before anything else.

**Hidden-tab throttling**: browsers throttle the timers of a
hidden tab — the FNOL burst crawls, the cockpit clock lags and
the scheduled events (T+0:25, T+5:00, T+8:00) drift. Keep the
cockpit in its own window, visible on stage (pre-flight item 6);
never run it as a background tab of the SAM UI window.

Builder failure signatures (all observed on the manufacturing
demo 2026-08-11 on SAM 2.225.14, and the reason the connectors
are pre-provisioned so the live build creates ONLY the agent):

- Name normalization: "StormIntakeAnalyst" without spaces,
  connector "acme-claims-mongodb". The workflows and the
  Orchestrator prompts reference the EXACT name
  "Storm Intake Analyst" — in the Review step before deploying,
  check the name field and correct it, otherwise the intake
  sections of all three reports name the peer as missing.
- Connector sub-task hallucination: when the Builder fans
  connector creation out to parallel sub-tasks, one can claim
  "MongoDB is not supported (only DynamoDB, Neo4j, Neptune)".
  It IS supported (`document_db`/`mongodb`, flagged
  experimental on 2.225.14 and still on 2.348.22) — the
  fallback configs prove it. With the agent-only build this
  path no longer exists.
- "Couldn't confirm full validation — deploy stays disabled
  until it succeeds" (2.225.14; the validation loop behind it
  re-verified on 2.348.22 on 2026-09-21, the deploy gate itself
  not -- Build & Activate was not clicked on 2.348.22): the
  deploy gate reflects the LAST validation result. The full
  validation passes when (a) the three connectors are manifest components with origin:
  platform / status: deployed AND (b) the agent config declares
  `connectors` at the APP level, as a sibling of app_config.
  Inside app_config the schema rejects the field — that
  one-level difference caused every earlier failure and
  flip-flop. The prompt mandates the exact structure; full
  validation is expected GREEN. If the banner still appears:
  one "rerun validation" in the Builder chat, and if the gate
  stays red, break glass (`cd fallback && sam config apply`)
  and continue at 2.4.
- A long pasted prompt may be attached as a `snippet.txt` file
  instead of inline text — harmless, the Builder loads it.
- Connectors-field flip-flop (2.225.14, still the case on
  2.348.22 -- re-verified 2026-09-21): the cross-component
  validator demands a connectors declaration, the app_config
  schema rejects the field INSIDE app_config, and the Builder
  oscillates between adding and removing it. The way out: the
  field belongs at the APP level — the prompt states the exact
  placement.
- **Builder pauses after the plan / writes the manifest first**
  (2.348.22, verified 2026-09-21): the Builder may stop at
  "Here's the build plan for your review" instead of building
  -- reply in ONE line "Approved - build it now exactly as
  specified, no further questions." and it builds without
  asking again (manufacturing prompt). A component config now
  only validates once `build_manifest.yaml` exists in the
  session; if the Builder validates the agent config first it
  gets "No build_manifest.yaml exists in this session", writes
  the manifest and continues on its own (insurance prompt) --
  no action needed, it costs one extra round.
- Toolset loss: one manufacturing run deployed with no runtime
  tools beyond the connector queries (no artifacts, no charts).
  Root cause: the tool groups never made it into the agent
  config. With the prompt's TOOLSETS block (builtin-group
  entries via `tool_name`, not `group_name`) the tools reach
  the runtime (on 2.348.22 both `tool_name` and `group_name`
  validate; the prompt keeps `tool_name`). CAVEAT: the
  platform's Toolsets field in Agent Management shows EMPTY
  either way — judge by the plan card / awe logs, never by
  that field (observed on 2.225.14; not re-verified for
  Builder-built agents on 2.348.22).
- **Stale agent card after delete + rebuild** (observed
  2026-08-12 on SAM 2.225.14; not re-verified on 2.348.22,
  where an agent DELETE also removes the agent's broker
  queue): after the analyst is deleted and rebuilt (exactly
  the live Builder sequence), the mesh can keep the DELETED
  instance's agent card; name-based resolution then hits the
  dead instance — symptom: WARN "multiple agent cards advertise
  the same display name" in the awe log plus "peer tool
  unavailable" on the intake node/delegation, while fail_fast
  keeps the run alive with a noted gap. Fix (~1 min):
  `kubectl rollout restart deployment
  agent-mesh-solace-agent-mesh-awe -n sam-solace-lab` — all
  live agents re-register, stale cards vanish. Worth a
  pre-flight glance after any rebuild rehearsal.

Builder Test tab: works since 2.348.22 (on 2.225.14 its test
plan was killed after 30 s). The first test plan after every
`str` start takes about 90 s, later ones about 4 s -- warm it up
once in the pre-flight before it goes anywhere near the stage;
this script does not need it.

Knowledge base specifics: the `Acme Claims Knowledge` connector
is an `mcp/remote` connector pointing at
`http://host.docker.internal:8765/mcp`; the MCP server embeds
queries with a local model that is downloaded once into the
`acme-knowledge-models` volume. After `uninstall.sh` (which
removes that volume) the first `install.sh` waits for the
download — budget two extra minutes. If the Knowledge Expert
answers "tool unavailable", check `curl localhost:8765/health`
and `docker compose -f qdrant/docker-compose.yaml ps` before
anything else.

Artifact pass-through: charts rendered by a delegated agent
(e.g. the analyst's conversion chart) live in THAT agent's
session; the merge report references them but may not embed
them, and the final answer says so transparently. Not a bug to
apologize for on stage — if asked, open the analyst's task in
Activities and show the chart there ("every artifact is
session-scoped and auditable").

Demo-clock contract: the fiction lives in July 2026 ("today" =
Monday 2026-07-20 10:00; the cell on Saturday 2026-07-18; BaFin
day 20 = 2026-08-08; payment run Friday 2026-07-24). Every
business timestamp in the cockpit's payloads — `detected_at`,
`window_start` / `window_end`, `scanned_at`, `reported_at` — is
that frozen Monday fiction, written as a UTC instant exactly as
the seeds store it. Only `published_at` carries the real time of
the click, and only for the broker trace. The agents therefore
never reconcile two clocks: ages and deadlines are computed
against the data snapshot pinned in their prompts, never
against NOW() and never against `detected_at`. If asked: "the
dataset is a frozen Monday morning and the event stream speaks
the same clock — the wall clock only rides along in
`published_at` for the audit trail."

Merge agents may WARN with a pseudo-tool `_continue_generation`
(observed on the manufacturing Quality Incident Reporter): the
model tries to continue a long answer via a tool that does not
exist. NOT fatal — the task completes and the report is
delivered. Only if a report visibly ends mid-sentence, tighten
the "under 30 lines" rule in the merge agent's prompt (workflow
variant) or in the entrypoint template (event path).

The Builder depends on the external LLM gateway
(lite-llm.mymaas.net): a transient upstream 502 surfaces as
"The AI provider returned an unexpected HTML response (HTTP
502)". On stage: retry ONCE, and if it fails again switch to
the break-glass without commentary —
`cd fallback && sam config apply` (NEVER `--prune`) creates the
Storm Intake Analyst + connectors in seconds and the demo
continues at "Review, deploy, first task".

Regulatory colour is colour, not data: the BaFin 30-day rule,
the EU AI Act Article 50 transparency and human-oversight
obligations (in force since 2026-08-02), DORA and the GDV fraud
principle appear in the SAY blocks and in the knowledge base's
guideline texts (CG-BAFIN-30, CG-FR-5); Allianz's Project Nemo,
the 11,000-claim hail event with first-contact triage and the
"Fastlane Total Loss" are context from public research and
never appear in Acme's data.
