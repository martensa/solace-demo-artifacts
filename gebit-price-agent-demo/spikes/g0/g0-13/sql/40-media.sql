-- 40-media.sql: Schema media (gpos-ui/BFF), Eigentuemer :r_ui.
-- Quelle: Anhang A (photo, visual). Quelle der Wahrheit fuer Fotos und
-- Plakate; Aufbewahrung 1 Messetag (Plan 2.5).
-- Idempotent: "if not exists", Grants wiederholbar.

\if :{?role_prefix}
\else
\set role_prefix gpos
\endif
\set r_pos :role_prefix _pos
\set r_engine :role_prefix _engine
\set r_loyalty :role_prefix _loyalty
\set r_ui :role_prefix _ui

set role :"r_ui";

create table if not exists media.photo (
  photo_id text primary key, scan_id text unique, kind text not null
    check (kind in ('competitor','shelf')),
  mime text not null, sha256 text not null, bytes bytea not null
    check (octet_length(bytes) <= 1048576),
  device text, created_at timestamptz not null default now());
-- Aufbewahrungsjob loescht nach created_at [A]
create index if not exists photo_created on media.photo (created_at);

create table if not exists media.visual (
  visual_id text primary key, article_number text not null,
  campaign text not null, model text, png bytea not null,
  created_at timestamptz not null default now(),
  unique (article_number, campaign));

-- Engine liest Fotos fuer load_photo (Rueckfall A2b, Plan 3.6/E6) [A];
-- wer media.visual schreibt (BFF oder Engine), klaert S3 [A]
grant usage on schema media to :"r_engine";
alter default privileges in schema media grant select on tables to :"r_engine";
grant select on all tables in schema media to :"r_engine";

reset role;
