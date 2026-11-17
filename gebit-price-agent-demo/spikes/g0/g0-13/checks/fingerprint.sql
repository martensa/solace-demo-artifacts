-- G0-13: Katalog- und Daten-Fingerabdruck der Schemas pos, engine, loyalty,
-- media. Gleicher Wert vor und nach einem Lauf = der Lauf hat nichts
-- veraendert (Idempotenz). Ausgabe: eine Zeile "ddl=<md5> data=<md5> ...".
\pset tuples_only on
\pset format unaligned
with nsp as (
  select oid, nspname from pg_namespace
   where nspname in ('pos','engine','loyalty','media')),
cat as (
  select format('nsp %s %s %s', n.nspname, pg_get_userbyid(p.nspowner), p.nspacl) x
    from nsp n join pg_namespace p on p.oid = n.oid
  union all
  select format('rel %s %s %s %s', c.oid::regclass, c.relkind,
                pg_get_userbyid(c.relowner), coalesce(c.relacl::text, ''))
    from pg_class c join nsp n on n.oid = c.relnamespace
  union all
  select format('col %s.%s %s %s %s %s', a.attrelid::regclass, a.attname,
                format_type(a.atttypid, a.atttypmod), a.attnotnull,
                coalesce(pg_get_expr(d.adbin, d.adrelid), ''), a.attnum)
    from pg_attribute a
    join pg_class c on c.oid = a.attrelid join nsp n on n.oid = c.relnamespace
    left join pg_attrdef d on d.adrelid = a.attrelid and d.adnum = a.attnum
   where a.attnum > 0 and not a.attisdropped
  union all
  select format('con %s %s %s', conrelid::regclass, conname, pg_get_constraintdef(c.oid))
    from pg_constraint c join nsp n on n.oid = c.connamespace
  union all
  select format('idx %s', pg_get_indexdef(i.indexrelid))
    from pg_index i join pg_class c on c.oid = i.indexrelid
    join nsp n on n.oid = c.relnamespace
  union all
  select format('view %s %s', c.oid::regclass, pg_get_viewdef(c.oid))
    from pg_class c join nsp n on n.oid = c.relnamespace where c.relkind = 'v'
  union all
  select format('defacl %s %s %s %s', pg_get_userbyid(defaclrole),
                defaclnamespace::regnamespace, defaclobjtype, defaclacl)
    from pg_default_acl
  union all
  select format('roleset %s %s', r.rolname, s.setconfig)
    from pg_db_role_setting s join pg_roles r on r.oid = s.setrole
   where s.setdatabase = (select oid from pg_database where datname = current_database())),
tabs as (
  select c.oid::regclass::text t from pg_class c join nsp n on n.oid = c.relnamespace
   where c.relkind = 'r'),
dat as (
  select t, (xpath('/row/h/text()', query_to_xml(format(
           'select count(*) || '':'' || md5(coalesce(string_agg(x::text, ''|'' order by x::text), '''')) as h from %s x', t),
           false, true, '')))[1]::text h
    from tabs)
select format('ddl=%s data=%s objects=%s tables=%s rows=%s',
  (select md5(string_agg(x, E'\n' order by x)) from cat),
  (select md5(string_agg(t || '=' || h, E'\n' order by t)) from dat),
  (select count(*) from cat),
  (select count(*) from tabs),
  (select sum(split_part(h, ':', 1)::int) from dat));
