/* /kasse: till simulator (UC1-BUILD-SPEC 10.3). Calls only the BFF facade
   (POST /api/pos/{Method}); position ids and totals come from SSE pos_event, because
   GEBIT does not return them synchronously. */
(function () {
  "use strict";

  const { T, el, fmt, chip, cents, euro, api, connectEvents, scheduler, sleep, waitFor } =
    window.GPOS;
  const K = T.kasse;
  const L = K.labels;
  const OPEN = ["CREATED", "OPEN"];
  const PAYMENT = ["IN_PAYMENT", "IN_CHARGING_FINANCIAL_TRANSACTION", "IN_CLOSING"];
  const FINAL = ["CLOSED", "CANCELLED", "IN_CANCELLATION", "RESET"];
  const LINE_WAIT_MS = 3000;

  const params = new URLSearchParams(location.search);
  const testMode = params.get("test") === "1";
  const tillParam = testMode ? params.get("till") : null;
  const tillQuery = tillParam ? "?till=" + encodeURIComponent(tillParam) : "";

  const S = {
    till: tillParam || "",
    booth: "",
    catalog: { articles: [], categories: [], byGtin: new Map() },
    cards: [],
    scenarios: [],
    tab: "",
    bon: null,
    selected: null,
    busy: false,
  };

  const $ = (id) => document.getElementById(id);
  const render = scheduler(renderAll);

  /* ---------------------------------------------------------------- helpers */
  function uuid4() {
    const b = crypto.getRandomValues(new Uint8Array(16));
    b[6] = (b[6] & 0x0f) | 0x40;
    b[8] = (b[8] & 0x3f) | 0x80;
    const h = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
    return [h.slice(0, 8), h.slice(8, 12), h.slice(12, 16), h.slice(16, 20), h.slice(20)]
      .join("-");
  }

  function setMsg(text, kind) {
    const node = $("msg");
    node.textContent = text || "";
    node.className = "msg " + (kind || "");
  }

  function newBon(txId) {
    return { tx_id: txId, status: "CREATED", receipt_number: "", total: "", card: "",
      persona: "", lines: new Map() };
  }

  function bonFromState(raw) {
    if (!raw) return null;
    const bon = Object.assign(newBon(raw.tx_id), raw, { lines: new Map() });
    for (const line of raw.lines || []) bon.lines.set(line.position_id, line);
    return bon;
  }

  const isOpen = () => S.bon && OPEN.includes(S.bon.status);
  const isActive = () => S.bon && !FINAL.includes(S.bon.status);
  const activeLines = () => (S.bon ? [...S.bon.lines.values()].filter((l) => !l.voided) : []);

  function bonTotalCents() {
    if (S.bon && S.bon.total) return cents(S.bon.total);
    return activeLines().reduce((sum, l) => sum + cents(l.price) * (l.item_count || 1), 0);
  }

  function statusKey() {
    if (!S.bon) return "ready";
    if (S.bon.status === "CLOSED") return "closed";
    if (FINAL.includes(S.bon.status)) return "ready";
    if (PAYMENT.includes(S.bon.status)) return "payment";
    return "open";
  }

  /* ---------------------------------------------------------------- facade */
  async function pos(method, body) {
    const r = await api(`/api/pos/${method}${tillQuery}`, { json: body });
    if (!r.ok || !r.body.ok) {
      const code = r.body.code ? r.body.code + ": " : "";
      throw new Error(code + (r.body.message || "HTTP " + r.status));
    }
    return r.body.result || {};
  }

  async function cancelBon() {
    await pos("CancelPurchaseTransaction", { purchaseTransactionId: S.bon.tx_id,
      cancellationReason: "Abbruch an der Kasse", cancellationReasonCode: "CASHIER" });
    S.bon.status = "CANCELLED";
    S.selected = null;
  }

  async function createBon() {
    if (isActive()) {
      try {
        await cancelBon();
      } catch (e) {
        /* the receipt is gone already (reset, other tab): POS resets an open basket of
           the till on CreatePurchaseTransaction anyway, so the till never gets stuck */
        console.warn("cancel of the previous receipt failed:", e.message);
      }
    }
    const result = await pos("CreatePurchaseTransaction", {});
    S.bon = newBon(result.purchaseTransactionId);
    S.selected = null;
    render();
    return S.bon.tx_id;
  }

  async function ensureBon() {
    return isOpen() ? S.bon.tx_id : createBon();
  }

  async function scan(ean, inputMethod) {
    const article = S.catalog.byGtin.get(ean);
    if (!article) {
      setMsg(fmt(K.unknownEan, { ean }), "error");
      return false;
    }
    const tx = await ensureBon();
    await pos("AddArticle", { purchaseTransactionId: tx, articleId: article.article_id,
      itemCount: 1, capturingInformation: { inputMethod, inputType: "EAN13",
        inputValue: ean } });
    setMsg("");
    return true;
  }

  async function assignCard(card) {
    const tx = await ensureBon();
    await pos("AssignLoyaltyMembership", { purchaseTransactionId: tx,
      membershipIdentificationValue: card,
      capturingInformation: { inputMethod: "SCANNER", inputType: "LOYALTY_CARD",
        inputValue: card } });
    const known = S.cards.find((c) => c.card === card);
    S.bon.card = card;
    S.bon.persona = known ? known.persona : "";
    render();
  }

  async function voidLine() {
    if (!S.selected || !isOpen()) return;
    await pos("VoidArticlePosition", { purchaseTransactionId: S.bon.tx_id,
      positionId: S.selected });
    S.selected = null;
  }

  /** Cash with the next full 5-euro amount (1.3). */
  async function payCash() {
    if (!isOpen() || activeLines().length === 0) return;
    const total = bonTotalCents();
    const amount = Math.max(5, Math.ceil(total / 500) * 5) * 100;
    const tx = S.bon.tx_id;
    await pos("StartPaymentProcess", { purchaseTransactionId: tx });
    await pos("CreateCashPayment", { purchaseTransactionId: tx,
      amount: { currency: "EUR", amount: { scale: 2, intVal: String(amount) } },
      clientId: `kasse-${S.till}`, clientTransactionId: uuid4() });
    setMsg(fmt(L.paid, { amount: euro(amount) }), "ok");
  }

  /** Run one user action; errors show as a red message, never as an exception. */
  async function guarded(action) {
    try {
      await action();
    } catch (e) {
      setMsg(fmt(L.error, { message: e.message }), "error");
    } finally {
      render();
      if (!$("reset-dialog").open) $("ean").focus();
    }
  }

  /* ---------------------------------------------------------------- scenarios */
  async function playScenario(scenario) {
    if (S.busy) return;
    S.busy = true;
    render();
    let scans = 0;
    try {
      for (const [i, step] of scenario.steps.entries()) {
        $("scenario-progress").textContent = fmt(L.scenarioRunning, {
          label: `${scenario.id} ${scenario.label}`, step: i + 1, steps: scenario.steps.length });
        if (step.op === "new") {
          await createBon();
          scans = 0;
        } else if (step.op === "card") {
          await assignCard(step.value);
        } else if (step.op === "scan") {
          if (!(await scan(step.value, "SCANNER"))) break;
          scans += 1;
          await waitFor(() => S.bon && S.bon.lines.size >= scans, LINE_WAIT_MS);
        } else if (step.op === "pay") {
          await waitFor(() => S.bon && S.bon.lines.size >= scans && S.bon.total, LINE_WAIT_MS);
          await payCash();
        }
        if (i < scenario.steps.length - 1) await sleep(K.scenarioStepMs);
      }
    } catch (e) {
      setMsg(fmt(L.error, { message: e.message }), "error");
    } finally {
      S.busy = false;
      $("scenario-progress").textContent = "";
      render();
    }
  }

  /* ---------------------------------------------------------------- events */
  function onPosEvent(d) {
    if (d.till !== S.till) return;
    if (!S.bon || S.bon.tx_id !== d.tx_id) S.bon = newBon(d.tx_id);
    const bon = S.bon;
    if ((d.offset || 0) >= (bon.last_offset || 0)) {
      bon.last_offset = d.offset || 0;
      if (d.status) bon.status = d.status;
      if (d.total) bon.total = d.total;
    }
    if (d.receipt_number) bon.receipt_number = d.receipt_number;
    if (d.event === "PositionAdded" && d.position_id) {
      bon.lines.set(d.position_id, { position_id: d.position_id, article_number: d.article_number,
        description: d.description, item_count: d.item_count || 1, price: d.price,
        price_source: d.price_source, regular_price: d.regular_price, voided: false,
        insight: null });
    } else if (d.event === "ArticlePositionVoided" && bon.lines.has(d.position_id)) {
      bon.lines.get(d.position_id).voided = true;
    } else if (d.event === "LoyaltyMembershipAssigned" && d.card) {
      const known = S.cards.find((c) => c.card === d.card);
      bon.card = d.card;
      bon.persona = known ? known.persona : "";
    }
    render();
  }

  function onInsight(d) {
    if (d.till !== S.till || !S.bon || S.bon.tx_id !== d.tx_id) return;
    const line = S.bon.lines.get(d.position_id);
    if (line) {
      line.insight = { code: d.code, text: d.text };
      render();
    }
  }

  async function loadCatalog() {
    const r = await api("/api/catalog" + tillQuery);
    if (!r.ok) {
      setMsg(L.catalogError, "error");
      return;
    }
    S.catalog = { articles: r.body.articles, categories: r.body.categories,
      byGtin: new Map(r.body.articles.map((a) => [a.gtin, a])) };
    if (!S.catalog.categories.some((c) => c.tag === S.tab)) {
      S.tab = S.catalog.categories.length ? S.catalog.categories[0].tag : "";
    }
    render();
  }

  /* ---------------------------------------------------------------- render */
  function priceNode(article) {
    if (article.price_source && article.price_source !== "REGULAR") {
      return el("span", {},
        el("span", { class: "badge action" }, K.actionBadge), " ",
        el("span", { class: "strike" }, article.regular_price + " €"), " ",
        article.price + " €");
    }
    return article.price + " €";
  }

  function renderHead() {
    const test = testMode && S.till !== S.booth;
    $("head-title").textContent = fmt(test ? K.testHead : K.head, { till: S.till });
    $("head-bon-label").textContent = S.bon ? L.bon : "";
    $("head-bon").textContent = S.bon ? (S.bon.receipt_number || S.bon.tx_id.slice(0, 8)) : "";
    const key = statusKey();
    $("head-status").textContent = K.status[key];
    $("head-status").className = "status " + key;
  }

  function renderCatalog() {
    $("tabs").replaceChildren(...S.catalog.categories.map((c) =>
      el("button", { class: "tab" + (c.tag === S.tab ? " active" : ""), type: "button",
        onclick: () => { S.tab = c.tag; render(); } }, c.label)));
    const tiles = S.catalog.articles.filter((a) => a.category === S.tab).map((a) =>
      el("button", { class: "tile" + (a.price_source !== "REGULAR" ? " action" : ""),
        type: "button", disabled: S.busy, onclick: () => guarded(() => scan(a.gtin, "TOUCH")) },
        el("span", { class: "name" }, a.name),
        el("span", { class: "pack" }, a.pack),
        el("span", { class: "price" }, priceNode(a)),
        el("span", { class: "ean-small" }, a.gtin)));
    $("grid").replaceChildren(...tiles);
  }

  function renderBars() {
    $("cards").replaceChildren(...S.cards.map((c) =>
      el("button", { class: "btn", type: "button", disabled: S.busy, title: c.card,
        onclick: () => guarded(() => assignCard(c.card)) }, c.persona)));
    $("scenarios").replaceChildren(...S.scenarios.map((s) =>
      el("button", { class: "btn", type: "button", disabled: S.busy,
        onclick: () => playScenario(s) }, `${s.id} ${s.label}`)));
  }

  function renderBon() {
    const bon = S.bon;
    $("bon-card").textContent = bon && bon.card
      ? `${T.kasse.cardBar}: ${bon.persona || bon.card} (${bon.card})` : "";
    const lines = bon ? [...bon.lines.values()] : [];
    $("lines").replaceChildren(...lines.map((l) =>
      el("li", { class: "line" + (l.voided ? " voided" : "") +
          (l.position_id === S.selected ? " selected" : ""),
        onclick: () => { if (!l.voided) { S.selected = l.position_id; render(); } } },
        el("span", { class: "line-name" }, `${l.item_count || 1} × ${l.description}`),
        el("span", { class: "line-price" }, l.price ? l.price + " €" : ""),
        el("span", { class: "line-meta" },
          l.price_source && l.price_source !== "REGULAR"
            ? el("span", { class: "badge action" }, K.actionBadge) : null,
          l.price_source && l.price_source !== "REGULAR" && l.regular_price
            ? el("span", { class: "strike" }, l.regular_price + " €") : null,
          chip(l.insight)))));
    $("total").textContent = euro(bonTotalCents()) + " €";
    $("btn-new").disabled = S.busy;
    $("btn-void").disabled = S.busy || !S.selected || !isOpen();
    $("btn-pay").disabled = S.busy || !isOpen() || activeLines().length === 0;
    $("btn-cancel").disabled = S.busy || !isActive();
  }

  function renderAll() {
    renderHead();
    renderCatalog();
    renderBars();
    renderBon();
  }

  /* ---------------------------------------------------------------- reset dialog */
  function setupResetDialog() {
    const dialog = $("reset-dialog");
    $("reset-title").textContent = L.resetTitle;
    $("reset-hint").replaceChildren(...K.resetHint.split(/(make [a-z-]+)/).map((part, i) =>
      (i % 2 ? el("code", { class: "nowrap" }, part) : part)));
    $("reset-close").textContent = L.close;
    $("reset-go").textContent = L.resetConfirm;
    $("reset-scopes").replaceChildren(...Object.entries(K.resetScopes).map(([scope, label], i) =>
      el("label", {}, el("input", { type: "radio", name: "scope", value: scope,
        checked: i === 0 }), label)));
    $("btn-reset").onclick = () => {
      $("reset-result").textContent = "";
      dialog.showModal();
    };
    $("reset-go").onclick = async () => {
      const scope = dialog.querySelector("input[name=scope]:checked").value;
      $("reset-go").disabled = true;
      const r = await api("/api/demo/reset", { json: { scope } });
      $("reset-go").disabled = false;
      const failed = Object.entries(r.body.steps || {}).filter(([, v]) => !v.ok)
        .map(([k]) => k);
      $("reset-result").textContent = r.ok && r.body.ok ? L.resetDone
        : fmt(L.resetFailed, { steps: failed.join(", ") || "HTTP " + r.status });
      $("reset-result").className = "msg " + (r.ok && r.body.ok ? "ok" : "error");
    };
  }

  /* ---------------------------------------------------------------- start */
  function setupStatic() {
    $("ean").placeholder = K.eanPlaceholder;
    $("ean-ok").textContent = L.eanButton;
    $("cards-title").textContent = K.cardBar;
    $("scenarios-title").textContent = K.scenarioBar;
    $("bon-title").textContent = L.bon;
    $("sum-label").textContent = L.sum;
    $("btn-new").textContent = K.buttons.new;
    $("btn-void").textContent = K.buttons.void;
    $("btn-void").title = L.selectLine;
    $("btn-pay").textContent = K.buttons.pay;
    $("btn-cancel").textContent = K.buttons.cancel;
    $("btn-reset").textContent = K.buttons.reset;
    $("test-switch-label").textContent = K.testSwitch;
    $("btn-new").onclick = () => guarded(createBon);
    $("btn-void").onclick = () => guarded(voidLine);
    $("btn-pay").onclick = () => guarded(payCash);
    $("btn-cancel").onclick = () => guarded(cancelBon);
    $("scan-form").onsubmit = (ev) => {
      ev.preventDefault();
      const ean = $("ean").value.trim();
      $("ean").value = "";
      if (ean) guarded(() => scan(ean, "SCANNER"));
    };
    if (testMode) {
      $("test-switch").classList.remove("hidden");
      $("test-toggle").checked = tillParam === "99";
      $("test-toggle").onchange = () => {
        location.search = $("test-toggle").checked ? "?test=1&till=99" : "?test=1";
      };
    }
    setupResetDialog();
  }

  async function start() {
    setupStatic();
    const [state, cards, scenarios] = await Promise.all([
      api("/api/state" + tillQuery), api("/api/cards"), api("/api/scenarios")]);
    S.till = state.body.till || S.till;
    S.booth = (state.body.booth || {}).till || "";
    S.bon = bonFromState(state.body.bon);
    S.cards = Array.isArray(cards.body) ? cards.body : [];
    S.scenarios = Array.isArray(scenarios.body) ? scenarios.body : [];
    await loadCatalog();
    connectEvents({
      pos_event: onPosEvent,
      insight: onInsight,
      price_change: () => loadCatalog(),
      reset: () => {
        S.bon = null;
        S.selected = null;
        setMsg("");
        loadCatalog();
      },
    });
    render();
  }

  start();
})();
