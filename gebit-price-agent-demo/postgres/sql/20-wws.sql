-- 20-wws.sql: schema wws (gpos-wws), owner :r_wws. Idempotent. New in UC1.
\if :{?role_prefix}
\else
\set role_prefix gpos
\endif
\set r_wws :role_prefix _wws

set role :"r_wws";

create table if not exists wws.season (
  season_code text primary key,                     -- 'valentinstag'
  label       text not null,                        -- 'Valentinstag'
  start_date  date not null,
  end_date    date not null,
  check (end_date >= start_date));

create table if not exists wws.article (
  article_number text primary key,                  -- '100001'
  article_id     text not null unique,              -- 'ID100001'
  gtin           text not null unique check (gtin ~ '^20[0-9]{11}$'),
  name           text not null,
  category       text not null,                     -- tag, e.g. 'kaffee_tee'
  category_label text not null,
  pack_label     text not null,
  net_quantity   numeric(10,3) not null check (net_quantity > 0),
  base_unit      text not null check (base_unit in ('g','ml','Stück')),
  vat_pct        numeric(4,2) not null check (vat_pct in (7.00, 19.00)),
  cost_net       numeric(8,2) not null check (cost_net > 0),
  price_bound    boolean not null default false,
  season_code    text references wws.season,
  listed_since   date not null,
  sort_order     int not null);

create table if not exists wws.article_price (
  article_number text not null references wws.article,
  store_id       text not null,
  regular_price  numeric(8,2) not null check (regular_price > 0),
  primary key (article_number, store_id));

-- Source of ref30 (PAngV). Never contains booth actions.
create table if not exists wws.price_history (
  article_number text not null references wws.article,
  store_id       text not null,
  valid_from     timestamptz not null,
  valid_to       timestamptz,
  price          numeric(8,2) not null check (price > 0),
  kind           text not null check (kind in ('REGULAR','PROMO')),
  primary key (article_number, store_id, valid_from));

create table if not exists wws.price_action (
  action_id      text primary key,                  -- 'PA-270216-0003', 'PA-SEED-100009'
  article_number text not null references wws.article,
  store_id       text not null,
  kind           text not null check (kind in ('CENTRAL','BOOTH')),
  regular_price  numeric(8,2) not null,
  action_price   numeric(8,2) not null,
  pct_shown      int not null check (pct_shown between 0 and 99),
  ref30          numeric(8,2) not null,
  valid_from     timestamptz not null,
  valid_to       timestamptz not null,
  proposal_id    text unique,                       -- null for CENTRAL
  reason_code    text not null,
  originator     text not null,
  approver       text,
  created_at     timestamptz not null default now(),
  ended_at       timestamptz,
  end_reason     text,
  check (action_price < regular_price),
  check (valid_to > valid_from),
  check (kind = 'CENTRAL' or (proposal_id is not null and approver is not null)));
-- one shelf price per article and store: at most one open action
create unique index if not exists price_action_one_open
  on wws.price_action (article_number, store_id) where ended_at is null;

create sequence if not exists wws.action_seq;

create table if not exists wws.sales_plan (
  article_number text not null references wws.article,
  store_id       text not null,
  plan_week      numeric(8,2) not null check (plan_week >= 0),
  primary key (article_number, store_id));

create table if not exists wws.sales_daily (
  article_number text not null references wws.article,
  store_id       text not null,
  day            date not null,
  units          int not null check (units >= 0),
  primary key (article_number, store_id, day));

create table if not exists wws.stock (
  article_number text not null references wws.article,
  store_id       text not null,
  on_hand        int not null check (on_hand >= 0),
  primary key (article_number, store_id));

create table if not exists wws.inbound_delivery (
  delivery_id    text primary key,
  article_number text not null references wws.article,
  store_id       text not null,
  expected_on    date not null,
  quantity       int not null check (quantity > 0));

create table if not exists wws.event_outbox (
  id bigserial primary key, aggregate_id text not null, aggregate_offset bigint not null,
  event_type text not null, topic text not null, payload_text text not null,
  delivery_class text not null check (delivery_class in
    ('sam_input','business','ui','telemetry')),
  user_props jsonb not null default '{}', app_message_id text not null,
  created_at timestamptz not null default now(), published_at timestamptz,
  unique (aggregate_id, aggregate_offset));
create index if not exists event_outbox_unpublished
  on wws.event_outbox (id) where published_at is null;

create table if not exists wws.audit (
  id      bigserial primary key,
  ts      timestamptz not null default now(),
  actor   text not null,
  action  text not null,
  ref     text,
  payload jsonb not null default '{}');

reset role;
