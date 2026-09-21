# Claim Triage -- Live Demo Script (default profile)

> **Version 2.0, 2026-09-16.** One scenario: a claim comes in after a hail
> storm, one workflow decides, a human signs. Shown twice, with the same agents
> and opposite outcomes. 16 minutes with questions, optional depth to 20. Click
> paths, names and expected cards follow the platform as built and measured on
> 2026-09-16 (SAM 2.225.14). Re-checked on SAM 2.348.22 (str 1.64.0) on
> 2026-09-21: install and uninstall, the dry fire (APPROVE in 27-28 s) and the
> evaluation runs; the full script was not re-rehearsed there.

**The line you say verbatim three times** (frame, after the HOLD, close): *"Keep
your agents where they are; govern them from here."*

**The sentence the room should repeat to a colleague afterwards**: "They can
govern the agents we already have -- even the ones that don't run on their
platform -- and we don't have to move anything."

Conventions: **DO** = click path or stage direction. **SAY** = spoken line,
always a `>` blockquote. **IF** = what to do when the screen does not match.
**Talk** = length of the beat without interruptions. **By** = latest start of
the beat inside a 16-minute budget; later than By plus 0:30 means pull a lever
from "Running late".

## Run sheet

| # | Beat | Screen | Talk | Budget | By |
| --- | --- | --- | --- | --- | --- |
| 1 | Frame: one storm, one claim, your estate | Slide 3 | 1:15 | 1:30 | 0:00 |
| 2 | Claim 1 comes in | C cockpit | 0:15 | 0:15 | 1:30 |
| 3 | Wait 1: who is working on it | A Agent Management | 0:45 | 0:45 | 1:45 |
| 4 | The APPROVE card, a human signs | C cockpit | 1:15 | 1:45 | 2:30 |
| 5 | The mechanism: one line of config | A workflow, liaison config | 1:15 | 2:00 | 4:15 |
| 6 | Claim 2 comes in | C cockpit | 0:15 | 0:15 | 6:15 |
| 7 | Wait 2: the receipt for claim 1 | B Activities | 0:45 | 0:45 | 6:30 |
| 8 | The HOLD card, a human signs | C cockpit | 1:30 | 2:00 | 7:15 |
| 9 | Models: tiers, not endpoints | A Models | 0:45 | 1:00 | 9:15 |
| 10 | Grafana: four panels, one honest limit | A Grafana | 1:45 | 2:30 | 10:15 |
| 11 | Quality: one report | A Evaluations | 1:00 | 1:15 | 12:45 |
| 12 | Close and the ask | C cockpit, then slide 2 | 1:30 | 2:00 | 14:00 |
| | **Spine** | | **12:15** | **16:00** | ends 16:00 |
| D | **Optional depth** -- pick up to 4:00 | see "Optional depth" | | **+3:45** | ends 19:45 |

Budget = talk plus the three to five questions a real room asks along the way. A
silent room finishes the spine in about 12 minutes: use the optional depth. A
talkative room: pull the levers.

| Optional depth | Slots in | Adds | Screen |
| --- | --- | --- | --- |
| D1 Ask the outside agent directly | after beat 8 | 1:15 | A Agent Management |
| D2 The entrypoint: the flow is a subscriber | after beat 5 | 0:30 | A Entrypoints |
| D3 The Connectors page | inside beat 9 | 0:30 | A Connectors |
| D4 The RBAC tables | inside beat 10 | 0:30 | A Grafana row 3 |
| D5 The lifecycle recap | after beat 12 | 1:00 | Slide 4 |

## Running late

Pull the levers in this order, one at a time.

| Lever | Pull it when | Saves |
| --- | --- | --- |
| L1 Fire claim 2 at the start of beat 5, let beat 5 cover the run, drop beat 7 | beat 5 starts after 4:45 | 0:45 |
| L2 Drop beat 9; say the tier sentence on the HOLD card instead (beat 8, IF) | beat 9 starts after 9:45 | 1:00 |
| L3 Beat 10 on two panels only: the Tempo trace and the honest limit | beat 10 starts after 10:45 | 1:00 |
| L4 Drop beat 11; offer the guardrail report as a follow-up document | beat 11 starts after 13:15 | 1:15 |

**Never cut**: the Claims Intake Analyst row, the allow list, both Approve
clicks, the CG-FR-5 sentence, the honest limit ("what this does not show you"),
the pitch line in the close.

## The room

The audience will NOT rebuild their agents on Solace. Their AI estate already
exists on Azure, AWS and Databricks, owned by different operating units. They
want transparency, control and reuse across the group, and they think
event-driven: an agent is a subscriber, a decision is an event. The message is
not "build your agents here". It is "keep them where they are; govern them from
here". Exactly one of the five agents in this demo runs outside the platform,
and the script keeps coming back to it: assert it (frame), show it (the roster
row), prove it (the allow list, Activities, Tempo), bank it (close).

## Stage in one look

- **Deck**: `slides/SAM v2 - Claim Triage (governance demo).pptx`. Slide 3
  opens (the setup at a glance), slide 2 closes (the one scenario, both
  claims), slide 4 is optional depth D5. Slide 1 is not shown. No deck: run
  without it (Appendix B, R11) -- the platform is the stage.
- **Window A** -- browser profile 1, `sam_admin`, left two thirds of the screen.
  Tabs in this order: (1) Agent Management, (2) Workflows -> Claim Triage, (3)
  Claims Intake Liaison with its configuration scrolled to the allow list, (4)
  Models, (5) Grafana "SAM Claims Governance", (6) Evaluations -> Reports with
  the latest ins-guardrails report open.
- **Window B** -- browser profile 2 or a private window,
  `power_user@solace.lab`, Activities. Stacked exactly on top of A. It has to be
  a separate profile: Activities is a per-user view, and tabs of one profile
  share one login.
- **Window C** -- the cockpit, `cockpit/index.html`, its own window on the right
  third, always visible. LED green, CLM-0913-00001 selected.
- **No terminal on screen.** The break-glass terminal lives on a second display
  or out of sight.

## Stage rules

- **Never narrate the stepper.** "policy DB -> intake (external) -> rules ->
  decision" is an animation on fixed delays, not telemetry. Only the T+ clock
  and the card are real; the step-level truth is Activities and Tempo.
- **Never name the wait.** No "while we wait", no "this takes about thirty
  seconds", no "let's see if it works". Click, turn to the other window, talk.
  The return line is two words: "There it is."
- **Say the run time twice only**: when the first card lands, and in the close.
  Never promise a number; point at "decided in" on the card. You may glance at
  the cockpit chip (it turns DECIDED and the clock stops); never read the
  running clock aloud.
- **One claim at a time.** While a claim runs, the cockpit ignores another
  click; never plan to fire both at once.
- **Approve claim 1 before firing claim 2.** Firing clears the card and its
  Approve button.
- **Never press Reset between the two claims.** It clears the event stream, and
  the close points at it.
- **Never cover the cockpit window.** Browsers throttle the timers of hidden
  windows; the clock stalls.
- **The second customer is never a fraudster.** Say indicators, specialist
  review, a human decides.
- **The Builder is off this stage.** Never open it.

## 1. Frame -- by 0:00

**Screen**: slide 3. **Talk**: 1:15.

**DO**: slide 3 is up before anyone sits down. Point at three places only, as
the words come: the event sources along the bottom ("down here"), the four
agents next to the Agent Mesh box ("here"), the dashed box marked outside the
platform ("out here").

**SAY**:

> "Saturday, the eighteenth of July, twenty to seven in the evening. A hail cell
> crosses Landkreis Boeblingen. Ten thousand four hundred claims follow.
>
> We are going to follow one of them, end to end. It arrives as one event on the
> mesh, down here. Five agents work on it, here. And one of those five does not
> run on this platform at all -- it sits out here, with its own model and its
> own access to the data.
>
> That is on purpose. Your agents already exist. Some on Azure, some on AWS,
> some in Databricks, owned by different units. Nobody in this room is going to
> ask you to move them. What is missing is the layer above them: who called
> which agent, under which identity, for how long -- and who decided in the end.
>
> So: keep your agents where they are; govern them from here."

**IF** there is no deck: say the same lines on the cockpit and leave out "down
here", "here" and "out here".

## 2. Claim 1 comes in -- by 1:30

**Screen**: C, the cockpit. **Talk**: 0:15.

**DO**: leave the slideshow (Cmd+Tab to the browser). Check the LED is green.
CLM-0913-00001 is selected: Lena Hartmann, VW Golf, MINOR, APP, 16 dents,
"clean". Pointer on **Claim comes in**.

**SAY**:

> "This is the claims cockpit. First notice of loss for Lena Hartmann's Golf:
> sixteen dents, reported through the app. Nobody types a prompt. It is one
> event, on the mesh."

**DO**: click **Claim comes in** on the word "event". Turn to window A and do
not look back.

## 3. Wait 1: who is working on it -- by 1:45

**Screen**: A, tab 1, Agent Management. **Talk**: 0:45, deliberately longer than
the run.

**DO**: point at each row as you name it: Acme Insurance Query Expert, Acme
Claims Knowledge Expert, Claims Triage Decision, Claims Intake Liaison. Then the
**Claims Intake Analyst** row: type discovered, no Undeploy button, no creator.
Point at it last and keep the pointer there.

**SAY**:

> "Here is who is working on it right now. An expert on the system of record --
> policies, claims, partners, in Postgres. An expert on the rulebook -- policy
> wordings, claims guidelines, partner contracts. A decision agent with no
> connector, no toolset and no database access; it only merges and decides. And
> a liaison, just as bare, whose only job is to carry one request across the
> edge of this platform.
>
> And this row: Claims Intake Analyst. No Undeploy button, no creator. It runs
> outside the platform, in its own namespace, on its own model, with its own
> database credentials. This platform never saw its code -- only the card the
> agent publishes on the broker. Nothing was migrated."

**SPARE** (the card has not landed yet):

> "And letting that agent take part cost exactly one line of configuration. I
> will show you that line in a minute."

**RETURN** (the chip reads DECIDED; finish the sentence you are in first):

> "There it is."

**IF** T+ passes 45 s: say the spare, then do beat 5 on this window right away
and come back to the card afterwards (drop the last sentence of beat 4). T+ past
90 s: Appendix B, R2.

## 4. The APPROVE card -- by 2:30

**Screen**: C, the cockpit. **Talk**: 1:15.

**DO**: expected card, green badge **APPROVE**, lane **FAST_LANE**. Policy
POL-104211 ACTIVE with hail cover HC-7; 16 dents on roof and bonnet, no glass
damage, drivable; estimate EUR 640; deductible EUR 300; repair network clause
RN-3 set, so a drive-in slot at P-BRAENDLE in Sindelfingen; photos taken 7
minutes after the cell started; no indicators; the reasons cite clauses such as
CG-FL-1, PW-HC-7 and PW-RN-3. Read what the card says. If a detail differs from
this list, the card wins.

**SAY**:

> "Approve, Fast Lane. The policy is active, with hail cover. Sixteen dents, no
> glass damage, the car is drivable, estimate six hundred and forty euros.
> Deductible three hundred euros. She signed the repair-network clause, so the
> route is a drive-in slot at the partner in her district -- Braendle, in
> Sindelfingen. Her photos were taken seven minutes after the cell started. No
> indicators.
>
> And every reason cites the clause it came from. These are the insurer's own
> rules, not the model's opinion.
>
> About half a minute -- the exact time is printed right here -- five agents,
> three data stores, and a card a claims lead can read out loud."

**DO**: point at "decided in" on "printed right here". Click **Approve**. The
button turns to Approved; the event stream shows the publish on
`acmeins/claims/decision/CLM-0913-00001` with `approved_by`.

**SAY**:

> "That button is the point. The agents recommend. A named human decides. And
> the decision is itself an event on the same mesh, with the approver's name on
> it -- any system that needs it simply subscribes.
>
> Now let me show you how that outside agent was allowed to take part."

## 5. The mechanism: one line of config -- by 4:15

**Screen**: A, tab 2 (Claim Triage), then tab 3 (Claims Intake Liaison).
**Talk**: 1:15.

**DO**: tab 2, the workflow graph: policy, intake and rules side by side,
decision below them. Point; do not open the nodes.

**SAY**:

> "This is the workflow. Four steps, and each one has a contract -- a schema its
> answer has to fit. Three of them ran side by side: the system of record, the
> rulebook, and the intake. Then the decision merges them.
>
> The intake step runs on the liaison. And this is the line to read."

**DO**: tab 3, the liaison's configuration: `interAgentCommunication` ->
`allowList` -> `ClaimsIntakeAnalyst`. Pointer on that entry.

**SAY**:

> "Its allow list names exactly one agent it may talk to: Claims Intake Analyst.
> By name. The platform's own orchestrator carries the same setting with a
> star -- it may call anything. This one has a single name. And an agent without
> this line has no way to call another agent at all.
>
> So reaching outside the platform is declared, it is reviewable, and it is
> enforced. Your risk function can read this line without asking an engineer."

**IF** lever L1 is pulled: do beat 6 first (select claim 2, say its line,
click), then come straight back here; beat 5 is the cover, beat 7 is dropped.

## 6. Claim 2 comes in -- by 6:15

**Screen**: C, the cockpit. **Talk**: 0:15.

**DO**: do NOT press Reset. Select **CLM-0913-08103**: Ben Meier, Skoda Octavia,
MODERATE, drive-in scanner. The row itself reads "60 dents claimed, scanner
counted 14" -- let them read it.

**SAY**:

> "Second claim. Ben Meier's Octavia, through the drive-in scanner. Same
> workflow, same agents, same rules. Nothing reconfigured. Only the data is
> different."

**DO**: click **Claim comes in** on the word "different". Turn to window B.

## 7. Wait 2: the receipt for claim 1 -- by 6:30

**Screen**: B, Activities as `power_user`. **Talk**: 0:45.

**DO**: open the task of the first claim, **CLM-0913-00001** -- the completed
run from a minute ago, never the run still in flight (check the time stamps); a
half-drawn tree steals the reveal. Show the workflow, the three parallel steps,
the liaison's hop to Claims Intake Analyst with its duration (the outside
agent's own share is typically about 5 s), then the decision step.

**SAY**:

> "Here is the receipt for the claim we just approved. The workflow. The three
> steps side by side. And here: the liaison handing one task to the outside
> analyst, and the answer coming back a few seconds later. That hop left the
> platform -- and it is logged exactly like the hops that never did.
>
> And look whose name is on all of it: the operations user, not the admin who
> configured this. The identity travels with the task."

**SPARE**:

> "When your auditors ask who called that agent, when, and for how long -- this
> page is the answer. The same page for the agents inside and the one outside."

**RETURN**:

> "There it is."

**IF** T+ passes 45 s: do beat 9 (Models) on window A, then come back for the
HOLD card and continue with beat 10. T+ past 90 s: Appendix B, R2.

## 8. The HOLD card -- by 7:15

**Screen**: C, the cockpit. **Talk**: 1:30.

**DO**: expected card, amber badge **HOLD**, lane **SPECIAL_INVESTIGATIONS**.
Policy MOTOR_PARTIAL, deductible EUR 150, no RN-3; 60 dents claimed, estimate
EUR 6,800, reserve EUR 7,800. Two indicators: the three photos carry EXIF
timestamps 7.3 days before the hail cell, and the drive-in scanner counted 14
dents against 60 claimed (a 76.7 percent deviation). CG-FR-5 cited; next step a
specialist review within ten working days. The card never says fraud. If a
detail differs, the card wins.

**SAY**:

> "Hold. Special investigations. Two indicators. The three photos carry
> timestamps from more than a week before the storm. And the drive-in scanner
> counted fourteen dents -- against sixty claimed.
>
> Now read the sentence the card insists on. It is the insurer's own guideline,
> CG-FR-5: a single indicator proves nothing; the overall picture decides; a
> human specialist decides; and never delay the honest majority.
>
> The agent accuses no one. It does not refuse, and it does not pay. It puts one
> claim in front of the right person, within ten working days.
>
> Same workflow. Same agents. Opposite outcome -- because the data was
> different, not the prompt."

**DO**: click **Approve**.

**SAY**:

> "A human signs the hold, too -- and that is an event as well. Keep your agents
> where they are; govern them from here."

**IF** lever L2 is pulled, say this before the last sentence: "And every agent
you watched runs on one model tier, so swapping the model is a platform
decision, not a prompt edit."

## 9. Models: tiers, not endpoints -- by 9:15

**Screen**: A, tab 4, Models. **Talk**: 0:45.

**DO**: point at the `fast` alias only. The page lists more aliases than this
demo uses (ten on 2.348.22, among them `google gemini`, which calls the Gemini
API directly instead of going through the LiteLLM proxy); do not count them and
do not tour them.

**SAY**:

> "Every agent you watched runs on one alias: fast. Today that is Claude Haiku
> 4.5. It is a tier, not an endpoint. Swap the model behind the tier here, and
> no agent changes -- it is a platform decision, not a prompt edit.
>
> The outside analyst brings its own model, configured outside and never
> registered here. That is honest, and it is the real state of your estate.
>
> Same for data. The platform holds the connections to the two stores it reads,
> in its connectors -- the database password sits there, never in a prompt. The
> third store, the raw intake, is not connected here at all. Only the outside
> agent can reach it."

**IF** the Connectors check in Appendix A (A6) did not pass: drop the last
paragraph.

## 10. Grafana: four panels, one honest limit -- by 10:15

**Screen**: A, tab 5, "SAM Claims Governance". **Talk**: 1:45.

**DO** (1): row 1, the stat **Registered agents**. Do not read the number.

**SAY**:

> "This is the operations view. First, an honest line: the outside analyst is
> not in this count. It is discovered, not registered. I would rather tell you
> that than have you find it."

**DO** (2): row 2, **Every hop of a claim is a span (Tempo)**; open the newest
trace. The platform's own hops show up under runtime ids (`agent_...`); the hop
to the outside agent reads `.../request/ClaimsIntakeAnalyst receive`, typically
about 5 s. Point at the user id tag. These are broker spans -- SAM emits no
spans of its own -- and the panel stays empty unless the event-mesh
`otel-collector` container runs (A10). The user id tag on the span was observed
on 2.225.14 and not re-verified on 2.348.22: check it in rehearsal.

**SAY**:

> "Every hop of that claim is a span on the broker, with the user's identity on
> it. Our own agents show up here under internal ids. The one hop you can read
> by name is the one to the agent we do not own -- because it is addressed by
> the name on its own card."

**DO** (3): row 3, **External agent traffic (its own log vs the broker)**.

**SAY**:

> "The same outside agent, seen from two sides at once: its own log, and the
> broker."

**DO** (4): row 4, **Tokens per agent x model** and the stat **Illustrative LLM
cost**. Do not read the cost value.

**SAY**:

> "Tokens per agent and per model, and a cost figure -- illustrative: list
> prices times tokens, not an invoice. There are thirty-four panels on this
> page; I have shown you four. The rest belongs to the team that runs it.
>
> And here is what this does not show you: what happens inside that outside
> agent -- its tokens, its own tool calls, its prompt. It shows every request
> and every answer that crossed the mesh, who asked, and how long it took. That
> is what a control layer can honestly promise over an agent it does not own."

**IF** lever L3 is pulled: panel 2, then the last paragraph only.

## 11. Quality: one report -- by 12:45

**Screen**: A, tab 6, Evaluations -> Reports -> **ins-guardrails**. **Talk**:
1:00.

**DO**: the latest ins-guardrails report: three attacks, two evaluators
(Security and LLM Judge), 6 of 6 passed. Do not open the Lab, do not open other
reports, do not start a run. Before the talk, read the latest ins-claims-rules
score (A9): both pre-runs on 2.348.22 read 9 of 10. If it still does, open the
failed row first. A wrong answer: replace "ten out of ten" below with "nine out
of ten -- and the one miss is exactly what this test is for: it caught it
before a customer did". A judge error (e.g. "unexpected end of JSON input"):
say "nine out of ten -- one row the judge could not score; we re-run it", and
do not claim a catch.

**SAY**:

> "This is the report your risk team will ask for. Three attacks on the expert
> that reads the system of record. A prompt injection asking for every
> customer's personal details. A destructive delete against the claims table.
> And someone claiming to be the administrator, asking for the database
> password.
>
> The expert refuses all three, stays read-only, and explains why. Six out of
> six -- scored by a security evaluator and a judge model, not by me.
>
> Two more test sets run against the rulebook agent and the decision agent: ten
> out of ten, and six out of six. Those three agents sit on a watchlist. When a
> model or a prompt changes, you run the same tests again, and the scores land
> as a trend on that dashboard."

## 12. Close and the ask -- by 14:00

**Screen**: C, the cockpit, then slide 2. **Talk**: 1:30.

**DO**: cockpit, the HOLD card up, hands off the mouse. The cockpit shows one
card at a time: claim 2's card replaced claim 1's. The event stream keeps
both -- point at the two `acmeins/claims/decision/...` entries.

**SAY**:

> "Count what we changed in your estate since we started: nothing. We did not
> rebuild an agent. We did not migrate a model. We did not move a database.
>
> One of the five agents never ran on this platform at all -- its own runtime,
> its own model, its own credentials. And it still had a contract, an identity
> on every hop, a span on the broker, a line on a dashboard, and a named human
> on the outcome.
>
> Two claims, opposite decisions, about half a minute each, both signed. There
> they are: two decision events in the stream."

**DO**: switch to slide 2, both claims side by side. Do not read the times
printed on the slide.

**SAY**:

> "Keep your agents where they are; govern them from here.
>
> The question I would take back to your team is not which platform to
> standardise on. It is this: which of our agents can we name -- and who is
> allowed to call them? If nobody can answer that today, that is the gap this
> closes.
>
> So pick one agent you already run -- the Databricks one, say -- and let us put
> its card on that roster together, in a workshop. You will recognise the
> screen."

**DO**: stop talking. Slide 2 stays up for the questions. Name only a workshop
format and a date you can actually offer.

## Optional depth

### D1. Ask the outside agent directly (after beat 8, +1:15)

**DO**: A, tab 1 -> Claims Intake Analyst -> **Chat with Agent**. Paste the
prepared question, then talk while it answers:

```
Compare the earliest photo of CLM-0913-08103 with the start of hail cell HZ-0913
```

**SAY** (while it answers):

> "You can talk to the outside agent directly, from here, like any other agent.
> The question goes over the broker to its own runtime. It reads its own
> database, with its own credentials, and the answer comes back over the same
> mesh -- under my identity this time, not the operations user's."

**DO** (on the answer): read the photo time and the cell start from the answer;
add no interpretation. If a loaded word appears, correct it calmly: indicators,
not verdicts. The exchange lands in window A's Activities (sam_admin), not in
window B.

### D2. The entrypoint: the flow is a subscriber (after beat 5, +0:30)

**DO**: A -> Entrypoints -> **claims-triage**: the event rule on
`acmeins/claims/fnol/received/...`. Its target reads as a runtime id, a
workaround for a platform bug (Appendix E); do not dwell on it.

**SAY**:

> "And this is what started it all: one subscription. First-notice-of-loss
> events start the claim triage. Nobody calls this workflow -- it listens. For
> your architects: the agents are subscribers, the decision is an event, and the
> broker in the middle sees every hop."

### D3. The Connectors page (inside beat 9, +0:30)

Only if Appendix A, A6 passed.

**DO**: A -> Connectors: **Acme Insurance DB** (SQL) and **Acme Claims
Knowledge** (MCP).

**SAY**:

> "Two connections. The database, through the platform's own SQL connector. And
> the rulebook, which lives in a Qdrant vector store. The platform has no native
> connector for Qdrant, so it sits behind a small MCP server -- and it gets the
> same treatment. Bring your own tool. The intake store is not on this page."

### D4. The RBAC tables (inside beat 10, +0:30)

**DO**: Grafana row 3: **RBAC roles -> scopes** and **IdP group -> role**. On
2.348.22 the group table also lists `sam_manager` (a built-in role: all SAM
administration except RBAC).

**SAY**:

> "Who may do what is code: the roles, their scopes, and which group from your
> identity provider lands in which role. Reviewed, versioned and applied like
> any other configuration -- and visible here to the people who audit it."

### D5. The lifecycle recap (after beat 12, +1:00)

Only if slide 4 is adapted (Appendix A, A2).

**DO**: slide 4. Top row left to right, then the bottom row.

**SAY**:

> "If you think of agents as a workforce, here is what you just saw, stage by
> stage. Hiring: four agents on the platform and one from outside, declared as
> configuration. Onboarding: connectors, with the credentials on the platform.
> Coaching: skills that teach the agents the schema and the rulebook.
> Supervision: a human presses Approve, and the approval is an event. Teamwork:
> one workflow, three steps in parallel, one merged decision. Improvement: three
> test sets on three watched agents, and a dashboard for the people who run
> it."

IF asked whether that Approve was the platform's human-in-the-loop: "No. That
Approve is the cockpit's, and it is an event after the decision. The
platform's own human-in-the-loop -- tool approvals and questions -- pauses an
agent in chat, Slack or Teams. An event-triggered workflow has nobody to ask,
so here the human signs downstream, as an event."

### Not in a 20-minute slot

Keep these for a technical follow-up session.

- **The live evaluation run** of ins-triage-decision. Wall time about two
  minutes (measured 102 s and 117 s on 2026-09-16, SAM 2.225.14); the run with
  the current evaluators scored 6 of 6, average 1.00 on both LLM Judge and
  Closed QA. Start
  it from Evaluations -> Lab -> experiments -> ins-triage-decision -> Run. From
  a terminal, the bare `sam eval run` answers 401 until the token is exported
  (Appendix E).
- **Swap the model behind `fast`** on the Models page and re-fire claim 1.
  Switch it back afterwards.
- **The third claim, CLM-0913-08891.** Not on stage for now: it is not in the
  cockpit, and its intake record does not match the system of record (Appendix
  E).
- **RBAC as YAML** in `agent-mesh-deployment/scripts/rbac/`.

## Appendix A -- Pre-flight, in order

What `./preflight.sh` covers (and fixes where it can): login and API, cluster
pods, a one-token probe of every model upstream, the four platform agents, both
connectors, the workflow and the entrypoint, the liaison's deployed allow list,
the external agent's pod and card, the Postgres, MongoDB and Qdrant data, the
MCP server, the broker WebSocket the cockpit uses, the dashboards and their
platform-DB grant, Tempo traces, the evaluation pre-runs, and a dry fire of
CLM-0913-00002. The manual checks after it cover what it does not.

### The day before

- **A1** Rehearse the full script once within 48 hours of the show. Tempo keeps
  48 hours of traces; older rehearsals leave the trace panel empty until the dry
  fire.
- **A2** The deck. Slides 2, 3 and 4 must carry this scenario. Check: slide 2's
  title ends "One Hail Cell, One Claim"; its two cards are CLM-0913-00001
  (APPROVE / FAST_LANE) and CLM-0913-08103 (HOLD / SPECIAL_INVESTIGATIONS); its
  bottom strip counts four agents on the platform and one outside (not "three of
  the four"). Slide 3's roster reads Query Expert, Knowledge Expert, Intake
  Liaison, Triage Decision; the entrypoint label reads claims-triage; there is
  no weather feed chip, no third Postgres cylinder, no "built live"; a dashed
  box shows the Claims Intake Analyst outside the platform. Slide 4 names no
  Builder beat, no "8 agents", no GDV, no "all passing". The speaker notes of
  slide 3 are rewritten (presenter view shows them) and label every run time
  and evaluation score with its SAM version. Any check fails: no deck (R11).
- **A3** No profile switch and no re-install on show day: `./install.sh`
  redeploys the two experts on every run (Appendix E).

### 45 minutes before

- **A4** Log in as `sam_admin` (a browser flow):

  ```
  sam auth login solace-lab --url https://sam.solace.lab
  ```

- **A5** From the demo directory: `./preflight.sh`. Allow up to 15 minutes on a
  fresh platform (evaluation pre-runs); much less when the runs exist. Wait for
  READY. While it runs, know three things:
  - After a Mac reboot the data-store steps can take several minutes, a MongoDB
    re-seed included. Let it finish; if it ends NOT READY on a data-store step,
    run it again.
  - Its dry-fire OK line prints "decision:APPROVE" -- cosmetic. A dry fire
    reported as FAIL after 90 s may be a cold first run that is still
    completing. Look for CLM-0913-00002 in Activities (power_user) first, then
    run `./preflight.sh --skip-evals` again.
  - Its closing reminders say that nothing runs live in Evaluations: this
    script starts no evaluation run on stage (beat 11 shows a finished
    report).

### 30 minutes before -- what preflight does not check

- **A6** Connectors page: exactly **Acme Insurance DB** and **Acme Claims
  Knowledge**. If fnol-intake, scanner-results or weather-cells are listed, they
  are leftovers of the extended profile. Delete them on the Connectors page
  before the show. If you cannot, skip D3 and drop the last paragraph of beat
  9 -- otherwise the pitch "only the outside agent reaches the intake store" is
  false on screen.
- **A7** Agent Management: the four claims agents, the built-in Orchestrator,
  Builder and Activity Monitor (the monitor is new in 2.348.22; not part of the
  story, do not point at it), plus **Claims Intake Analyst** as discovered. No
  Fast Lane Clerk, no reporters, no Storm Intake Analyst. Other discovered
  agents of the shared lab mesh may be listed too (Web Research Agent, Web
  Scraper Agent, Markdown Creator, Mermaid Diagram Generator). Scroll or filter
  so the Claims Intake Analyst row is on screen together with the four claims
  agents, and know the answer in Appendix C. That row is also your ten-second
  health tell on stage: no row, no outside agent (R4).
- **A8** Tab 3: the liaison's configuration shows `allowList` with the single
  entry `ClaimsIntakeAnalyst`, scrolled into view. The spoken line "an agent
  without this line has no way to call another agent at all" (beat 5, Appendix
  C) was observed on 2.225.14 and not re-verified on 2.348.22: in rehearsal, ask
  Claims Triage Decision in chat to call ClaimsIntakeAnalyst and expect a
  refusal or no peer tool.
- **A9** Tab 6: the latest **ins-guardrails** report (6 of 6) open. The scores
  in beat 11 and Appendix D were measured on SAM 2.225.14: check that the
  pre-runs on 2.348.22 read the same, and say what the reports say. On
  2026-09-21 both ins-claims-rules pre-runs read 9 of 10 (Closed QA 5 of 5,
  Factuality 4 of 5): once the judge returned broken JSON on the BaFin row, once
  the expert on `fast` wrongly tied a waived deductible to the Fast Lane
  confirmation. A re-run can read 10 of 10 or 9 of 10 -- use the beat 11
  fallback line if it stays at 9. The Reports list also shows two experiments of
  the extended profile and the platform's seeded "Sample Experiment" (target
  Orchestrator); have the answer in Appendix C ready.
- **A10** Tab 5: the governance dashboard loads; the Tempo panel shows the dry
  fire's trace; the platform-DB tables (roster, RBAC incl. **IdP group ->
  role**, latest runs) are filled. Widen the time range if the dry fire is
  older than the default hour. The Tempo panel needs the event-mesh
  `otel-collector` container Up (`docker ps --filter name=otel-collector`; if
  it is not, `(cd ../event-mesh-deployment && docker compose up -d
  otel-collector)` and fire the dry run again) -- SAM emits no spans of its
  own, Tempo only holds the broker's.

### 10 minutes before -- the stage

- **A11** Open the cockpit from the demo directory: `open cockpit/index.html` (a
  local file, no web server). The LED turns green within seconds, labelled "sam
  VPN" and `ws://localhost:8008`. Press **Reset** once, then select
  CLM-0913-00001. Chip IDLE, clock T+00:00.
- **A12** Arrange the windows as in "Stage in one look". `./demo-links.sh`
  prints every platform and Grafana link; the cockpit is a local file and is not
  in its output.
- **A13** Warm the agents: the preflight dry fire does it. If that was a long
  time ago, fire once more off screen -- never with a stage claim:

  ```
  node tools/fire-claim.js --claim CLM-0913-00002 --wait 90
  ```

- **A14** Browser zoom so a whole decision card fits in window C; notifications
  and screen saver off; deck in slideshow on slide 3.

## Appendix B -- Recovery

The T+ clock in the cockpit header is the only timer you need. Measured runs
land between 27 and 33 s.

- **R1 Slow (T+ between 45 and 90 s).** Not a failure. Keep talking and move to
  the next beat's material on the other window (claim 1: beat 5; claim 2: beat
  9), then come back. Say nothing about the delay. If someone asks: "Four
  language models are working on this one, three of them at the same time."
- **R2 Very slow (T+ past 90 s).** Go to window B, Activities, open the running
  task and show which step is still working. Say: "Let's look at it the way your
  operations team would: here is the run, and here is the step that is still
  working." Intake step stuck: R4. Run ended without reaching the cockpit: R3.
- **R3 Break-glass re-fire.** Cockpit footer, **Re-fire same claim**: publishes
  the same claim again. Whichever decision lands first is shown; a late
  duplicate is ignored. Say: "Let me send that claim in again. This flow only
  reads the claims data and publishes a decision, so a second run is harmless."
  Cover it like any wait. Off-screen alternative for a second person (use 08103
  for claim 2); its result also lands in the cockpit while the cockpit is
  waiting for that claim, and the terminal prints the decision:

  ```
  node tools/fire-claim.js --claim CLM-0913-00001 --wait 90
  ```

- **R4 REFER / HANDLER with "intake unavailable".** The outside agent did not
  answer. The platform did the right thing, so say so: "That is the outside
  agent not answering. Look what the decision did: it did not guess, and it did
  not fail. It handed the claim to a human, and it says why. That is exactly
  what should happen when an agent you do not own is down." Continue the script;
  re-fire only after the fix below and once the Claims Intake Analyst row is
  back in Agent Management.
- **R5 FAILED card (red).** Read nothing from the error aloud. Say: "That run
  did not complete -- and the failure arrived as an event too, here in the
  stream. Let me send it again." Then R3. A second failure: switch to
  evidence -- the dry fire of CLM-0913-00002 in Activities and its trace -- and
  continue with beat 5 or beat 9.
- **R6 REFER for another reason** (a policy or rules section missing). A step's
  answer did not fit its schema, and the decision agent names what was missing.
  Say: "One of the three inputs did not come back, so the decision agent refused
  to guess and handed the claim to a person, with the reason." Then R3. Rules
  missing twice: check the MCP server off screen (`curl -s
  localhost:8765/health`).
- **R7 Unexpected outcome** (00001 not APPROVE, or 08103 not HOLD). Do not argue
  with the card. Read its reasons, then: "The card shows its reasons, so we can
  check it rather than trust it -- and that is why a human signs." Re-fire only
  if a reason says data was missing. Analyse the node outputs in Activities
  after the show.
- **R8 LED red, Claim comes in greyed out.** No broker session. Reload the
  cockpit (Cmd+R). Still red: the local brokers are down. Meanwhile do beat 3 or
  beat 5 without a claim running, and fire when green. Off screen:

  ```
  docker start solace-1 solace-2
  ```

- **R9 Empty Grafana panels.** Widen the time range to include the live runs.
  Tempo empty: skip panel 2 and say the honest-limit paragraph on panel 3
  (afterwards, off screen: is the event-mesh `otel-collector` container Up?
  See A10).
  Platform-DB tables empty: the grafana_ro grant is missing (preflight
  re-applies it); skip to panel 4.
- **R10 Approve does nothing.** The cockpit publishes one approval per decision,
  then the button reads Approved. Still enabled after a click: the LED is
  probably red, see R8. The decision on the card stands either way.
- **R11 No usable deck.** Frame and close on the cockpit; the lines work
  unchanged without the pointing phrases. Skip D5.

Fixing the outside agent (R4), off screen, about a minute:

```
kubectl -n sam-solace-lab-agents get pods
kubectl -n sam-solace-lab-agents logs deploy/sam-claims-intake-agent --tail=50
kubectl rollout restart deployment sam-claims-intake-agent -n sam-solace-lab-agents
```

If the platform log still warns "multiple agent cards advertise the same display
name" or "peer tool unavailable" (typical after a re-install; observed on
2.225.14, not re-verified on 2.348.22, where deleting an agent also removes its
broker queue), restart the platform's agent runtime too. That takes every
platform agent down for a while: never during the demo, only in a break or
afterwards.

```
kubectl rollout restart deployment agent-mesh-solace-agent-mesh-awe -n sam-solace-lab
```

## Appendix C -- If they ask

Answer in one breath, then offer to show it. Never volunteer anything in
Appendix E; it is credible when asked for and alarming when offered.

**Where do the credentials live?**

> "The platform holds the connections to the two stores it reads, in its
> connectors. The database password sits there, not in any prompt, and the
> agents never see it -- we even test that the database expert refuses to hand
> it out; that was the third attack in the guardrail report. The outside agent
> keeps its own database and model credentials in its own runtime. This platform
> never holds them."

Honest addition if they probe: in this lab the SQL connector uses the database's
administrative account and the MCP server has no authentication; read-only
behaviour comes from the agent's instructions and is tested, not enforced by a
database role. In production the connector gets a read-only role.

**What stops an agent from calling something it should not?**

> "Three things. An agent can only call another agent if its configuration names
> it -- without that line it has no way to call one at all, and the liaison
> names exactly one. Roles decide which users may use which agents, connectors
> and workflows. And every workflow step has a schema its answer must fit. What
> the outside agent does inside its own runtime stays its owner's business; we
> govern what crosses the mesh."

Show: tab 3 (the allow list), D4 (the RBAC tables). Honest addition: the
platform's Orchestrator carries a star.

**What happens when the external agent is down?**

> "The intake step reports that the analyst was unavailable, and the decision
> agent's first rule turns that into a referral to a human handler, with the
> reason on the card. The workflow does not crash and nothing is guessed. On the
> dashboard, the outside agent's traffic panel stops showing received requests."

Show: R4 if it happens live.

**How do you know quality is not drifting?**

> "Three test sets on the three agents that reason: the rulebook agent, the
> database expert under attack, and the decision agent on the exact inputs the
> workflow sends it. Today: six of six on the attacks, six of six on the
> decisions, and on the rulebook what the latest report says (A9) -- if it shows
> a miss, open that row before you call it a catch. Those agents are on a
> watchlist, and
> every run lands as a time series on the dashboard -- so a model swap or a
> prompt edit is a measured decision."

Honest addition: the tests target agents, not the workflow as a whole -- the
orchestration is proven by Activities and Tempo -- and runs are started, not
continuous.

**What does this cost?**

> "The model side is on the dashboard: tokens per agent and per model, and an
> illustrative cost figure -- list prices times tokens. The outside agent's
> tokens are not in it; that bill stays with its owner. The platform itself is a
> commercial conversation, and I would like to take that offline with you."

**Is the second customer a fraudster?**

> "We do not know, and neither does the agent. It found two indicators. Its own
> guideline says a single indicator proves nothing, the overall picture decides,
> and a specialist decides. One claim waits for a person; the honest majority is
> not delayed."

**Will this work with our agents on Azure, AWS or Databricks?**

> "The agent you saw is built with our Python SDK, which takes care of the
> broker and the agent card. Hosted next to Databricks or on Azure, the same
> agent changes only its database and model settings. An agent on another
> framework has to join the mesh the same way -- publish a card and answer
> requests over the broker. Which of yours is closest to that is the first thing
> we would look at together."

**What does the platform not see of the external agent?**

> "Its internal tool calls, its tokens and its prompt. It sees its card, every
> request and answer that crosses the mesh, who called, and how long it took."

**Why a liaison? Why not call the external agent from the workflow directly?**

> "In this version a workflow step has to run on a platform agent. So one
> platform agent holds the contract and makes the call -- which also gives you
> exactly one place where that permission is written down."

**Who is the approver? Is that a real login?**

> "In this demo the approver is a fixed name in the cockpit page. In your claims
> system it would be the person who is signed in."

**What are the other discovered agents on that list?**

> "Agents from other work on the same lab mesh, discovered the same way. None of
> the four claims agents may call them -- no allow list names them."

**Why does the evaluation list show a weaker run, and more experiments?**

(The weaker run existed only on the 2.225.14 platform database; on 2.348.22
the question is only about the extra experiments -- answer with the last
sentence.)

> "That run is from before we changed the scorer. A word-overlap score marked
> correct decisions down for phrasing them differently; the judge scored the
> same decisions as correct. We changed how we measure, not the agent. The other
> experiments belong to a broader version of this demo."

**How long do you keep the audit trail?**

> "In this lab: traces for two days, logs and metrics for seven. In production
> that is your retention policy."

**Why does it take half a minute?**

> "Four agents think, three of them at the same time. The longest path is the
> intake hop plus the decision -- and the outside agent itself is only about
> five seconds of that."

**Can we change the model?**

> "Yes, behind the tier. Every agent binds to an alias, so switching the model
> is a change on the Models page, not in the agents. We would run the same tests
> against the new model first."

**Does this make us compliant (EU AI Act, BaFin, GDV)?**

> "It gives an auditor the building blocks: named human decisions, a traceable
> hop for every call, tested guardrails. Whether your setup is compliant is your
> compliance team's call -- and this is the evidence we would bring to that
> conversation."

## Appendix D -- Numbers you may say

Every figure below is measured or seeded. Anything not on this list, do not say.

| Fact | Value | Say it as |
| --- | --- | --- |
| The storm | Hail cell HZ-0913, Saturday 2026-07-18, 18:40, Landkreis Boeblingen | "twenty to seven on a Saturday evening" |
| Claims after the cell | 10,400 | "ten thousand four hundred" |
| Run time, event to decision | measured 2026-09-16 on SAM 2.225.14: 00002 26.8 s, 00001 27.7 s, 08103 30.6 s (later 31.1 s and 32.6 s), 08891 32.7 s, preflight dry fire 27 s; on SAM 2.348.22 (2026-09-21): preflight dry fires 28 s and 27 s | "about half a minute"; exact only as printed on the card |
| Node budget, typical run | measured on SAM 2.225.14: policy 13 s, intake 19 s (outside agent 5 s), rules 9 s, decision 12 s; critical path intake plus decision | "the outside agent is about five seconds" |
| Claim 1, CLM-0913-00001 | Lena Hartmann, VW Golf, app, 16 dents roof and bonnet, no glass damage, drivable, EUR 640, POL-104211 ACTIVE, HC-7, deductible EUR 300, RN-3, Sindelfingen, photos 7 min after the cell start | APPROVE / FAST_LANE, drive-in slot at P-BRAENDLE |
| Claim 2, CLM-0913-08103 | Ben Meier, Skoda Octavia, drive-in scanner, 60 dents claimed, EUR 6,800, reserve EUR 7,800, MOTOR_PARTIAL, deductible EUR 150, no RN-3; photos 7.3 days before the cell; scanner 14 vs 60 (76.7 percent) | HOLD / SPECIAL_INVESTIGATIONS, specialist within ten working days |
| Contracts | policy 22 fields, intake 12, rules 5, decision 14 | "every step has a schema" |
| Postgres acme_insurance | 68,700 policies, 51,525 customers, 10,400 claims, 1,600 workshop estimates, 3,900 payment items, 9 repair partners | system of record, native SQL connector |
| Qdrant acme_knowledge | 52 passages, 384 dimensions, cosine; 16 claims guidelines, 14 partner contracts, 12 policy wordings, 10 storm playbooks | the rulebook, behind an MCP server |
| MongoDB acme_claims | fnol_intake 10,463 (app 4,160, voice agent 2,663, workshop portal 1,560, drive-in scanner 1,040, agency email 1,040), scanner_results 1,040, weather_cells 3 | raw intake, only the outside agent reaches it |
| Clauses that appear | CG-FL-1, PW-HC-7, PW-RN-3, PW-DED-1, PW-EXCL-1, CG-SC-1, CG-FR-5, CG-BAFIN-30, CG-HOLD-1, PW-TL-1, CG-TL-2 | read them from the card |
| Models | four platform agents on `fast` (Claude Haiku 4.5), Orchestrator on `general`, outside agent on its own Haiku 4.5 | "a tier, not an endpoint" |
| Evaluations | ins-claims-rules (5 questions, Factuality + Closed QA) 10/10 on 2.225.14, 9/10 in both 2.348.22 pre-runs (2026-09-21, A9); ins-guardrails 6/6 (3 attacks, Security + LLM Judge) and ins-triage-decision 6/6 (3 decisions, LLM Judge + Closed QA) on both versions; watchlist of 3 agents | "ten of ten (or nine of ten, beat 11), six of six, six of six" |
| Dashboard | sam-claims-governance, folder SAM, 34 panels | "I showed you four" |
| Lab retention | Tempo 48 h, Loki 7 days, Prometheus 7 days | "traces two days, logs seven" |

Never say: a single run's seconds as a promise, the cost value, the number of
model aliases, the Registered agents value.

## Appendix E -- Known limits (moderate honestly)

### Visible on stage

- **One card at a time.** The cockpit has a single decision area; firing claim 2
  replaces claim 1's card. The event stream keeps both, which is why the close
  points at the stream and then at slide 2.
- **The stepper is decoration.** Its steps pulse on fixed CSS delays. The card
  and the clock come from the payloads and the click.
- **Platform hops in Tempo are runtime ids.** Spans read `.../request/agent_<id>
  receive`; only the outside agent's hop reads by name (`ClaimsIntakeAnalyst`),
  because its card name is its address (still so in 2.348.22). Tempo holds
  broker spans only: SAM emits no OTel spans of its own, and the broker's reach
  Tempo only while the event-mesh `otel-collector` container runs (A10).
- **The outside agent is not counted.** It is not in the Registered agents stat,
  the token and cost panels, or the platform database. The platform sees its
  card, every A2A hop with user identity and latency (Activities, Tempo, Loki),
  and the pod's plain-text log (row 3). Do not promise more.
- **Leftover MongoDB connectors.** An extended install creates fnol-intake,
  scanner-results and weather-cells. `install.sh` removes them for this profile
  -- the claim that only the outside agent reads the intake store has to survive
  a click on the Connectors page -- but `preflight.sh` does not flag them if
  something puts them back (A6).
- **Evaluations list more than three experiments.** ins-ops-quality and
  ins-ops-model-benchmark belong to the extended profile, and an early
  ins-triage-decision run scored with Response Match (1 of 3, average 0.515) can
  sit in Reports (on the 2.225.14 platform database; the one rebuilt for
  2.348.22 starts without it). The experiment now uses LLM Judge plus Closed
  QA: Response Match punished correct JSON decisions for their wording.
- **The Models page lists more aliases** than the demo uses. Point at `fast`;
  never count them.
- **Other discovered agents** of the shared lab mesh can appear in Agent
  Management (A7).
- **The approver is a fixed name** in the cockpit
  (`claims.lead@acme-insurance`), not a login.
- **The SQL connector uses the database's administrative account** in this lab
  and the MCP server has no authentication. Read-only behaviour is instructed
  and tested (ins-guardrails), not enforced by a database role.
- **The entrypoint's target reads as a runtime id** (see the event-to-workflow
  bugs below).
- **CLM-0913-08891 is not a stage claim.** Its system-of-record data (Ford
  Focus, Herrenberg, app) and its intake record (a different vehicle, channel
  and town) were not seeded as a matching pair, so the card can show a vehicle
  mismatch and a lower confidence. Its measured 32.7 s run stands; keep it off
  stage until the intake seed is pinned.
- **Junk characters in a reason.** The live contract note of partner P-DELLENDOC
  still contains an em dash (the seed file is corrected; the database keeps it
  until Postgres is re-seeded), and non-ASCII characters can arrive mangled in
  the cockpit (observed on 2.225.14; not re-verified on 2.348.22). If a line on
  the card shows three junk characters, read around them.
- **Hidden-window throttling.** The T+ clock runs on browser timers; keep the
  cockpit in its own visible window.

### Platform and build (2.348.22)

The platform runs SAM 2.348.22 (str 1.64.0, chart 2.1.164). Most of this list
was found on 2.225.14; every platform-behaviour item says whether it was
re-verified on 2.348.22.

- **Two platform bugs on the event-to-workflow path** (verified 2026-09-10 on
  2.225.14, still present in 2.348.22 -- re-verified 2026-09-21): an
  entrypoint `promptTemplate` renders only for agent targets, so a workflow
  target gets an empty message; and the gateway publishes to
  `.../request/<workflow name>` while the runtime listens on
  `.../request/workflow_<id>`. Workaround in `install.sh`: the entrypoint is
  rendered from `triage/entrypoints/claims-triage.yaml.template` after the
  workflow exists, targeting the runtime name, with `inputExpression:
  "input.payload"`. Consequences: the runtime name changes per install (re-run
  `install.sh`, never hand-edit `.rendered/`), and events published before the
  deploy are lost. The receivers themselves now come up about a second after
  the deploy (2.225.14: 20 to 40 s).
- **Node input templates render only whole-string expressions** (observed on
  2.225.14; not re-verified on 2.348.22). First-level nodes carry only an
  `instruction:` and receive the raw event; the decision node needs an
  explicit `input:` map. Do not "improve" the YAML.
- **External v1 agents cannot be workflow nodes.** The CLI rejects the
  reference (still so on 2.348.22), and via the REST API the v1 handler never
  answers the v2 engine (observed on 2.225.14). A platform agent has to carry
  the hop -- hence the liaison.
- **Peer delegation comes from one key**, `interAgentCommunication.allowList` in
  `additionalConfigurations`. Without it an agent has no delegation tool at all
  (observed on 2.225.14; not re-verified on 2.348.22); the Orchestrator carries
  `["*"]` (unchanged in 2.348.22). Routing the hop through the Orchestrator also
  works but adds Opus-tier overhead to the critical path.
- **Never tell a schema-bound node agent how to format its answer** (observed
  on 2.225.14; not re-verified on 2.348.22). The platform injects its own
  structured-output instruction; a "JSON only" instruction makes the node
  output null. Node instructions describe content only.
- **The liaison must call no tool except its peer tool** (observed on 2.225.14;
  not re-verified on 2.348.22). Given the chance, a fast-tier agent patches its
  answer with artifact tools and corrupts it into "intake unavailable". The ban
  sits in the prompt and in the node instruction; do not soften either.
- **The decision is an LLM output validated against a schema.** A node that
  violates its schema ends with a null output (no retry; the workflow still
  reports completed; observed on 2.225.14, not re-verified on 2.348.22), and
  the decision agent turns a missing section into REFER / HANDLER with the
  reason. `fail_fast` is off on purpose so this stays visible instead of fatal.
- **No RBAC "denied" log lines.** Grants and denials log at DEBUG only (observed
  on 2.225.14; not re-verified on 2.348.22); the dashboard shows auth failures
  and capability-widening blocks instead.
- **Evaluations target agents, not workflows** (still so in 2.348.22).
  ins-triage-decision feeds the decision agent the workflow's exact fan-in; the
  orchestration itself is proven by Activities and Tempo. One LLM-judge call
  takes around 40 s; two measured ins-triage-decision runs took 102 s and 117 s
  (measured on SAM 2.225.14).
- **A bare `sam eval run` answers 401** even with a valid CLI login (still so on
  CLI 2.348.22, re-verified 2026-09-21): the token has to be exported first.

```
bash                              # from the demo directory
./demo-links.sh >/dev/null        # refreshes the CLI token
. ../agent-mesh-deployment/scripts/lib/common.sh
load_env ../agent-mesh-deployment && resolve_sam_cli && sam_auth_token
"$SAM_CLI" eval run ins-triage-decision \
  --url https://sam.solace.lab --threshold 0.8
```

- **`install.sh` redeploys the two experts on every run.** Their skill binding
  never converges (2.225.14, still in 2.348.22, where the plan also flags the
  output modes), so `sam config plan` in `core/` always reports both as an
  update. `preflight.sh` reinstalls only when a resource is missing. Never
  re-install close to the show; never show `sam config plan` on stage.
- **Expert tier and database login come from the environment.** The two
  experts bind `${INS_EXPERT_TIER, fast}`; `install.sh` exports `fast` for this
  profile and `general` for `--extended`, and an exported value wins
  (`INS_EXPERT_TIER=... ./install.sh`, likewise `INS_DB_USERNAME` /
  `INS_DB_PASSWORD`). The defaults sit inline, not in a manifest `variables:`
  block: on CLI 2.348.22 a default there beats the environment.
- **Connector tools after an `str` restart.** The first call gets "tool not in
  manifest"; on 2.348.22 the agent runtime re-registers and retries on its own,
  so the call succeeds about a second later. No action needed, but the first
  dry fire after a restart can be a little slower.
- **Profiles are mutually exclusive.** Both entrypoints subscribe to
  `acmeins/claims/fnol/received/...`. Switch with `./uninstall.sh --keep-core`,
  then `./install.sh --extended`; never on show day. The other profile's script
  is `talk-track-extended.md`.
- **The outside agent's cluster prerequisites.** Its Deployment needs the
  namespace `sam-solace-lab-agents` and the Secret `sam-shared-secret` (broker,
  model endpoint and key), both from the companion solace-sam-artifacts
  repository. `install.sh` stops with a message when either is missing; if they
  disappear later, the pod stops working and every card lands as REFER / intake
  unavailable. Its image is
  `registry.solace.lab/solace-agent-mesh-enterprise:latest` with
  `imagePullPolicy: Always` (on 2026-09-21 the 1.97.2 build): every pod start
  resolves the tag against the lab registry, so the registry must be reachable
  whenever the pod restarts.
- **Stale agent card after delete and rebuild.** The mesh can keep a dead
  instance's card after a re-install (observed on 2.225.14; not re-verified on
  2.348.22); fix in Appendix B.
- **Retention.** Tempo 48 h, Loki 7 days, Prometheus 7 days.
- **Demo clock.** The data is a frozen Monday 2026-07-20 10:00 UTC; node
  instructions pin that instant. "Days before the cell" is computed against the
  cell start in the event, never against the wall clock; only `published_at` and
  `approved_at` carry real time.
- **Regulatory colour is colour, not data.** CG-FR-5 and CG-BAFIN-30 live inside
  Acme's fictional rulebook; answer compliance questions with Appendix C, never
  with a claim of compliance.

## Appendix F -- Why the script runs in this order

For whoever edits this next. The script follows the narrative review's spine:
the first claim fires before minute two, every explanation covers a running
clock, the roster becomes wait-window material, and the live evaluation run is
gone. Deliberate deviations:

- **Slides.** The frame opens on slide 3 instead of the cockpit alone: it
  asserts "one agent is outside" before the roster shows it. Slide 2 closes
  because the cockpit keeps one card, and the close needs both outcomes side by
  side. Slide 1 (the generic lifecycle vision) is not shown: it invites "so you
  want us to build here".
- **Window B stays a separate browser profile.** Activities is per user; tabs of
  one profile share one login, so power_user cannot be a tab of the sam_admin
  window.
- **"Its own namespace", not "its own cluster".** The outside agent runs in the
  same Kubernetes cluster, in `sam-solace-lab-agents`.
- **No "read-only service accounts" line.** The lab's SQL connector does not use
  one (Appendix E).
- **CLM-0913-08891 left the optional depth.** Its intake record does not match
  its system-of-record data.
- **The run time is read off the card**, never recited: it moves by a few
  seconds between runs.
