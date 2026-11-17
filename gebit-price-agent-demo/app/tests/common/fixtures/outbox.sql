-- outbox.sql: tiny schema for the WP-A tests of db/outbox (not part of the demo).
-- Same outbox form as UC1-BUILD-SPEC 5.1, schema ut, owner role :role_prefix _ut.
--   psql -X -v ON_ERROR_STOP=1 -v role_prefix=gpos_ut_<hex> -d <scratch db> -f outbox.sql
\if :{?role_prefix}
\else
\set role_prefix gpos_ut
\endif
\set r_ut :role_prefix _ut

select format('create role %I login', r)
  from (values (:'r_ut')) as v(r)
 where not exists (select 1 from pg_roles where rolname = r)
\gexec

create schema if not exists ut authorization :"r_ut";

set role :"r_ut";

create table if not exists ut.event_outbox (
  id bigserial primary key, aggregate_id text not null, aggregate_offset bigint not null,
  event_type text not null, topic text not null, payload_text text not null,
  delivery_class text not null check (delivery_class in
    ('sam_input','business','ui','telemetry')),
  user_props jsonb not null default '{}', app_message_id text not null,
  created_at timestamptz not null default now(), published_at timestamptz,
  unique (aggregate_id, aggregate_offset));
create index if not exists event_outbox_unpublished
  on ut.event_outbox (id) where published_at is null;

reset role;
