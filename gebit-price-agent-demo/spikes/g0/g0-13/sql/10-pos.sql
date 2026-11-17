-- 10-pos.sql: Schema pos (gpos-pos), Eigentuemer :r_pos.
-- Quelle: D 7.1 (article, article_price, basket, basket_line; ohne
-- MHD-Felder), Anhang A (price_action); till, payment, receipt und
-- event_outbox fehlen in D und Anhang A und sind ergaenzt [A].
-- D 7.1 active_promotion entfaellt: ersetzt durch pos.price_action.
-- Idempotent: "if not exists", Grants wiederholbar.

\if :{?role_prefix}
\else
\set role_prefix gpos
\endif
\set r_pos :role_prefix _pos
\set r_engine :role_prefix _engine
\set r_loyalty :role_prefix _loyalty
\set r_ui :role_prefix _ui

set role :"r_pos";

-- Kassen: Standkasse 01, Hintergrundkassen 02..05 (D 5.2) [A]
create table if not exists pos.till (
  till_id   text primary key,                       -- '01'
  store_id  text not null default '101',
  location  text not null unique,                   -- 'Root.DE.999.101.01'
  kind      text not null check (kind in ('booth','background')),
  active    boolean not null default true);

-- D 7.1 ohne perishable und batch_of (MHD entfaellt, Owner-Vorgabe 9)
create table if not exists pos.article (
  article_number  text primary key,                 -- 'article004'
  article_id      text not null unique,             -- 'IDarticle004'
  gtin            text not null unique,             -- Filial-EAN GS1 20-29
  name            text not null,
  category        text not null,                    -- non_food | food | book
  vat             numeric(4,2) not null,
  regular_price   numeric(8,2) not null check (regular_price > 0),
  cost_net        numeric(8,2) not null check (cost_net >= 0),
  net_qty         numeric(8,3), unit text,          -- Grundpreis (A08)
  excluded_reason text check (excluded_reason in ('price_bound','alcohol','deposit')),
  shelf_slot      text, image text);

create table if not exists pos.article_price (
  article_number text not null references pos.article,      -- FK [A]
  store_id       text not null,
  regular_price  numeric(8,2) not null check (regular_price > 0),
  primary key (article_number, store_id));

-- Anhang A: Overlay pro Besuch, nie in engine.price_history
create table if not exists pos.price_action (
  action_id text primary key, article_number text not null,
  store_id text not null, kind text not null
    check (kind in ('PROMOTION','MARKDOWN')),
  regular_price numeric(8,2) not null, action_price numeric(8,2) not null,
  pct_shown int not null, ref30 numeric(8,2) not null,
  valid_from timestamptz not null, valid_to timestamptz,
  proposal_id text not null unique, visit_id text not null,
  approver_role text not null, approver_ref text not null,
  ended_at timestamptz,
  check (action_price < regular_price));               -- B01 nur Senkung
-- ein Regalpreis je Artikel und Filiale (B08, G01): hoechstens eine
-- laufende Aktion [A]
create unique index if not exists price_action_one_open
  on pos.price_action (article_number, store_id) where ended_at is null;
create index if not exists price_action_visit on pos.price_action (visit_id);

create table if not exists pos.basket (
  tx_id uuid primary key, visit_id text,
  till text references pos.till,                    -- FK [A]
  status text, receipt_number text, opened_at timestamptz,
  closed_at timestamptz, total numeric(10,2), last_offset bigint);
create index if not exists basket_visit on pos.basket (visit_id);

create table if not exists pos.basket_line (
  tx_id uuid references pos.basket on delete cascade,      -- FK [A]
  position_id uuid, article_number text,
  unit_price numeric(8,2), discount numeric(8,2), item_count int,
  voided boolean, price_source text, primary key (tx_id, position_id));

-- [A] v1 nur CreateCashPayment; Coupons rechnet Loyalty ab
create table if not exists pos.payment (
  payment_id uuid primary key,
  tx_id      uuid not null references pos.basket on delete cascade,
  kind       text not null default 'CASH' check (kind in ('CASH','CARD')),
  amount     numeric(10,2) not null,
  tendered   numeric(10,2), change_due numeric(10,2),
  created_at timestamptz not null default now());
create index if not exists payment_tx on pos.payment (tx_id);

-- [A] Bon als jsonb und binaer (Plan 2.5), Receipt-API 2.13.0 in Closed
create table if not exists pos.receipt (
  tx_id          uuid primary key references pos.basket on delete cascade,
  receipt_number text not null unique,
  api_version    text not null,                     -- 'receipt-api-2.13.0'
  receipt_json   jsonb not null,
  receipt_bin    bytea not null,
  fiscal         jsonb,                             -- Fiskal-Simulation
  created_at     timestamptz not null default now());

-- [A] Transaktions-Outbox, gleiche Form wie loyalty.event_outbox
-- (ein common/outbox.py fuer alle Dienste); aggregate_id = txId,
-- Application Message ID = aggregate_id:aggregate_offset (Plan 2.4)
create table if not exists pos.event_outbox (
  id               bigserial primary key,
  aggregate_id     text not null,
  aggregate_offset bigint not null,
  event_type       text not null,                   -- 'PositionAdded'
  topic            text not null,                   -- gebit/rp/purchase/v2/...
  payload          jsonb not null,                  -- proto3-JSON mit @type
  created_at       timestamptz not null default now(),
  published_at     timestamptz,
  unique (aggregate_id, aggregate_offset));
create index if not exists event_outbox_unpublished
  on pos.event_outbox (id) where published_at is null;

-- Engine liest Korb und Preise (Anhang A), schreibt nie
grant usage on schema pos to :"r_engine";
alter default privileges in schema pos grant select on tables to :"r_engine";
grant select on all tables in schema pos to :"r_engine";

reset role;
