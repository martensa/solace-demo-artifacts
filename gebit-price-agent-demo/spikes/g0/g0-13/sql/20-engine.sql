-- 20-engine.sql: Schema engine (gpos-engine), Eigentuemer :r_engine.
-- Quelle: D 7.1 ohne MHD-Felder plus Anhang A (trigger, approval,
-- inbound_delivery, competitor_observation, season_calendar, Spalten
-- an proposal); samrun und event_outbox fehlen in D und Anhang A [A].
-- Entfallen aus D 7.1: voucher_template, voucher (-> loyalty.offer,
-- loyalty.coupon, RL 4.3), active_promotion (-> pos.price_action);
-- article, article_price, basket, basket_line liegen in pos.
-- Keine FKs ueber Schemagrenzen (article_number als Text) [A].
-- Idempotent: "if not exists".

\if :{?role_prefix}
\else
\set role_prefix gpos
\endif
\set r_pos :role_prefix _pos
\set r_engine :role_prefix _engine
\set r_loyalty :role_prefix _loyalty
\set r_ui :role_prefix _ui

set role :"r_engine";

-- Stamm- und Presetdaten
create table if not exists engine.scenario (
  scenario_id text primary key,                     -- TR1..TR7, T2..T4
  name text, store_date date, store_time_start time,
  time_factor int, hero_article text, params jsonb);

-- D 7.1 ohne best_before (MHD); plan_today numeric statt int, weil TR2
-- mit 16,8 Stueck/Tag rechnet (RL 3.4) [A]
create table if not exists engine.scenario_article (
  scenario_id text references engine.scenario, article_number text,
  plan_today numeric(8,2), sold_until_start int, stock int,
  velocity_per_h numeric, elasticity numeric, horizon_h int,
  leftover_weight numeric, active_promo jsonb,
  primary key (scenario_id, article_number));

-- note_id als Schluessel fuer idempotente Seeds [A]
create table if not exists engine.store_note (
  note_id text primary key,
  scenario_id text references engine.scenario, article_number text,
  source text, note text);                          -- 'Lieferavis', 'Zentrale'

-- Quelle fuer ref30 (A01); enthaelt nie Messe-Aktionen (Plan 2.5).
-- kind ohne MHD; Schluessel fuer idempotente Seeds [A]
create table if not exists engine.price_history (
  scenario_id text, article_number text, store_id text,
  price numeric(8,2), valid_from timestamptz, valid_to timestamptz,
  kind text check (kind in ('REGULAR','PROMO')), announced boolean,
  primary key (scenario_id, article_number, store_id, valid_from));

create table if not exists engine.sales_daily (
  scenario_id text, article_number text, day date,
  units int, avg_price numeric(8,2),
  primary key (scenario_id, article_number, day));        -- PK [A]

create table if not exists engine.affinity_rule (
  antecedent text, consequent text, lift numeric, confidence numeric,
  primary key (antecedent, consequent));                   -- PK [A]

-- Anhang A: neue Datenquellen
create table if not exists engine.inbound_delivery (      -- TR2
  delivery_id text primary key, scenario_id text, article_number text,
  quantity int not null, expected_at timestamptz not null, note text);

create table if not exists engine.competitor_observation (  -- TR3
  scan_id text primary key, photo_id text, article_number text,
  readable boolean, competitor_price numeric(8,2),
  our_price numeric(8,2), gap_pct numeric(5,1), confidence numeric(3,2),
  verdict text not null, valid_to timestamptz, raw jsonb,
  created_at timestamptz not null default now());

create table if not exists engine.season_calendar (       -- TR6
  article_number text primary key, season text not null,
  season_end date not null, step_plan jsonb not null);

-- Laufzeit (pro Besuch zurueckgesetzt, ausser markiert)
create table if not exists engine.visit (
  visit_id text primary key, scenario_id text,
  started_at timestamptz, ended_at timestamptz, outcome text);   -- bleibt

create table if not exists engine.event_inbox (
  tx_id uuid, "offset" bigint, event_type text,
  created_at timestamptz, received_at timestamptz, via text,  -- direct | sam
  sam_run_id text, verdict text, contract_ok boolean,
  primary key (tx_id, "offset"));                             -- nachts geloescht

-- Anhang A
create table if not exists engine.trigger (
  trigger_id text primary key, kind text not null
    check (kind in ('slow_seller','overstock','competitor_price','season_end')),
  article_number text not null, visit_id text, tx_id uuid,
  source_event text, facts jsonb not null, status text not null,
  created_at timestamptz not null default now(), sam_run_id text);

-- D 7.1 plus die drei Spalten aus Anhang A (dort als alter table)
create table if not exists engine.proposal (
  proposal_id text primary key, visit_id text,
  article_number text, kind text, status text, slots jsonb, blocked jsonb,
  checks jsonb, recommended text, chosen_slot text, pct_shown int,
  new_price numeric(8,2), ref30 numeric(8,2), valid_to timestamptz,
  ai jsonb, text_source text, via text, proposal_hash text,
  created_at timestamptz, ready_at timestamptz, decided_at timestamptz,
  applied_at timestamptz, expires_at timestamptz, sam_run_id text,
  trigger_id text references engine.trigger,               -- Anhang A
  needs_approval boolean not null default true,            -- Anhang A
  action_kind text not null default 'PROMOTION'            -- Anhang A
    check (action_kind in                                  -- Check [A]
      ('PROMOTION','MARKDOWN','COUPON_CAMPAIGN','SPECIAL_COUPON')));
create index if not exists proposal_visit on engine.proposal (visit_id);

-- Anhang A
create table if not exists engine.approval (
  proposal_id text primary key references engine.proposal,
  via text not null check (via in ('native','kiosk','fallback','teams','chat')),
  sam_run_id text, sam_request_id text, inbox_item_id text,
  pending_at timestamptz, answered_at timestamptz,
  human_answer text check (human_answer in ('approve','reject')),
  answered_hash text, answered_device text,          -- Waechter Flaeche A (3.5)
  outcome text check (outcome in
    ('approved','rejected','expired','superseded','failed','blocked')),
  error_code text);                    -- z. B. HIL_DENIED, NOTIFY_FAILED

create table if not exists engine.decision (
  decision_id text primary key,
  proposal_id text unique references engine.proposal, action text, pct numeric,
  reason_code text, approver_role text, approver_ref text,
  decided_at timestamptz, token_ok boolean, via text);

create table if not exists engine.price_change (
  change_id text primary key,
  proposal_id text unique, kind text, old_price numeric, new_price numeric,
  ref30 numeric, port_impl text, requested_at timestamptz,
  applied_at timestamptz, esl_ack_at timestamptz, first_scan_at timestamptz);

-- [A] eine Zeile je Tool-Aufruf; Quelle fuer gpos/v1/samrun/{runId} und
-- den Monitor-Ticker (Plan 2.4, R18)
create table if not exists engine.samrun (
  id bigserial primary key,
  run_id text not null, workflow text, node text not null, tool text,
  verdict text, ms int, visit_id text, ref text,
  payload jsonb not null default '{}',
  created_at timestamptz not null default now());
create index if not exists samrun_run on engine.samrun (run_id);
create index if not exists samrun_visit on engine.samrun (visit_id);

create table if not exists engine.audit_event (
  id bigserial primary key, ts timestamptz,
  kind text, ref text, payload jsonb);              -- nur anhaengen, bleibt

create table if not exists engine.kpi_day (
  day date primary key, scans int, sam_runs int,
  llm_calls int, proposals int, approved int, adjusted int, rejected int,
  expired int, vouchers int, redeemed int, fallbacks int,
  contract_events int, contract_errors int);

-- [A] Transaktions-Outbox, gleiche Form wie pos/loyalty
create table if not exists engine.event_outbox (
  id               bigserial primary key,
  aggregate_id     text not null,                   -- proposal_id, trigger_id
  aggregate_offset bigint not null,
  event_type       text not null,
  topic            text not null,                   -- gpos/v1/...
  payload          jsonb not null,
  created_at       timestamptz not null default now(),
  published_at     timestamptz,
  unique (aggregate_id, aggregate_offset));
create index if not exists event_outbox_unpublished
  on engine.event_outbox (id) where published_at is null;

reset role;
