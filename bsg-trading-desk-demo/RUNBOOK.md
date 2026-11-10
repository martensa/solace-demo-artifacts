# Runbook: BSG Trading Desk Assistant

Cheat sheet for the show. Every number below was measured on the lab
cluster on 2026-11-04 (SAM 2.493.0), driving the four steps through
the UI itself. The lab runs SAM 2.542.1 since 2026-11-10; an
API-driven re-check there (same endpoints as the UI buttons) gave
reply 6.8 s, alert 10.4 s, note 23.1 s after the alert issuer
specific and 7.4 s / 10.5 s / 18.9 s market wide.

## Before the audience arrives

```bash
sam auth login solace-lab   # the CLI token cache expires daily
make demo-up                # idempotent; prints the URLs
make demo-reset             # starting state
```

- Demo UI: `https://bsg-desk.solace.lab`
  (fallback: `make port-forward`, then `http://localhost:8090`)
- SAM: `https://sam.solace.lab`, logged in as `power_user`
- Grafana: `https://monitoring.solace.lab`
- Check: ticker moves, header shows "Mesh verbunden", step 1 shows
  no fallback banner.

## The four steps (about 5 minutes)

1. **Watch starten** (0:00-1:00). Click "Auftrag an den
   Desk-Assistenten". Expected within about 10 s: the assistant's
   German reply and, in step 1, watch id, topic filter
   `bsg/quotes/alpha/dax-turbo/>` and the condition
   `spread_pct > 0.5`, 10 s hold.
2. **Szenario auslösen** (1:00-1:30). Click "Alpha: Spread weitet
   sich". The ticker turns Alpha red (0.8 %). Expected: exactly one
   alert about 10-12 s after the click (measured in the cluster:
   10.3 s, three runs).
3. **Workflow** (1:30-2:30). The node list fills: Alert anreichern
   (Tool), bsg-quote-analyst and bsg-market-context (which run in
   parallel), Verzweigung auf scope (Switch), bsg-desk-communicator,
   Desk-Note publizieren (Tool). The two tool nodes report
   themselves; the agent rows in between are inferred, because SAM's
   status events live on a VPN the UI cannot read (see the README's
   decision on the VPN), so their timing on screen is the whole run,
   not their own. Measured: note with chart **18.0 s** after the
   alert, against a 60 s budget. The real split is analyst 8.7 s and
   context 5.3 s in parallel, then the communicator 11.1 s --
   the Grafana dashboard shows it.
4. **Mensch entscheidet** (2:30-3:00). Click
   "Plausibilitaetspruefung fuer Alpha starten". The ticker marks
   Alpha "in Pruefung"; the action event closes the loop.

Close (3:00-5:00): the "Grafana" link opens
`BSG Trading Desk Demo`: duration and tokens of the last run per
node, the branch it took, and a table of runs (about 60k tokens
issuer specific, 92k market wide). "SAM Activities" shows the same
run with its nodes as a Gantt.

## Reserve: second branch (about 1.5 minutes)

1. `make demo-reset` (or the Reset button), then step 1 again.
2. Click "Marktweit: Volatilitaetssprung": reference jumps 2-3 %,
   all issuers widen, a high-impact news item appears.
3. Expected: the branch shows "marktweit", the note says "keine
   Emittentenmassnahme". Measured: 20.3 s from the alert, with
   "Beta (0,91 %) und Gamma (0,89 %) zeigen vergleichbar erhoehte
   Spannen ... DAX in letzten 60 s um 3,42 % gefallen".

## Fallbacks, in this order

1. Agent does not answer step 1: set `ENTRY_MODE=direct` in the
   ConfigMap `bsg-demo-config` and restart `demo-ui`; the UI then
   publishes the watch itself and shows a banner saying so.
2. UI unreachable: `make port-forward` and `http://localhost:8090`.
3. Button does not react: `make scenario-wide-spread ISSUER=alpha
   DURATION=30` or `make scenario-market-wide DURATION=30`.
4. Workflow hangs: the run times out after 90 s and reports on
   `bsg/desk/errors` (shown in the event stream); `make demo-reset`
   and start again.

## Reset and removal

- `make demo-reset` -- scenario reset, watches cleared, issuer
  status normal, UI stream cleared (a few seconds).
- `make uninstall` -- removes everything the demo created.
