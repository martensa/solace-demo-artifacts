/* /monitor: fair monitor, read only (UC1-BUILD-SPEC 10.4). Everything comes from the
   SSE stream /api/events; "hello" carries the /api/state snapshot. Only the booth till
   (store/till from the snapshot) and the booth rules r1/r3/r4 are shown.
   Two AI stages (15.2 UC1-26): the fast agent gathers evidence (review "prepared" again,
   now with "evidence"), the planning agent writes the KI-Empfehlung (review
   "decision", proposal "ai_model"); a missing model alias means "fast" (modelOf). */
(function () {
  "use strict";

  const { T, el, icon, fmt, chip, cents, euro, elapsed, stateText, api, connectEvents,
    scheduler } = window.GPOS;
  const MT = T.monitor;
  const ML = MT.labels;
  const TS = MT.timelineSteps;
  const CARD_REFRESH_MS = 500;
  const RUNS_MAX = 5;
  const RUNS_SHOWN_REVIEW = 3;  // 1920 x 1080: room for rule card, KI-Schritte, KI-Empfehlung
  const FADE_PX = 28;           // fade of a cut box in column 2 (monitor.css .clipped)
  const CALLS_KEPT = 30;
  const CALLS_SHOWN = 8;
  const NEW_PRICE_STATION_S = 30;
  const CORRELATE_MS = 10000;  // 10.4: R4 error run <-> proposal end state (arrival time)
  const RULE_SOURCE = { r1: "rule", r3: "ai", r4: "human" };
  const DENIED = ["rejected", "expired", "blocked"];
  const END_STATES = ["approved", "rejected", "expired", "failed", "superseded", "blocked"];
  const APPROVER_STATES = ["pending", "approved", "rejected", "expired", "blocked"];
  const REVIEW_ACTIVE = ["requested", "prepared"];
  const PAST_PREPARED = ["prepared", "proposed", "no_action", "blocked", "failed"];
  const RECOMMENDED = ["proposed", "no_action", "blocked"];
  const WITHOUT_AI = ["no_candidates", "only_blocked"];
  const HOLDS = ["yes", "no", "unknown"];

  const M = {
    booth: { store: "", till: "" },
    demoDate: "",
    bon: null,
    runs: [],
    review: null,
    calls: [],
    proposal: null,
    pendingSince: 0,
    wasPending: false,
    lastEnd: null,
    priceEvent: null,
    awaitingScan: "",
    nextScan: "",
    duplicate: false,
    lastApproval: null,
    approvedAt: 0,
    counters: null,
    lastEvent: "",
    lastEventAt: Date.now(),
    recap: false,
  };

  const $ = (id) => document.getElementById(id);
  const render = scheduler(renderAll);
  const isBooth = (d) => d.till === M.booth.till && (!d.store || d.store === M.booth.store);
  const isObj = (x) => x !== null && typeof x === "object" && !Array.isArray(x);
  /** append() without empty parts: the DOM would turn null into the text "null". */
  const put = (parent, ...children) => parent.append(...children.filter((c) =>
    c !== null && c !== undefined && c !== false));
  const now = () => performance.now();

  /* ---------------------------------------------------------------- models */
  /** Model rule (same as ui/texts.py model_of): "fast" or "planning", else "fast". */
  const modelOf = (alias) => (T.models.includes(alias) ? alias : T.defaultModel);
  /** {model} of the timeline: always the display name, never the alias. */
  const modelName = (alias) => T.modelNames[modelOf(alias)];
  const aiHeader = (alias) => fmt(MT.aiRecommendation,
    { model: modelOf(alias), name: modelName(alias) });

  /* ---------------------------------------------------------------- review data */
  /** The planning decision of a review event (7.2; an engine object carries
      agent_decision); null before the recommendation. */
  function decisionOf(r) {
    if (!r) return null;
    const d = isObj(r.decision) ? r.decision : isObj(r.agent_decision) ? r.agent_decision : null;
    return d && d.decision ? d : null;
  }

  /** The evidence the engine stored from the fast agent (note_evidence), or null. */
  function evidenceOf(r) {
    if (!r) return null;
    const found = [r.evidence, isObj(r.decision) ? r.decision.evidence : null,
      isObj(r.agent_decision) ? r.agent_decision.evidence : null];
    return found.find(isObj) || null;
  }

  const itemsOf = (ev) => (ev && Array.isArray(ev.items) ? ev.items.filter(isObj) : []);
  const holdsOf = (item) => (HOLDS.includes(item.holds) ? item.holds : "unknown");
  const lineOf = (r, number) => (r.lines || []).find((l) => l.article_number === number);
  const reasonLabel = (code) => T.reasons[code] || code || "";

  function candidatesOf(r) {
    if (typeof r.candidates === "number") return r.candidates;
    return (r.lines || []).filter((l) => l.candidate && !l.blocked).length;
  }

  /** The fast agent's API queries of one review (tool calls with ref == review_id). */
  const callsOf = (reviewId) => (reviewId
    ? M.calls.filter((c) => String(c.ref || "") === reviewId) : []);

  function articleName(r, number, ev) {
    const line = lineOf(r, number);
    const item = itemsOf(ev).find((i) => i.a === number);
    return (line && line.name) || (item && item.name) || number || "";
  }

  /* ---------------------------------------------------------------- state */
  function newBon(txId) {
    return { tx_id: txId, status: "CREATED", total: "", card: "", persona: "",
      consent_profiling: null, lines: new Map(), events: [] };
  }

  function bonFromState(raw) {
    if (!raw) return null;
    const bon = Object.assign(newBon(raw.tx_id), raw, { lines: new Map() });
    for (const line of raw.lines || []) bon.lines.set(line.position_id, line);
    bon.events = raw.events || [];
    return bon;
  }

  function touch(kind) {
    M.lastEvent = kind;
    M.lastEventAt = Date.now();
    M.recap = false;
  }

  function onPosEvent(d) {
    if (!isBooth(d)) return;
    touch("pos_event");
    if (!M.bon || M.bon.tx_id !== d.tx_id) M.bon = newBon(d.tx_id);
    const bon = M.bon;
    if ((d.offset || 0) >= (bon.last_offset || 0)) {
      bon.last_offset = d.offset || 0;
      if (d.status) bon.status = d.status;
      if (d.total) bon.total = d.total;
    }
    bon.events = bon.events.concat([{ event: d.event, offset: d.offset, to_sam: d.to_sam }])
      .slice(-12);
    if (d.event === "PositionAdded" && d.position_id) {
      bon.lines.set(d.position_id, { position_id: d.position_id, description: d.description,
        item_count: d.item_count || 1, price: d.price, price_source: d.price_source,
        regular_price: d.regular_price, voided: false, insight: null });
      if (M.awaitingScan === d.article_number && d.price_source === "BOOTH_ACTION") {
        M.nextScan = d.price;
        M.awaitingScan = "";
      }
    } else if (d.event === "ArticlePositionVoided" && bon.lines.has(d.position_id)) {
      bon.lines.get(d.position_id).voided = true;
    } else if (d.event === "LoyaltyMembershipAssigned") {
      if (d.card) {
        Object.assign(bon, { card: d.card, persona: d.persona,
          consent_profiling: d.consent_profiling });
      } else {
        setTimeout(() => refreshCard(d.tx_id), CARD_REFRESH_MS);
      }
    }
    render();
  }

  /** The card of a GEBIT event without capturingInformation: from the BFF receipt. */
  async function refreshCard(txId) {
    const r = await api("/api/state");
    const bon = r.body.bon;
    if (!bon || !M.bon || bon.tx_id !== txId || M.bon.tx_id !== txId || !bon.card) return;
    Object.assign(M.bon, { card: bon.card, persona: bon.persona,
      consent_profiling: bon.consent_profiling });
    render();
  }

  function onInsight(d) {
    if (!isBooth(d)) return;
    touch("insight");
    if (M.bon && M.bon.tx_id === d.tx_id && M.bon.lines.has(d.position_id)) {
      M.bon.lines.get(d.position_id).insight = { code: d.code, text: d.text };
    }
    render();
  }

  /** Final label of an R4 error run from the engine outcome (10.4). */
  function finalLabel(state) {
    return state === "rejected" ? T.runLabels.denied
      : state === "expired" ? T.runLabels.expired : T.runLabels.error;
  }

  function settle(run, state) {
    run.label = finalLabel(state);
    run.provisional = false;
  }

  /** sam_run carries no proposal or run id and the engine ts runs on the demo clock:
      R4 error runs and proposal end states are paired by the monitor's own arrival
      time (seenAt, <= 10 s). Replayed runs (hello) keep their provisional label. */
  function onSamRun(d, replay) {
    if (!RULE_SOURCE[d.rule]) return;
    if (!replay) touch("sam_run");
    const run = Object.assign({}, d, { seenAt: replay ? -Infinity : now() });
    if (run.rule === "r4" && run.provisional && M.lastEnd &&
        run.seenAt - M.lastEnd.seenAt <= CORRELATE_MS) {
      settle(run, M.lastEnd.state);
      M.lastEnd = null;
    }
    M.runs = [run].concat(M.runs).slice(0, RUNS_MAX);
    render();
  }

  function onEndState(state) {
    const at = now();
    const run = M.runs.find((r) => r.rule === "r4" && r.provisional &&
      at - r.seenAt <= CORRELATE_MS);
    if (run) {
      settle(run, state);
      M.lastEnd = null;
    } else {
      M.lastEnd = { state, seenAt: at };
    }
  }

  /** The repeated "prepared" (now with evidence) merges into the same review. */
  function onReview(d) {
    if (!isBooth(d)) return;
    touch("review");
    const same = M.review && M.review.review_id === d.review_id;
    M.review = same ? Object.assign({}, M.review, d, { lines: d.lines || M.review.lines }) : d;
    render();
  }

  /** The timeline shows the API families of 10.4 (Kasse, Warenwirtschaft, Loyalty): the
      fast agent's evidence queries, not the approver's gated apply_price. Calls are
      kept across reviews and matched by ref (a call can arrive before "prepared"). */
  function onToolCall(d, replay) {
    if (d.caller !== "agent" || !MT.apiFamilies[d.service]) return;
    if (!replay) touch("tool_call");
    M.calls = M.calls.concat([d]).slice(-CALLS_KEPT);
    render();
  }

  function onProposal(d) {
    if (!isBooth(d)) return;
    touch("proposal");
    if (d.signal === "duplicate_request") {
      M.duplicate = true;
      render();
      return;
    }
    if (!M.proposal || M.proposal.proposal_id !== d.proposal_id) {
      M.duplicate = false;
      M.priceEvent = null;
      M.nextScan = "";
      M.wasPending = false;
    }
    M.proposal = d;
    if (d.state === "pending") {
      M.pendingSince = Date.parse(d.ts) || Date.now();
      M.wasPending = true;
    }
    if (d.state === "approved") {
      M.awaitingScan = d.article_number;
      M.approvedAt = Date.now();
      M.lastApproval = { proposal: d, priceEvent: M.priceEvent };
    }
    if (END_STATES.includes(d.state)) onEndState(d.state);
    render();
  }

  function onPriceChange(d, replay) {
    if (d.store !== M.booth.store) return;
    if (!replay) touch("price_change");
    if (d.event === "PriceChangeApplied") {
      M.priceEvent = d;
      if (M.lastApproval && M.lastApproval.proposal.proposal_id === d.proposal_id) {
        M.lastApproval.priceEvent = d;
      }
    } else if (M.priceEvent && M.priceEvent.action_id === d.action_id) {
      M.priceEvent = null;
    }
    render();
  }

  function onHello(state) {
    M.booth = state.booth || M.booth;
    M.demoDate = state.demo_date || "";
    M.bon = bonFromState(state.bon);
    M.review = state.review || null;
    M.proposal = state.proposal_event || state.proposal || null;
    M.counters = state.counters || null;
    M.runs = [];
    M.calls = [];
    M.lastEnd = null;
    M.wasPending = Boolean(M.proposal && (M.proposal.state === "pending" ||
      M.proposal.pending_at));
    /* an engine object (11.8) carries pending_at/decided_at; its ts is the read time */
    if (M.proposal && M.proposal.state === "pending") {
      M.pendingSince = Date.parse(M.proposal.pending_at || M.proposal.ts) || Date.now();
    }
    if (M.proposal && M.proposal.state === "approved") {
      M.approvedAt = Date.parse(M.proposal.decided_at || M.proposal.ts) || 0;
      M.lastApproval = { proposal: M.proposal, priceEvent: null };
    }
    for (const item of state.events || []) {
      if (item.event === "sam_run") onSamRun(item.data, true);
      else if (item.event === "tool_call") onToolCall(item.data, true);
      else if (item.event === "price_change") onPriceChange(item.data, true);
    }
    render();
  }

  function onReset() {
    Object.assign(M, { bon: null, runs: [], review: null, calls: [], proposal: null,
      pendingSince: 0, wasPending: false, lastEnd: null, priceEvent: null, awaitingScan: "",
      nextScan: "", duplicate: false, lastApproval: null, approvedAt: 0, recap: false,
      lastEvent: "", lastEventAt: Date.now() });
    render();
  }

  /* ---------------------------------------------------------------- stations */
  function activeStation() {
    const p = M.proposal;
    if (p && (p.state === "pending" || p.state === "ready")) return 4;
    if (M.review && M.review.state === "prepared") return 3;
    if (M.review && M.review.state === "requested") return 2;  // 1.4: review requested
    if (M.nextScan || (M.approvedAt && Date.now() - M.approvedAt < NEW_PRICE_STATION_S * 1000)) {
      return 5;
    }
    if (M.lastEvent === "insight" || M.lastEvent === "sam_run") return 2;
    if (M.bon && !["CLOSED", "CANCELLED", "RESET"].includes(M.bon.status)) return 1;
    return 0;
  }

  function renderStations() {
    const active = activeStation();
    const pending = M.proposal && M.proposal.state === "pending";
    $("stations").replaceChildren(...MT.stations.map((s) =>
      el("li", { class: `station src-${T.sourceTones[s.source] ? s.source : "till"}` +
          (Number(s.no) === active ? " active" : "") +
          (Number(s.no) === active && active === 4 && pending ? " pulse" : "") },
        el("span", { class: "no" }, s.no), s.label)));
  }

  /* ---------------------------------------------------------------- column 1 */
  function renderTill() {
    const bon = M.bon;
    const status = !bon ? ML.noBon : bon.status === "CLOSED" ? ML.bonClosed
      : ["CANCELLED", "RESET"].includes(bon.status) ? ML.bonCancelled : ML.bonOpen;
    $("till-status").textContent = status;
    $("card-box").replaceChildren();
    if (bon && bon.card) {
      const consent = bon.consent_profiling === true ? MT.consentYes
        : bon.consent_profiling === false ? MT.consentNo : "";
      $("card-box").append(el("span", { class: "persona" },
        fmt(ML.card, { persona: bon.persona || bon.card })),
      consent ? " · " + consent : "");
    }
    const lines = bon ? [...bon.lines.values()] : [];
    $("bon-lines").className = "bon-lines" + (bon && bon.status !== "CLOSED" ? " open" : "");
    $("bon-lines").replaceChildren(...lines.map((l) =>
      el("li", { class: "bon-line" + (l.voided ? " voided" : "") },
        el("span", { class: "name" }, `${l.item_count || 1} × ${l.description}`),
        el("span", { class: "price" }, l.price ? l.price + " €" : ""),
        el("span", { class: "meta" },
          l.price_source && l.price_source !== "REGULAR"
            ? el("span", { class: "badge action" }, T.kasse.actionBadge) : null,
          l.price_source && l.price_source !== "REGULAR" && l.regular_price
            ? el("span", { class: "strike" }, l.regular_price + " €") : null,
          chip(l.insight)))));
    const total = bon && bon.total ? bon.total
      : euro(lines.filter((l) => !l.voided).reduce((s, l) => s + cents(l.price), 0));
    $("bon-sum").textContent = bon ? `${ML.sum} ${total} €` : "";
    $("band").replaceChildren(...(bon ? bon.events : []).slice().reverse().map((e) =>
      el("li", { class: e.to_sam ? "sam" : "" }, `${e.event} #${e.offset}`,
        e.to_sam ? " " + ML.toSam : "")));
  }

  /* ---------------------------------------------------------------- column 2 */
  function runClass(r) {
    return r.ok ? "ok" : r.label === T.runLabels.expired ? "expired"
      : r.label === T.runLabels.denied ? "denied" : "error";
  }

  function renderRuns() {
    const review = M.review && !WITHOUT_AI.includes(M.review.state);
    const shown = M.runs.slice(0, review ? RUNS_SHOWN_REVIEW : RUNS_MAX);
    $("runs").replaceChildren(...shown.map((r) =>
      el("li", { class: `src-${RULE_SOURCE[r.rule]}` },
        el("span", { class: "rule" }, r.rule.toUpperCase()),
        el("span", { class: "wf" }, r.workflow),
        el("span", { class: "label " + runClass(r), title: r.ok ? null : r.error || null },
          r.label))));
  }

  function reviewLine(line, extraClass) {
    const signals = (line.signals || []).map((s) =>
      el("span", { class: "chip red" }, T.reasons[s] || s));
    return el("div", { class: "review-line " + extraClass },
      el("div", { class: "head" }, line.name, signals),
      line.facts ? el("div", { class: "facts" }, line.facts) : null);
  }

  function renderReview() {
    const r = M.review;
    const box = $("review");
    box.replaceChildren();
    if (!r) return;
    const lines = r.lines || [];
    const candidates = lines.filter((l) => l.candidate && !l.blocked);
    const blocked = lines.filter((l) => l.blocked);
    const rest = lines.filter((l) => !l.candidate && !l.blocked);
    const chosen = r.decision && r.state === "proposed" ? r.decision.article_number : "";
    const summary = r.state === "requested" ? MT.reviewRequested
      : !lines.length ? stateText(r.state)
        : fmt(MT.reviewSummary, { articles: lines.length,
          candidates: r.candidates !== undefined ? r.candidates : candidates.length });
    box.append(el("div", { class: "summary" },
      el("span", { class: "badge rule src-rule" }, MT.ruleAnalysis), summary));
    if (candidates.length) {
      box.append(el("div", { class: "group" }, ML.candidates));
      const main = candidates.filter((l) => !chosen || l.article_number === chosen);
      box.append(...main.map((l) => reviewLine(l, "candidate" + (chosen ? " proposed" : ""))));
      const others = candidates.filter((l) => chosen && l.article_number !== chosen);
      if (others.length) {
        box.append(el("div", { class: "group" }, MT.otherCandidates));
        box.append(...others.map((l) => reviewLine(l, "candidate")));
      }
    }
    if (blocked.length) {
      box.append(el("div", { class: "group" }, ML.blocked));
      box.append(el("div", { class: "pills" }, blocked.map((l) =>
        el("span", { class: "pill", title: l.facts || "" }, icon("lock"),
          `${l.name} · ${l.blocked}`))));
    }
    if (rest.length) {
      box.append(el("div", { class: "group" }, MT.noActionNeeded));
      box.append(el("div", { class: "pills" }, rest.map((l) =>
        el("span", { class: "pill", title: l.facts || "" }, l.name))));
    }
  }

  /** One main step of the timeline (texts of 10.5 TIMELINE_STEPS). */
  function step(text, source, opts) {
    const o = opts || {};
    return el("li", { class: `step src-${source}` + (o.pulse ? " pulse" : "") +
        (o.failed ? " failed" : ""), title: o.title || null },
      el("span", { class: "what" }, text),
      o.detail ? el("span", { class: "detail" }, "· " + o.detail) : null);
  }

  /** Sub-line of one API query of the fast agent. */
  function askLine(c) {
    const family = MT.apiFamilies[c.service] || c.service;
    const m = String(c.summary || "").match(/^(\d{4,}):\s*(.*)$/);
    const what = fmt(MT.agentAsks, { model: modelName("fast"), family, tool: c.tool }) +
      (m ? ` (${m[1]})` : "");
    const detail = [c.ms !== undefined ? `${c.ms} ms` : "", m ? m[2] : c.summary]
      .filter(Boolean).join(" · ");
    return el("li", { class: "ask src-ai" + (c.ok === false ? " failed" : "") },
      el("span", { class: "what" }, what),
      detail ? el("span", { class: "detail" }, "· " + detail) : null);
  }

  /** API queries of the evidence step; after a reconnect without the calls:
      (tx known ? 1 : 0) + the tools of every evidence item. */
  function queriesOf(ev, calls) {
    if (calls.length) return calls.length;
    const tools = itemsOf(ev)
      .reduce((n, i) => n + (Array.isArray(i.tools) ? i.tools.length : 0), 0);
    return (ev.tx && ev.tx !== "unknown" ? 1 : 0) + tools;
  }

  /** The KI-Schritte of the current review (10.4): rules, evidence (fast) with its API
      queries, recommendation (planning), engine, approver (fast). */
  function timelineRows() {
    const r = M.review;
    if (!r) return [];
    const rows = [];
    const ev = evidenceOf(r);
    const d = decisionOf(r);
    const calls = callsOf(r.review_id);
    const p = M.proposal && M.proposal.review_id === r.review_id ? M.proposal : null;
    const candidates = candidatesOf(r);
    if (PAST_PREPARED.includes(r.state) && (candidates > 0 || ev || d)) {
      rows.push(step(fmt(TS.rules, { candidates }), "rule"));
    }
    if (ev) {
      const items = itemsOf(ev);
      rows.push(step(fmt(TS.evidenceDone, { model: modelName(ev.model), n: queriesOf(ev, calls) }),
        "ai", { detail: fmt(TS.evidenceDetail, {
          holding: items.filter((i) => holdsOf(i) === "yes").length, checked: items.length }) }));
    } else if (calls.length && r.state === "prepared") {
      rows.push(step(fmt(TS.evidenceRunning, { model: modelName("fast") }), "ai", { pulse: true }));
    } else if (calls.length) {  // legacy single agent: no evidence step
      rows.push(step(fmt(TS.evidenceDone, { model: modelName("fast"), n: calls.length }), "ai"));
    }
    rows.push(...calls.slice(-CALLS_SHOWN).map(askLine));
    const propose = d && d.decision === "propose" ? step(fmt(TS.planningPropose, {
      model: modelName(d.model), article: articleName(r, d.article_number, ev),
      reason: reasonLabel(d.reason) }), "ai") : null;
    if (r.state === "prepared" && ev) {
      rows.push(step(fmt(TS.planningRunning, { model: modelName("planning") }), "ai",
        { pulse: true }));
    } else if (r.state === "proposed" && propose) {
      rows.push(propose);
    } else if (r.state === "no_action") {
      rows.push(step(fmt(TS.planningNoAction, { model: modelName(d ? d.model : "") }), "ai"));
    } else if (r.state === "blocked") {
      if (propose) rows.push(propose);
      rows.push(step(fmt(TS.engineBlocked, { reason: r.error || stateText("blocked") }), "rule",
        { failed: true }));
    } else if (r.state === "failed" && ev) {
      /* no raw SAM error on the monitor: the English text only as the title */
      rows.push(step(fmt(TS.planningFailed, { model: modelName("planning") }), "ai",
        { failed: true, title: r.error || r.status_reason || "" }));
    }
    if (p) rows.push(step(fmt(TS.engine, { old: p.old_price, new: p.new_price }), "rule"));
    if (p && (APPROVER_STATES.includes(p.state) || (p.state === "failed" && M.wasPending))) {
      rows.push(step(fmt(TS.approver, { model: modelName("fast") }), "ai"));
    }
    return rows;
  }

  function renderTimeline() {
    $("timeline").replaceChildren(...timelineRows());
  }

  /** Evidence of the fast agent: one line per checked candidate. The engine's German
      facts of that line stand once, on the review card above (and on the proposal
      card); items[].numbers is never rendered (planner and audit only). */
  function evidenceBlock(r, ev) {
    const items = itemsOf(ev);
    if (!items.length) return [];
    return [el("div", { class: "who evidence-title" }, fmt(MT.evidenceTitle,
      { model: modelOf(ev.model), name: modelName(ev.model) })),
    ...items.map((item) => {
      const line = lineOf(r, item.a);
      return el("div", { class: "evidence holds-" + holdsOf(item) },
        el("div", { class: "what" }, fmt(MT.evidenceLine, {
          article: item.name || (line && line.name) || item.a || "",
          reason: reasonLabel(item.reason), holds: MT.evidenceHolds[holdsOf(item)] })));
    })];
  }

  /** The proposal of this review, when the monitor knows it. */
  function proposalOf(r) {
    const p = M.proposal;
    return p && r && p.review_id === r.review_id ? p : null;
  }

  /** The KI-Empfehlung block (planning) with the evidence below it. Headline and
      rationale only while the engine kept them: a proposal with text_source "template"
      (11.3 step 7 threw the KI text away) shows TEMPLATE_TEXT here, as column 3 does.
      Facts stand on the review card and in column 3, not here (1920 x 1080). */
  function renderDecision() {
    const r = M.review;
    const box = $("decision");
    box.replaceChildren();
    if (!r) return;
    if (WITHOUT_AI.includes(r.state)) {
      box.append(el("div", { class: "without-ai" }, MT.reviewWithoutAi));
      return;
    }
    const d = decisionOf(r);
    if (RECOMMENDED.includes(r.state) && (d || r.state !== "blocked")) {
      const dd = d || {};
      const p = proposalOf(r);
      box.append(el("div", { class: "who" }, aiHeader(dd.model)));
      if (r.state === "no_action" || dd.decision === "no_action") {
        const rationale = dd.rationale || r.rationale || "";
        put(box, el("div", {}, el("strong", {}, MT.noChangeRecommended)),
          rationale ? el("div", {}, rationale) : null);
      } else if (p && p.text_source === "template") {
        box.append(el("div", { class: "template" }, MT.templateText));
      } else {
        put(box, dd.headline ? el("div", {}, el("strong", {}, dd.headline)) : null,
          dd.rationale ? el("div", {}, dd.rationale) : null);
      }
    }
    if (r.state === "blocked") {
      /* refused by stage_proposal (candidate, evidence, reason, consent) or a guardrail:
         the engine's words of the timeline, not the proposal state text */
      box.append(el("div", { class: "state" },
        fmt(TS.engineBlocked, { reason: r.error || stateText("blocked") })));
    } else if (!REVIEW_ACTIVE.includes(r.state) && !["proposed", "no_action"].includes(r.state)) {
      const reason = r.status_reason;
      box.append(el("div", { class: "state", title: r.state === "failed" ? r.error || null : null },
        stateText(r.state) || MT.noAdjustment, reason ? ` (${reason})` : ""));
    }
    box.append(...evidenceBlock(r, evidenceOf(r)));
  }

  /* ---------------------------------------------------------------- column 3 */
  function guardrail(g) {
    const cls = g.ok ? "ok" : g.info ? "locked" : "bad";
    return el("li", { class: cls }, icon(g.ok ? "check" : g.info ? "lock" : "cross"),
      g.rule, g.value ? ` · ${g.value}` : "");
  }

  function proposalCard(p) {
    const reason = p.reason_label || T.reasons[p.reason] || p.reason || "";
    return el("div", {},
      el("div", { class: "article" }, p.article_name),
      el("div", { class: "prices" }, `${p.old_price} € → ${p.new_price} €`,
        el("span", { class: "pct" }, p.pct_label ? `(${p.pct_label})` : "")),
      el("div", { class: "meta" }, fmt(ML.reason, { label: reason })),
      p.text_source === "ai"
        ? el("div", { class: "source ai" }, aiHeader(p.ai_model))
        : el("div", { class: "source template" }, MT.templateText),
      p.headline ? el("div", { class: "headline" }, p.headline) : null,
      p.rationale ? el("div", { class: "rationale" }, p.rationale) : null,
      p.facts_line ? el("div", { class: "facts" }, p.facts_line) : null,
      p.note ? el("div", { class: "note" }, p.note) : null,
      (p.guardrails || []).length ? el("div", { class: "gr-title" }, MT.guardrailsTitle) : null,
      el("ul", { class: "guardrails" }, (p.guardrails || []).map(guardrail)),
      p.ref30 ? el("div", { class: "meta" }, fmt(MT.ref30, { ref30: p.ref30 })) : null,
      p.base_price_label ? el("div", { class: "meta" },
        fmt(ML.basePrice, { label: p.base_price_label })) : null,
      p.valid_to_label ? el("div", { class: "meta" },
        fmt(ML.validTo, { label: p.valid_to_label })) : null,
      p.clamped ? el("div", { class: "info" }, MT.clamped) : null);
  }

  function renderStamp(p) {
    const stamp = $("stamp");
    stamp.replaceChildren();
    stamp.className = "stamp hidden";
    if (!p) return;
    if (p.state === "approved") {
      stamp.className = "stamp";
      stamp.append(el("div", { class: "big" }, MT.stampApproved), el("div", {}, MT.stampBy),
        el("div", {}, fmt(MT.newPriceActive, { price: p.new_price })));
    } else if (DENIED.includes(p.state)) {
      stamp.className = "stamp denied";
      put(stamp, el("div", { class: "big" }, MT.stamps[p.state]),
        p.status_reason ? el("div", {}, p.status_reason) : null,
        el("div", { class: "by" }, MT.stampBy));
    }
  }

  function renderApproval() {
    const recap = M.recap && M.lastApproval;
    const p = recap ? M.lastApproval.proposal : M.proposal;
    const priceEvent = recap ? M.lastApproval.priceEvent : M.priceEvent;
    $("recap").textContent = MT.recap;
    $("recap").classList.toggle("hidden", !recap);
    $("duplicate").textContent = stateText("duplicate_request");
    $("duplicate").classList.toggle("hidden", recap || !M.duplicate);
    $("proposal").replaceChildren(p ? proposalCard(p) : el("div", { class: "waiting" },
      ML.waiting));
    const line = $("status-line");
    line.className = "status-line" + (p && p.state !== "pending" ? " final" : "");
    line.textContent = !p ? "" : p.state === "pending"
      ? fmt(MT.pendingSince, { elapsed: elapsed((Date.now() - M.pendingSince) / 1000) })
      : stateText(p.state);
    renderStamp(p);
    const pe = $("price-event");
    pe.classList.toggle("hidden", !priceEvent);
    pe.replaceChildren(...(priceEvent ? [
      el("div", {}, el("strong", {}, `${ML.priceEvent}: ${priceEvent.event}`),
        ` · actionId ${priceEvent.action_id}`),
      el("div", { class: "topic" }, priceEvent.topic)] : []));
    const next = !recap && M.nextScan;
    $("next-scan").classList.toggle("hidden", !next);
    $("next-scan").textContent = next ? fmt(MT.nextScan, { price: M.nextScan }) : "";
  }

  /* ---------------------------------------------------------------- footer */
  function renderFooter() {
    $("counters").textContent = M.counters ? M.counters.line : "";
    $("llm-hint").textContent = MT.llmHint;
    renderClock();
  }

  function renderClock() {
    const now = new Date();
    const day = M.demoDate ? new Date(M.demoDate + "T12:00:00") : now;
    const weekday = ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"][day.getDay()];
    const date = `${String(day.getDate()).padStart(2, "0")}.` +
      `${String(day.getMonth() + 1).padStart(2, "0")}.${day.getFullYear()}`;
    $("clock").textContent = `${weekday} ${date} · ${now.toLocaleTimeString("de-DE")}`;
  }

  /** Floor of a box in column 2: down to the bottom of child plus the fade of a cut box
      (FADE_PX = the mask in monitor.css), so the protected lines never fade; never more
      than the content (no blank space). 0 without a child. */
  function floorOf(box, child) {
    if (!child) return 0;
    const bottom = child.getBoundingClientRect().bottom - box.getBoundingClientRect().top;
    return Math.min(box.scrollHeight, Math.ceil(bottom) + FADE_PX);
  }

  /** Column 2 at 1920 x 1080 (10.4): when it is full, the evidence lines of the
      KI-Empfehlung clip first, then the rest of the review card. Floors: the review card
      keeps its summary and first candidate line ("Regel-Analyse (ohne KI)"), the
      KI-Empfehlung keeps its header and texts. Cut boxes fade instead of a half line. */
  function fitColumn2() {
    const review = $("review");
    const decision = $("decision");
    review.style.minHeight = "";
    decision.style.minHeight = "";
    const core = [...decision.children].filter((c) => !c.matches(".evidence-title, .evidence"));
    const floors = [
      floorOf(review, review.querySelector(".review-line") || review.querySelector(".summary")),
      floorOf(decision, core[core.length - 1])];
    review.style.minHeight = floors[0] + "px";
    decision.style.minHeight = floors[1] + "px";
    for (const box of [review, decision]) {
      box.classList.toggle("clipped", box.scrollHeight > box.clientHeight + 1);
    }
  }

  function renderAll() {
    renderStations();
    renderTill();
    renderRuns();
    renderReview();
    renderTimeline();
    renderDecision();
    renderApproval();
    renderFooter();
    fitColumn2();
  }

  /* ---------------------------------------------------------------- start */
  function setupStatic() {
    $("claim").textContent = MT.claim;
    $("badges").replaceChildren(...MT.badges.map((b) => el("span", { class: "badge outline" }, b)));
    [$("col-till-title").textContent, $("col-mesh-title").textContent,
      $("col-approval-title").textContent] = MT.columns;
    $("band-title").textContent = ML.events;
    $("runs-title").textContent = ML.runs;
    $("review-title").textContent = ML.review;
    $("timeline-title").textContent = ML.timeline;
    $("hints").textContent = `${MT.fictional} · ${MT.simplification}`;
  }

  function tick() {
    const idle = (Date.now() - M.lastEventAt) / 1000;
    if (!M.recap && M.lastApproval && idle >= MT.recapAfterS) M.recap = true;
    renderClock();
    renderApproval();
    renderStations();
  }

  setupStatic();
  connectEvents({
    hello: onHello,
    pos_event: onPosEvent,
    insight: onInsight,
    sam_run: (d) => onSamRun(d, false),
    review: onReview,
    tool_call: (d) => onToolCall(d, false),
    proposal: onProposal,
    price_change: (d) => onPriceChange(d, false),
    counters: (d) => { M.counters = d; renderFooter(); },
    reset: onReset,
  });
  setInterval(tick, 1000);
  window.addEventListener("resize", render);
  render();
})();
