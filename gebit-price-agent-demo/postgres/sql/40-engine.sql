-- 40-engine.sql: schema engine (gpos-engine, gpos-gate), owner :r_engine. Idempotent.
\if :{?role_prefix}
\else
\set role_prefix gpos
\endif
\set r_engine :role_prefix _engine

set role :"r_engine";

create sequence if not exists engine.review_seq;
create sequence if not exists engine.proposal_seq;

-- every POS event that reached SAM R1 (dedup key txId:offset)
create table if not exists engine.event_inbox (
  tx_id          uuid not null,
  "offset"       bigint not null,
  event_type     text not null,
  store_id       text not null,
  till_id        text not null,
  event_ts       timestamptz,                       -- header.eventTimestamp (real time)
  received_at    timestamptz not null default now(),
  sam_run_id     text,
  verdict        text not null,
  payload_sha256 text not null,                     -- of canonical JSON (sorted keys)
  primary key (tx_id, "offset"));

create table if not exists engine.insight (
  id             bigserial primary key,
  tx_id          uuid not null,
  store_id       text not null,
  till_id        text not null,
  position_id    text,
  article_number text,
  code           text not null,
  text           text not null,
  facts          jsonb not null default '{}',
  sam_run_id     text,
  created_at     timestamptz not null default now());
create index if not exists insight_tx on engine.insight (tx_id);

create table if not exists engine.review (
  review_id      text primary key,                  -- 'GR-270216-0007'
  tx_id          uuid not null unique,
  store_id       text not null,
  till_id        text not null,
  membership_id  text,
  status         text not null check (status in
                   ('requested','prepared','proposed','no_action','no_candidates',
                    'only_blocked','deferred','blocked','failed','superseded')),
  lines          jsonb not null default '[]',       -- per line signals (UI, 7.2)
  agent_input    text,
  agent_decision jsonb,
  run_id_raise   text,
  run_id_review  text,
  error          text,
  created_at     timestamptz not null default now(),
  prepared_at    timestamptz,
  decided_at     timestamptz);
create index if not exists review_till on engine.review (store_id, till_id, created_at);

create table if not exists engine.proposal (
  proposal_id    text primary key,                  -- 'GP-270216-0003'
  review_id      text not null unique references engine.review,
  tx_id          uuid not null,
  store_id       text not null,
  till_id        text not null,
  article_number text not null,
  article_name   text not null,
  reason         text not null check (reason in
                   ('slow_seller','season_end','customer_behaviour')),
  step_requested int not null,                      -- agent's step_pct (information)
  step_pct       int not null check (step_pct in (10,20,30)),  -- engine: suggested
  clamped        boolean not null default false,    -- true: agent step was corrected
  regular_price  numeric(8,2) not null,
  new_price      numeric(8,2) not null,
  ref30          numeric(8,2) not null,
  pct_shown      int not null,
  margin_pct_new numeric(5,1) not null,
  base_price_label text,
  valid_from     timestamptz not null,
  valid_to       timestamptz not null,
  headline       text not null,
  rationale      text not null,
  facts_line     text not null,
  note           text not null default '',          -- e.g. 'Rücknahme der Preiserhöhung
                                                    --  vom 11.01.' (6.7 step 8)
  text_source    text not null check (text_source in ('ai','template')),
  guardrails     jsonb not null,
  proposal_hash  text not null,
  status         text not null check (status in
                   ('ready','pending','approved','rejected','expired','failed',
                    'superseded','blocked')),
  status_reason  text,
  run_id_stage   text,
  run_id_approval text,
  created_at     timestamptz not null default now(),
  pending_at     timestamptz,
  decided_at     timestamptz,
  check (new_price < regular_price));
-- at most one open proposal per till
create unique index if not exists proposal_one_open_per_till
  on engine.proposal (store_id, till_id) where status in ('ready','pending');

create table if not exists engine.approval (
  proposal_id       text primary key references engine.proposal,
  run_id            text not null,                  -- run of check_proposal
  checked_at        timestamptz not null,           -- real time
  apply_calls       int not null default 0,
  first_apply_at    timestamptz,
  last_apply_status text,
  agent_status      text,
  outcome           text check (outcome in
                      ('approved','rejected','expired','failed','superseded','blocked')),
  error             text,
  sam_error_at      timestamptz,                    -- R4 errorOutput seen (11.8)
  decided_at        timestamptz);

create table if not exists engine.price_change (
  action_id      text primary key,                  -- from WWS
  proposal_id    text not null unique references engine.proposal,
  article_number text not null,
  store_id       text not null,
  old_price      numeric(8,2) not null,
  new_price      numeric(8,2) not null,
  ref30          numeric(8,2) not null,
  valid_to       timestamptz not null,
  run_id         text,
  applied_at     timestamptz not null default now());

create table if not exists engine.tool_call (
  id        bigserial primary key,
  ts        timestamptz not null default now(),
  service   text not null,                          -- engine | gate
  tool      text not null,
  caller    text not null,                          -- workflow | agent
  run_id    text,
  ref       text,
  ms        int not null,
  ok        boolean not null,
  summary   text);
create index if not exists tool_call_run on engine.tool_call (run_id);

create table if not exists engine.audit_event (
  id      bigserial primary key,
  ts      timestamptz not null default now(),
  kind    text not null,
  ref     text,
  payload jsonb not null default '{}');

create table if not exists engine.event_outbox (
  id bigserial primary key, aggregate_id text not null, aggregate_offset bigint not null,
  event_type text not null, topic text not null, payload_text text not null,
  delivery_class text not null check (delivery_class in
    ('sam_input','business','ui','telemetry')),
  user_props jsonb not null default '{}', app_message_id text not null,
  created_at timestamptz not null default now(), published_at timestamptz,
  unique (aggregate_id, aggregate_offset));
create index if not exists event_outbox_unpublished
  on engine.event_outbox (id) where published_at is null;

reset role;
