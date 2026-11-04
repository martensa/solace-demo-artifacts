"""Generate the BSG Grafana dashboard ConfigMap."""
import json

DS = {"type": "postgres", "uid": "sam-platform-db"}

# tasks carries only the generated ids (agent_<uuid>), so the node is
# recognised by the instruction the workflow sends it. That survives a
# re-create of the agents, which the ids do not.
NODE_CASE = """CASE
    WHEN t.handler_type = 'workflow' THEN 'Workflow-Lauf'
    WHEN t.initial_request_text LIKE 'Compare the alerting issuer%' THEN '2 bsg-quote-analyst'
    WHEN t.initial_request_text LIKE 'Decide from the reference prices%' THEN '3 bsg-market-context'
    WHEN t.initial_request_text LIKE 'Zweig emittentenspezifisch%' THEN '5 bsg-desk-communicator'
    WHEN t.initial_request_text LIKE 'Zweig marktweit%' THEN '5 bsg-desk-communicator'
    WHEN t.initial_request_text LIKE 'Auftrag eines QLP%' THEN '1 bsg-desk-assistant'
    ELSE coalesce(t.handler_name, '?')
  END"""

BSG = "t.entrypoint_id = '$ep'"
RANGE = "to_timestamp(t.start_time/1000.0) BETWEEN $__timeFrom() AND $__timeTo()"
LAST_RUN = f"""(SELECT id FROM tasks
     WHERE entrypoint_id = '$ep' AND handler_type = 'workflow'
           AND parent_task_id IS NULL
     ORDER BY start_time DESC LIMIT 1)"""


def sql(q):
    return {"datasource": DS, "rawSql": q, "format": "table",
            "rawQuery": True, "refId": "A"}


def text(title, content, x, y, w, h):
    return {"type": "text", "title": title, "transparent": True,
            "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "options": {"mode": "markdown", "content": content},
            "fieldConfig": {"defaults": {}, "overrides": []}}


def stat(title, q, x, y, w, h, unit=None, decimals=None, thresholds=None):
    defaults = {}
    if unit:
        defaults["unit"] = unit
    if decimals is not None:
        defaults["decimals"] = decimals
    if thresholds:
        defaults["thresholds"] = thresholds
    else:
        defaults["thresholds"] = {"mode": "absolute",
                                  "steps": [{"color": "text", "value": None}]}
    return {"type": "stat", "title": title,
            "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "targets": [sql(q)],
            "options": {"reduceOptions": {"calcs": ["lastNotNull"],
                                          "fields": "", "values": False},
                        "textMode": "auto", "colorMode": "value"},
            "fieldConfig": {"defaults": defaults, "overrides": []}}


def table(title, q, x, y, w, h, overrides=None):
    return {"type": "table", "title": title,
            "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "targets": [sql(q)],
            "options": {"showHeader": True},
            "fieldConfig": {"defaults": {"custom": {"align": "auto"}},
                            "overrides": overrides or []}}


def barchart(title, q, x, y, w, h):
    return {"type": "barchart", "title": title,
            "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "targets": [sql(q)],
            "options": {"xField": "Knoten", "orientation": "horizontal",
                        "showValue": "always",
                        "legend": {"showLegend": False, "displayMode": "list",
                                   "placement": "bottom"}},
            "fieldConfig": {"defaults": {"unit": "s", "decimals": 1,
                                         "color": {"mode": "palette-classic"}},
                            "overrides": []}}


panels = []
y = 0
panels.append(text("", (
    "## BSG Trading Desk Assistant -- ein Lauf im Detail\n"
    "**Alert -> Workflow -> Desk-Note.** Die deterministischen Schritte "
    "(`Alert anreichern`, `Desk-Note publizieren`) sind Tool-Knoten ohne "
    "Modell und tauchen hier nicht als Kosten auf; bezahlt werden nur die "
    "vier Agenten. Zeitraum oben rechts auf *Last 15 minutes* stellen."
), 0, y, 24, 3))
y += 3

panels.append(stat("Letzter Lauf: Alert bis Desk-Note",
                   f"""SELECT (t.end_time - t.start_time)/1000.0 AS "Sekunden"
FROM tasks t WHERE t.id = {LAST_RUN}""",
                   0, y, 5, 5, unit="s", decimals=1,
                   thresholds={"mode": "absolute", "steps": [
                       {"color": "green", "value": None},
                       {"color": "yellow", "value": 45},
                       {"color": "red", "value": 60}]}))
panels.append(stat("Tokens im letzten Lauf",
                   f"""SELECT sum(coalesce(t.total_input_tokens,0)
          + coalesce(t.total_output_tokens,0)) AS "Tokens"
FROM tasks t WHERE t.parent_task_id = {LAST_RUN}""",
                   5, y, 5, 5, decimals=0))
panels.append(stat("Laeufe im Zeitraum",
                   f"""SELECT count(*) AS "Laeufe" FROM tasks t
WHERE {BSG} AND t.handler_type = 'workflow'
  AND t.parent_task_id IS NULL AND {RANGE}""",
                   10, y, 4, 5, decimals=0))
panels.append(stat("Fehlgeschlagen",
                   f"""SELECT count(*) AS "Fehler" FROM tasks t
WHERE {BSG} AND t.handler_type = 'workflow' AND t.parent_task_id IS NULL
  AND t.status <> 'completed' AND {RANGE}""",
                   14, y, 4, 5, decimals=0,
                   thresholds={"mode": "absolute", "steps": [
                       {"color": "green", "value": None},
                       {"color": "red", "value": 1}]}))
panels.append(stat("Zweig des letzten Laufs",
                   f"""SELECT CASE
         WHEN bool_or(t.initial_request_text LIKE 'Zweig marktweit%')
           THEN 'marktweit'
         WHEN bool_or(t.initial_request_text LIKE 'Zweig emittentenspez%')
           THEN 'emittentenspezifisch'
         ELSE '-' END AS "Zweig"
FROM tasks t WHERE t.parent_task_id = {LAST_RUN}""",
                   18, y, 6, 5))
y += 5

panels.append(text("", "### Der letzte Lauf, Knoten fuer Knoten", 0, y, 24, 2))
y += 2

panels.append(table("Knoten des letzten Laufs", f"""SELECT
  {NODE_CASE} AS "Knoten",
  round((t.end_time - t.start_time)/1000.0, 1) AS "Sekunden",
  t.total_input_tokens AS "Input-Tokens",
  t.total_output_tokens AS "Output-Tokens",
  t.status AS "Status"
FROM tasks t
WHERE t.parent_task_id = {LAST_RUN}
ORDER BY t.start_time""", 0, y, 12, 8))

panels.append(barchart("Dauer je Knoten (letzter Lauf)", f"""SELECT
  {NODE_CASE} AS "Knoten",
  (t.end_time - t.start_time)/1000.0 AS "Sekunden"
FROM tasks t
WHERE t.parent_task_id = {LAST_RUN}
ORDER BY t.start_time""", 12, y, 12, 8))
y += 8

panels.append(text("", "### Alle Laeufe im Zeitraum", 0, y, 24, 2))
y += 2

panels.append(table("Laeufe", f"""SELECT
  to_timestamp(t.start_time/1000.0) AS "Start",
  round((t.end_time - t.start_time)/1000.0, 1) AS "Sekunden",
  t.status AS "Status",
  (SELECT CASE
     WHEN bool_or(c.initial_request_text LIKE 'Zweig marktweit%') THEN 'marktweit'
     WHEN bool_or(c.initial_request_text LIKE 'Zweig emittentenspez%')
       THEN 'emittentenspezifisch'
     ELSE '-' END
   FROM tasks c WHERE c.parent_task_id = t.id) AS "Zweig",
  (SELECT sum(coalesce(c.total_input_tokens,0) + coalesce(c.total_output_tokens,0))
   FROM tasks c WHERE c.parent_task_id = t.id) AS "Tokens",
  coalesce(t.error_message, '') AS "Fehler"
FROM tasks t
WHERE {BSG} AND t.handler_type = 'workflow' AND t.parent_task_id IS NULL
  AND {RANGE}
ORDER BY t.start_time DESC
LIMIT 20""", 0, y, 14, 8))

panels.append(table("Tokens je Agent (Zeitraum)", f"""SELECT
  {NODE_CASE} AS "Agent",
  count(*) AS "Aufrufe",
  sum(coalesce(t.total_input_tokens,0)) AS "Input",
  sum(coalesce(t.total_output_tokens,0)) AS "Output",
  round(avg((t.end_time - t.start_time)/1000.0), 1) AS "Sekunden (Mittel)"
FROM tasks t
WHERE {BSG} AND t.handler_type = 'agent' AND t.end_time IS NOT NULL AND {RANGE}
GROUP BY 1 ORDER BY 1""", 14, y, 10, 8))
y += 8

panels.append(text("", (
    "### Der Beleg\n"
    "**SAM Activities**: `https://sam.solace.lab` -> Activities -> den "
    "Lauf oeffnen -> *Performance* zeigt dieselben Knoten als Gantt. "
    "**Tempo**: Explore -> Tempo -> `sam-solace-lab/a2a` fuer die "
    "Broker-Spans jedes A2A-Hops. **Loki**: `{namespace=\"sam-solace-lab\"}` "
    "mit der traceID aus Activities."
), 0, y, 24, 3))

dashboard = {
    "uid": "sam-bsg-trading-desk",
    "title": "BSG Trading Desk Demo",
    "tags": ["sam", "bsg", "trading-desk"],
    "schemaVersion": 39,
    "editable": True,
    "refresh": "10s",
    "time": {"from": "now-15m", "to": "now"},
    "timezone": "browser",
    "templating": {"list": [{
        "name": "ep",
        "label": "Entrypoint",
        "type": "query",
        "datasource": DS,
        "refresh": 1,
        "query": ("SELECT DISTINCT entrypoint_id FROM tasks "
                  "WHERE initial_request_text LIKE '%watcher_api%' "
                  "AND entrypoint_id IS NOT NULL"),
        "current": {}, "options": [], "includeAll": False, "multi": False,
        "hide": 0,
    }]},
    "panels": panels,
}

body = json.dumps(dashboard, indent=1, ensure_ascii=False)
cm = {
    "apiVersion": "v1",
    "kind": "ConfigMap",
    "metadata": {
        "name": "dashboard-sam-bsg-trading-desk",
        "namespace": "sam-solace-lab",
        "labels": {"grafana_dashboard": "1"},
        "annotations": {"grafana_folder": "SAM"},
    },
    "data": {"sam-bsg-trading-desk.json": body},
}
import yaml  # noqa: E402
out = ("# Grafana dashboard for the BSG trading desk demo.\n"
       "# Generated by scripts/gen_dashboard.py -- edit that, not this file.\n"
       "#\n"
       "# Datasource `sam-platform-db` is the WebUI database (tasks), which\n"
       "# is where the per-task token and duration rows live. tasks carries\n"
       "# only generated ids, so each node is recognised by the instruction\n"
       "# the workflow sends it; that survives a re-create of the agents.\n")
print(out + yaml.safe_dump(cm, allow_unicode=True, sort_keys=False, width=10**6))
