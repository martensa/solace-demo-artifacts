-- 10-pos.sql: schema pos (gpos-pos), owner :r_pos. Idempotent.
\if :{?role_prefix}
\else
\set role_prefix gpos
\endif
\set r_pos :role_prefix _pos
\set r_engine :role_prefix _engine

set role :"r_pos";

create table if not exists pos.till (
  till_id   text primary key,                       -- '01' booth, '98' probe, '99' test
  store_id  text not null,                          -- '101' booth, '199' probe/test
  location  text not null unique,                   -- 'Root.DE.999.101.01'
  kind      text not null check (kind in ('booth','probe','test')),
  active    boolean not null default true);

create sequence if not exists pos.receipt_seq;

create table if not exists pos.basket (
  tx_id                  uuid primary key,
  till_id                text not null references pos.till,
  store_id               text not null,
  location               text not null,
  status                 text not null check (status in
                           ('CREATED','OPEN','IN_PAYMENT','CLOSED','CANCELLED','RESET')),
  receipt_number         text,
  membership_id          text,                      -- from ResolveMembership
  membership_position_id uuid,
  employee_id            text, cashdrawer_id text,
  created_at             timestamptz not null default now(),
  opened_at              timestamptz, closed_at timestamptz,
  total                  numeric(10,2) not null default 0,
  paid                   numeric(10,2) not null default 0,
  last_offset            bigint not null default 0);
create index if not exists basket_till_status on pos.basket (till_id, status);

create table if not exists pos.basket_line (
  tx_id         uuid not null references pos.basket on delete cascade,
  position_id   uuid not null,
  line_no       int not null,
  article_number text not null,
  article_id    text not null,
  name          text not null,
  gtin          text,
  category      text not null,                      -- tag from WWS
  item_count    int not null check (item_count > 0),
  unit_price    numeric(8,2) not null,              -- effective price at scan
  regular_price numeric(8,2) not null,
  price_source  text not null check (price_source in
                  ('REGULAR','CENTRAL_ACTION','BOOTH_ACTION')),
  action_id     text,
  vat_pct       numeric(4,2) not null,
  voided        boolean not null default false,
  created_at    timestamptz not null default now(),
  primary key (tx_id, position_id));

create table if not exists pos.payment (
  payment_id  uuid primary key,
  tx_id       uuid not null references pos.basket on delete cascade,
  kind        text not null check (kind in ('CASH','CHANGE')),
  amount      numeric(10,2) not null,
  created_at  timestamptz not null default now());

create table if not exists pos.receipt (
  tx_id          uuid primary key references pos.basket on delete cascade,
  receipt_number text not null,
  api_version    text not null,                     -- 'receipt-api-2.13.0' or 'none'
  receipt_b64    text not null default '',
  created_at     timestamptz not null default now());

create table if not exists pos.event_outbox (
  id bigserial primary key, aggregate_id text not null, aggregate_offset bigint not null,
  event_type text not null, topic text not null, payload_text text not null,
  delivery_class text not null check (delivery_class in
    ('sam_input','business','ui','telemetry')),
  user_props jsonb not null default '{}', app_message_id text not null,
  created_at timestamptz not null default now(), published_at timestamptz,
  unique (aggregate_id, aggregate_offset));
create index if not exists event_outbox_unpublished
  on pos.event_outbox (id) where published_at is null;

grant usage on schema pos to :"r_engine";
grant select on pos.till, pos.basket, pos.basket_line to :"r_engine";

reset role;
