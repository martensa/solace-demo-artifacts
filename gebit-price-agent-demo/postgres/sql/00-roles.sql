-- 00-roles.sql: roles and schemas of DB gpos (UC1). Run as DB admin in DB gpos.
--   psql -X -v ON_ERROR_STOP=1 [-v role_prefix=gpos] -d gpos -f 00-roles.sql
-- Idempotent. Passwords are set by scripts/install.sh (stdin), never here.
\if :{?role_prefix}
\else
\set role_prefix gpos
\endif
\set r_pos :role_prefix _pos
\set r_wws :role_prefix _wws
\set r_loyalty :role_prefix _loyalty
\set r_engine :role_prefix _engine

select format('create role %I login', r)
  from unnest(array[:'r_pos', :'r_wws', :'r_loyalty', :'r_engine']) as r
 where not exists (select 1 from pg_roles where rolname = r)
\gexec

-- non-superuser admin (AKS later): SET and INHERIT on the service roles
select format('grant %I to %I with inherit true, set true', r, current_user)
  from unnest(array[:'r_pos', :'r_wws', :'r_loyalty', :'r_engine']) as r
 where not (select rolsuper from pg_roles where rolname = current_user)
\gexec

create schema if not exists pos     authorization :"r_pos";
create schema if not exists wws     authorization :"r_wws";
create schema if not exists loyalty authorization :"r_loyalty";
create schema if not exists engine  authorization :"r_engine";

select format('alter role %I in database %I set search_path = %I', r, current_database(), s)
  from (values (:'r_pos', 'pos'), (:'r_wws', 'wws'),
               (:'r_loyalty', 'loyalty'), (:'r_engine', 'engine')) as v(r, s)
\gexec
