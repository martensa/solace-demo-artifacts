-- 00-roles.sql: Rollen und Schemas der DB gpos (Plan 2.5, E7, Anhang A).
-- G0-13-Kandidat fuer postgres/sql/ (AP03).
--
-- Aufruf als DB-Admin in der DB gpos (Lab: postgres; AKS: Admin von
-- PG Flexible), vor 10..40:
--   psql -X -v ON_ERROR_STOP=1 [-v role_prefix=gpos] -d gpos -f 00-roles.sql
-- role_prefix (Default gpos) ergibt gpos_pos, gpos_engine, gpos_loyalty,
-- gpos_ui; G0-13 lief mit gpos_g0 im geteilten Lab-Cluster.
--
-- Idempotent: Rollen per \gexec-Waechter, Schemas "if not exists",
-- Rollen-Settings wiederholbar.
--
-- Abweichung von Anhang A [A]: die Grants auf pos (und media) stehen
-- in 10-pos.sql bzw. 40-media.sql nach den Tabellen, als Default-Privileg
-- des Eigentuemers plus "grant ... on all tables". In 00-roles liefen
-- sie vor jeder Tabelle ins Leere.
-- Passwoerter setzt install.sh (nie im Repo) [A].

\if :{?role_prefix}
\else
\set role_prefix gpos
\endif
\set r_pos :role_prefix _pos
\set r_engine :role_prefix _engine
\set r_loyalty :role_prefix _loyalty
\set r_ui :role_prefix _ui

-- Rollen (cluster-weit), nur wenn sie fehlen
select format('create role %I login', r)
  from unnest(array[:'r_pos', :'r_engine', :'r_loyalty', :'r_ui']) as r
 where not exists (select 1 from pg_roles where rolname = r)
\gexec

-- Ein Admin ohne Superuser (PG Flexible) braucht SET auf den Dienstrollen,
-- damit 10..40 per "set role" als Eigentuemer anlegen, und INHERIT, damit
-- Seed-Pruefung und Betrieb (Reset, Diagnose) lesen koennen; PG 16+ gibt
-- dem Ersteller nur ADMIN. Superuser (Lab) ueberspringen das.
-- [V: G0-13 run-nonsuper auf PG 18.3; PG Flexible selbst offen]
select format('grant %I to %I with inherit true, set true', r, current_user)
  from unnest(array[:'r_pos', :'r_engine', :'r_loyalty', :'r_ui']) as r
 where not (select rolsuper from pg_roles where rolname = current_user)
\gexec

-- Ein Schema je Dienst; kein Dienst schreibt in ein fremdes Schema
create schema if not exists pos     authorization :"r_pos";
create schema if not exists engine  authorization :"r_engine";
create schema if not exists loyalty authorization :"r_loyalty";
create schema if not exists media   authorization :"r_ui";

-- search_path je Dienst, nur in dieser DB [A]
select format('alter role %I in database %I set search_path = %I', r, current_database(), s)
  from (values (:'r_pos', 'pos'), (:'r_engine', 'engine'),
               (:'r_loyalty', 'loyalty'), (:'r_ui', 'media')) as v(r, s)
\gexec
