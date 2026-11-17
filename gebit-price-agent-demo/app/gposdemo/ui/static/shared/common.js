/* gpos-ui shared helpers for /kasse and /monitor. Plain ES2020, no build step, no
   external libraries. Texts come from /static/shared/texts.js (window.GPOS_TEXTS).
   DOM is built with textContent only: event data is never interpreted as HTML. */
(function () {
  "use strict";

  const T = window.GPOS_TEXTS;

  /** el("div", {class: "x", onclick: fn}, child, "text") */
  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === undefined || value === null || value === false) continue;
      if (key === "class") node.className = value;
      else if (key.startsWith("on") && typeof value === "function") {
        node.addEventListener(key.slice(2), value);
      } else node.setAttribute(key, value === true ? "" : String(value));
    }
    for (const child of children.flat()) {
      if (child === undefined || child === null || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  const SVG_NS = "http://www.w3.org/2000/svg";
  const ICONS = {
    lock: "M7 10V7a5 5 0 0 1 10 0v3h1a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-9" +
      "a1 1 0 0 1 1-1h1zm2 0h6V7a3 3 0 0 0-6 0v3z",
    check: "M9.5 16.2 5.3 12l-1.4 1.4 5.6 5.6L20.1 8.4 18.7 7z",
    cross: "M6.4 5 5 6.4 10.6 12 5 17.6 6.4 19l5.6-5.6 5.6 5.6 1.4-1.4-5.6-5.6L19 6.4 " +
      "17.6 5 12 10.6z",
    arrow: "M4 11h12.2l-5.6-5.6L12 4l8 8-8 8-1.4-1.4 5.6-5.6H4z",
  };

  function icon(name, cls) {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("class", "icon " + (cls || ""));
    svg.setAttribute("aria-hidden", "true");
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", ICONS[name]);
    path.setAttribute("fill", "currentColor");
    svg.append(path);
    return svg;
  }

  /** "{a} und {b}" with {a: 1, b: 2} */
  function fmt(template, vars) {
    return template.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
  }

  /** Scan-analysis chip of an insight {code, text}: colour scheme of 10.4. */
  function chip(insight) {
    if (!insight || !insight.code) return null;
    const spec = T.chips[insight.code] || { tone: "grey", lock: false, text: "" };
    const text = insight.text || spec.text || insight.code;
    return el("span", { class: "chip " + spec.tone, title: text },
      spec.lock ? icon("lock") : null, text);
  }

  /** "9,99" -> 999 (cents); "" -> 0 */
  function cents(label) {
    if (!label) return 0;
    const m = String(label).trim().match(/^(-?\d+)(?:[.,](\d{1,2}))?/);
    if (!m) return 0;
    const sign = m[1].startsWith("-") ? -1 : 1;
    return Number(m[1]) * 100 + sign * Number((m[2] || "0").padEnd(2, "0"));
  }

  /** 999 -> "9,99" */
  function euro(value) {
    const sign = value < 0 ? "-" : "";
    const abs = Math.abs(value);
    return sign + Math.floor(abs / 100) + "," + String(abs % 100).padStart(2, "0");
  }

  /** 72 s -> "1:12" */
  function elapsed(seconds) {
    const s = Math.max(0, Math.floor(seconds));
    return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  }

  function stateText(state) {
    return T.states[state] || state || "";
  }

  async function api(path, options) {
    const opts = Object.assign({ headers: {} }, options || {});
    if (opts.json !== undefined) {
      opts.method = opts.method || "POST";
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.json);
      delete opts.json;
    }
    const response = await fetch(path, opts);
    let body = null;
    try {
      body = await response.json();
    } catch (e) {
      body = null;
    }
    return { status: response.status, ok: response.ok, body: body || {} };
  }

  /** EventSource on /api/events with named handlers; shows a banner while offline. */
  function connectEvents(handlers) {
    const banner = el("div", { class: "conn hidden", role: "status" }, T.connectionLost);
    document.body.append(banner);
    const source = new EventSource("/api/events");
    source.onopen = () => banner.classList.add("hidden");
    source.onerror = () => banner.classList.remove("hidden");
    for (const [kind, handler] of Object.entries(handlers)) {
      source.addEventListener(kind, (ev) => {
        let data = {};
        try {
          data = JSON.parse(ev.data);
        } catch (e) {
          return;
        }
        handler(data);
      });
    }
    return source;
  }

  /** Re-render at most once per animation frame. */
  function scheduler(render) {
    let queued = false;
    return function schedule() {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => {
        queued = false;
        render();
      });
    };
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  /** Resolve true as soon as pred() holds, false after timeoutMs. */
  async function waitFor(pred, timeoutMs) {
    const end = Date.now() + timeoutMs;
    while (Date.now() < end) {
      if (pred()) return true;
      await sleep(50);
    }
    return pred();
  }

  window.GPOS = { T, el, icon, fmt, chip, cents, euro, elapsed, stateText, api,
    connectEvents, scheduler, sleep, waitFor };
})();
