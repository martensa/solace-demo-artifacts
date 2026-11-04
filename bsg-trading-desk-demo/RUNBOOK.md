# Runbook: BSG Trading Desk Assistant

Cheat sheet for the show. Times are targets; the deterministic part
(watch, alert) is measured, the SAM part is still to be measured on
the cluster after Gate 0.

## Before the audience arrives

```bash
make demo-up        # idempotent; prints the URLs
make demo-reset     # starting state
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
   alert about 10-12 s after the click (measured locally: 10.2 s).
3. **Workflow** (1:30-2:30). The node list fills: Alert anreichern,
   bsg-quote-analyst, bsg-market-context, Verzweigung
   (emittentenspezifisch), bsg-desk-communicator, Desk-Note
   publizieren. Target: note with chart under 60 s after the alert.
4. **Mensch entscheidet** (2:30-3:00). Click
   "Plausibilitaetspruefung fuer Alpha starten". The ticker marks
   Alpha "in Pruefung"; the action event closes the loop.

Close (3:00-5:00): "Grafana" link (tokens and duration per `bsg-`
agent, last 15 minutes) and "SAM Activities" (the workflow run with
its nodes).

## Reserve: second branch (about 1.5 minutes)

1. `make demo-reset` (or the Reset button), then step 1 again.
2. Click "Marktweit: Volatilitaetssprung": reference jumps 2-3 %,
   all issuers widen, a high-impact news item appears.
3. Expected: the branch shows "marktweit", the note says "keine
   Emittentenmassnahme".

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
