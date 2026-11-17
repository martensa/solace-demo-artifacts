-- G0-13 Plausibilitaetspruefungen nach DDL und Seed (als Admin).
-- Rechnet die Ausloeser-Zahlen aus spikes/loyalty-tools/calc_output.txt
-- mit den Seed-Daten nach und prueft Leitplanken (CHECK, FK, UNIQUE) und
-- Schemarechte. Schreibtests laufen in Subtransaktionen, die
-- zurueckgerollt werden; die DB bleibt unveraendert.

\if :{?role_prefix}
\else
\set role_prefix gpos
\endif
\set r_pos :role_prefix _pos
\set r_engine :role_prefix _engine
\set r_loyalty :role_prefix _loyalty
\set r_ui :role_prefix _ui
\pset footer off
select set_config('g0.r_pos', :'r_pos', false), set_config('g0.r_engine', :'r_engine', false),
       set_config('g0.r_loyalty', :'r_loyalty', false), set_config('g0.r_ui', :'r_ui', false) \g /dev/null

\echo '== S1 Inventar je Schema'
select n.nspname as schema,
       count(*) filter (where c.relkind = 'r') as tables,
       count(*) filter (where c.relkind = 'v') as views,
       string_agg(distinct pg_get_userbyid(c.relowner), ',') as owners
  from pg_class c join pg_namespace n on n.oid = c.relnamespace
 where n.nspname in ('pos','engine','loyalty','media') and c.relkind in ('r','v')
 group by 1 order by 1;

\echo '== S2 Tabellen ohne Primaerschluessel (erwartet: 0 Zeilen)'
select c.oid::regclass as table_without_pk
  from pg_class c join pg_namespace n on n.oid = c.relnamespace
 where n.nspname in ('pos','engine','loyalty','media') and c.relkind = 'r'
   and not exists (select 1 from pg_constraint k where k.conrelid = c.oid and k.contype = 'p');

\echo '== S3 Seed-Zeilen (nur Tabellen mit Zeilen)'
select t as table, n as rows from (
  select c.oid::regclass::text t,
         (xpath('/row/n/text()', query_to_xml(format('select count(*) as n from %s', c.oid::regclass),
                false, true, '')))[1]::text::int n
    from pg_class c join pg_namespace s on s.oid = c.relnamespace
   where s.nspname in ('pos','engine','loyalty','media') and c.relkind = 'r') x
 where n > 0 order by t;

\echo '== S4 ref30 (A01: Minimum der 30 Tage vor der Senkung) und gezeigte Prozent fuer 6,89'
select s.scenario_id, s.hero_article,
       r.ref30,
       (100 * (round(r.ref30 * 100)::int - 689)) / round(r.ref30 * 100)::int as shown_pct_6_89
  from engine.scenario s
  cross join lateral (
    select min(h.price) as ref30 from engine.price_history h
     where h.scenario_id = s.scenario_id and h.article_number = s.hero_article
       and h.store_id = '101'
       and h.valid_from < (s.store_date + s.store_time_start) at time zone 'Europe/Berlin'
       and coalesce(h.valid_to, 'infinity') >
           ((s.store_date + s.store_time_start) at time zone 'Europe/Berlin') - interval '30 days') r
 where s.scenario_id in ('TR1','T2') order by 1;

\echo '== S5 Stufentabellen TR1, TR2, TR6 aus Seed (Formeln von calc_triggers.py)'
with inp as (
  select s.scenario_id, a.regular_price::float8 as p0, round(a.regular_price * 100)::int as p0c,
         a.vat::float8 as vat, a.cost_net::float8 as c,
         (sa.stock + coalesce((select sum(d.quantity) from engine.inbound_delivery d
                                where d.scenario_id = s.scenario_id
                                  and d.article_number = s.hero_article), 0))::float8 as avail,
         sa.velocity_per_h::float8 as v, sa.elasticity::float8 as eps, sa.horizon_h::float8 as h,
         sa.leftover_weight::float8 as w,
         coalesce(round((s.params->>'target_days')::numeric * sa.plan_today), 0)::float8 as target_end,
         case a.category when 'non_food' then 20 else 12 end as floor_pct,
         round(a.regular_price * 100)::int as refc       -- ref30 = Regelpreis (S4, RL)
    from engine.scenario s
    join engine.scenario_article sa on sa.scenario_id = s.scenario_id
                                   and sa.article_number = s.hero_article
    join pos.article a on a.article_number = s.hero_article
   where s.scenario_id in ('TR1','TR2','TR6')),
steps as (
  select i.*, st.step,
         case when st.step = 0 then i.p0c else
           (select max(eu * 100 + e) from generate_series(0, x.exact / 100) eu,
                   unnest(array[99, 89, 79, 49]) e where eu * 100 + e <= x.exact) end as pc
    from inp i cross join unnest(array[0, 10, 20, 30, 40]) st(step)
    cross join lateral (select floor(i.p0c * (100 - st.step) / 100.0)::int as exact) x),
calc as (
  select scenario_id, step, pc, p0c, refc, floor_pct,
         least(avail, v * power((pc / 100.0) / p0, eps) * h) as q, avail, target_end, c, w,
         (pc / 100.0) / (1 + vat / 100) as pnet
    from steps),
res as (
  select scenario_id, step, pc / 100.0 as price,
         case when pc < refc then (100 * (refc - pc)) / refc else 0 end as shown,
         q, greatest(0, avail - q - target_end) as left_,
         (pnet - c) * q - w * c * greatest(0, avail - q - target_end) as gp,
         (pnet - c) / pnet * 100 as margin, pc, p0c, floor_pct
    from calc),
fin as (
  select r.*, concat_ws(',',
           case when pc < p0c and margin < floor_pct then 'margin<' || floor_pct end,
           case when shown > 30 then 'disc>30' end) as blocked,
         gp - first_value(gp) over (partition by scenario_id order by step) as dgp
    from res r)
select scenario_id as tr, case step when 0 then 'none' else step::text end as step,
       to_char(price, 'FM90.00') as price,
       case when shown > 0 then '-' || shown || '%' else '' end as shown,
       round(q::numeric, 1) as units, round(left_::numeric, 1) as left,
       round(gp::numeric, 1) as gp, to_char(dgp, 'FMSG990.0') as dgp,
       round(margin::numeric, 1) || '%' as margin, blocked
  from fin f order by f.scenario_id, f.step;

\echo '== S6 Slot A je Ausloeser (bester DB-Gewinn ohne Sperre)'
with inp as (
  select s.scenario_id, a.regular_price::float8 as p0, round(a.regular_price * 100)::int as p0c,
         a.vat::float8 as vat, a.cost_net::float8 as c,
         (sa.stock + coalesce((select sum(d.quantity) from engine.inbound_delivery d
                                where d.scenario_id = s.scenario_id
                                  and d.article_number = s.hero_article), 0))::float8 as avail,
         sa.velocity_per_h::float8 as v, sa.elasticity::float8 as eps, sa.horizon_h::float8 as h,
         sa.leftover_weight::float8 as w,
         coalesce(round((s.params->>'target_days')::numeric * sa.plan_today), 0)::float8 as target_end,
         case a.category when 'non_food' then 20 else 12 end as floor_pct,
         round(a.regular_price * 100)::int as refc, a.net_qty
    from engine.scenario s
    join engine.scenario_article sa on sa.scenario_id = s.scenario_id
                                   and sa.article_number = s.hero_article
    join pos.article a on a.article_number = s.hero_article
   where s.scenario_id in ('TR1','TR2','TR6')),
steps as (
  select i.*, st.step,
         case when st.step = 0 then i.p0c else
           (select max(eu * 100 + e) from generate_series(0, x.exact / 100) eu,
                   unnest(array[99, 89, 79, 49]) e where eu * 100 + e <= x.exact) end as pc
    from inp i cross join unnest(array[0, 10, 20, 30, 40]) st(step)
    cross join lateral (select floor(i.p0c * (100 - st.step) / 100.0)::int as exact) x),
res as (
  select scenario_id, step, pc, p0c, refc, floor_pct, net_qty,
         case when pc < refc then (100 * (refc - pc)) / refc else 0 end as shown,
         ((pc / 100.0) / (1 + vat / 100) - c) * least(avail, v * power((pc / 100.0) / p0, eps) * h)
           - w * c * greatest(0, avail - least(avail, v * power((pc / 100.0) / p0, eps) * h) - target_end) as gp,
         ((pc / 100.0) / (1 + vat / 100) - c) / ((pc / 100.0) / (1 + vat / 100)) * 100 as margin
    from steps),
ok as (
  select r.*, gp - max(gp) filter (where step = 0) over (partition by scenario_id) as dgp
    from res r)
select distinct on (scenario_id) scenario_id as tr, to_char(pc / 100.0, 'FM90.00') as slot_a,
       '-' || shown || ' %' as shown, to_char(dgp, 'FMSG990.0') as dgp,
       case when net_qty is not null then to_char(pc / 100.0 / net_qty, 'FM990.00') || ' EUR/kg' end as grundpreis,
       case when net_qty is not null then to_char(p0c / 100.0 / net_qty, 'FM990.00') || ' EUR/kg' end as grundpreis_regulaer
  from ok
 where step > 0 and not (pc < p0c and margin < floor_pct) and shown <= 30
 order by scenario_id, gp desc;

\echo '== S7 TR3 Espresso gegen Wettbewerb 6,99 (eps_rel aus beobachteter Rate)'
with i as (
  select a.regular_price::float8 as p0, a.vat::float8 as vat, a.cost_net::float8 as c,
         sa.stock::float8 as stock, sa.horizon_h::float8 as h, sa.velocity_per_h::float8 as vobs,
         (s.params->>'competitor_price')::float8 as comp, (s.params->>'plan_velocity_per_h')::float8 as vplan
    from engine.scenario s
    join engine.scenario_article sa on sa.scenario_id = s.scenario_id and sa.article_number = s.hero_article
    join pos.article a on a.article_number = s.hero_article where s.scenario_id = 'TR3'),
e as (select i.*, ln(vobs / vplan) / ln(p0 / comp) as eps_rel from i),
r as (
  select e.*, p, case when p > comp then vplan * power(p / comp, eps_rel) else vplan end as v,
         p / (1 + vat / 100) as pnet
    from e cross join unnest(array[7.99, 7.49, 6.99]::float8[]) p)
select round(eps_rel::numeric, 2) as eps_rel, to_char(p, 'FM0.00') as price,
       round(v::numeric, 2) as v_h, round(least(stock, v * h)::numeric, 1) as units,
       round(((pnet - c) * least(stock, v * h))::numeric, 1) as gp,
       round(((pnet - c) / pnet * 100)::numeric, 1) || '%' as margin,
       round(((p - comp) / comp * 100)::numeric, 1) || '%' as gap
  from r order by p desc;

\echo '== S8 TR4/TR5 Coupons und Kopplungsangebot (loyalty.offer x pos.article)'
select o.offer_id, o.target_article, to_char(a.regular_price, 'FM90.00') as regular,
       to_char(floor(round(a.regular_price * 100) * (100 - o.discount_value) / 100) / 100, 'FM90.00') as coupon_price,
       round(((floor(round(a.regular_price * 100) * (100 - o.discount_value) / 100) / 100 / (1 + a.vat / 100)
               - a.cost_net) / (floor(round(a.regular_price * 100) * (100 - o.discount_value) / 100) / 100
               / (1 + a.vat / 100)) * 100), 1) || '%' as margin,
       case when a.net_qty is not null then to_char(floor(round(a.regular_price * 100)
               * (100 - o.discount_value) / 100) / 100 / a.net_qty, 'FM990.00') || ' EUR/kg' end as grundpreis
  from loyalty.offer o join pos.article a on a.article_number = o.target_article
 where o.offer_id in ('OFF-GUAC-30','OFF-CANTUCCINI-30','OFF-KAFFEEPADS-30') order by 1;

\echo '== S9 Punkte (1 Punkt je volle 2 EUR, loyalty.program)'
select to_char(t, 'FM90.00') as total_eur, floor(t / p.earn_eur_per_point)::int as points
  from loyalty.program p cross join unnest(array[8.67, 14.88, 12.16]) t
 where p.program_id = 'POINTS-ID';

\echo '== S10 POS-Artikel ohne loyalty.article_ref (purchase_line hat FK darauf)'
select a.article_number, a.name from pos.article a
 where not exists (select 1 from loyalty.article_ref r where r.article_number = a.article_number)
 order by 1;

\echo '== S11 View loyalty.member_category_8w laeuft (ohne Kaeufe 0 Zeilen)'
select count(*) as rows from loyalty.member_category_8w;

\echo '== S12 Leitplanken und Rechte (Schreibtests werden zurueckgerollt)'
do $$
declare
  r_pos text := current_setting('g0.r_pos');
  r_engine text := current_setting('g0.r_engine');
  r_ui text := current_setting('g0.r_ui');
  n int;
begin
  -- B01: Aktion nur als Senkung
  begin
    insert into pos.price_action values ('PA-T1','article004','101','PROMOTION',8.67,9.10,0,8.67,
      now(),null,'prp-t1','v-t','marktleitung','r');
    raise exception 'FAIL B01 not enforced';
  exception when check_violation then raise notice 'PASS B01 action_price >= regular_price -> check_violation';
  end;
  -- B08/G01: zweite offene Aktion je Artikel und Filiale
  begin
    insert into pos.price_action values ('PA-T2','article019','101','PROMOTION',1.29,0.99,23,1.29,
      now(),null,'prp-t2','v-t','marktleitung','r');
    raise exception 'FAIL G01 second open action accepted';
  exception when unique_violation then raise notice 'PASS G01 second open action on article019 -> unique_violation';
  end;
  -- C02: Katalog-Coupon ohne Freigabe hoechstens 30 %
  begin
    insert into loyalty.offer (offer_id, kind, target_article, discount_type, discount_value,
      max_discount_eur, valid_days, promotion_id, text_key)
    values ('OFF-T40','PERSONAL_COUPON','article008','RELATIVE',40,1.00,7,'p','t');
    raise exception 'FAIL C02 not enforced';
  exception when check_violation then raise notice 'PASS C02 auto coupon 40 %% -> check_violation';
  end;
  -- C04: Tags nur aus der Allowlist
  begin
    insert into loyalty.member_tag values ('M-0001','religion','EXPLICIT',1.0);
    raise exception 'FAIL C04 not enforced';
  exception when foreign_key_violation then raise notice 'PASS C04 tag outside vocabulary -> foreign_key_violation';
  end;
  -- Frequenz: hoechstens ein offener Coupon je Mitglied und Angebot
  begin
    insert into loyalty.coupon (coupon_id, coupon_code, offer_id, member_id, discount_type,
      discount_value, max_discount_eur, valid_from, valid_to, issued_channel)
    values ('CPN-T1','T-CODE-1','OFF-CANTUCCINI-30','M-0001','RELATIVE',30,1.00,now(),now() + interval '7 days','RULE'),
           ('CPN-T2','T-CODE-2','OFF-CANTUCCINI-30','M-0001','RELATIVE',30,1.00,now(),now() + interval '7 days','RULE');
    raise exception 'FAIL frequency rule not enforced';
  exception when unique_violation then raise notice 'PASS frequency rule second open coupon -> unique_violation';
  end;
  -- media: Foto > 1 MiB
  begin
    insert into media.photo (photo_id, kind, mime, sha256, bytes)
    values ('ph-t1','competitor','image/jpeg','x', decode(repeat('00', 1048577), 'hex'));
    raise exception 'FAIL photo size not enforced';
  exception when check_violation then raise notice 'PASS photo > 1 MiB -> check_violation';
  end;
  -- Rechte: engine liest pos und media
  begin
    execute format('set local role %I', r_engine);
    select count(*) into n from pos.article;
    perform count(*) from media.photo;
    raise notice 'PASS % reads pos.article (% rows) and media.photo', r_engine, n;
    raise exception using errcode = 'P0002', message = 'rollback';
  exception when no_data_found then null;
  end;
  -- engine schreibt nie in pos
  begin
    execute format('set local role %I', r_engine);
    update pos.article set regular_price = 0.01 where article_number = 'article004';
    raise exception 'FAIL engine wrote pos.article';
  exception when insufficient_privilege then raise notice 'PASS % update pos.article -> insufficient_privilege', r_engine;
  end;
  -- engine hat kein SQL auf loyalty (gRPC)
  begin
    execute format('set local role %I', r_engine);
    perform count(*) from loyalty.member;
    raise exception 'FAIL engine read loyalty.member';
  exception when insufficient_privilege then raise notice 'PASS % select loyalty.member -> insufficient_privilege', r_engine;
  end;
  -- pos schreibt nicht in engine
  begin
    execute format('set local role %I', r_pos);
    insert into engine.trigger (trigger_id, kind, article_number, facts, status)
    values ('t-x','slow_seller','article004','{}','new');
    raise exception 'FAIL pos wrote engine.trigger';
  exception when insufficient_privilege then raise notice 'PASS % insert engine.trigger -> insufficient_privilege', r_pos;
  end;
  -- ui schreibt media.photo, liest pos nicht
  begin
    execute format('set local role %I', r_ui);
    insert into media.photo (photo_id, kind, mime, sha256, bytes, device)
    values ('ph-t2','competitor','image/jpeg', encode(sha256('\xffd8'::bytea), 'hex'), '\xffd8', 'tablet-01');
    raise notice 'PASS % insert media.photo', r_ui;
    perform count(*) from pos.article;
    raise exception 'FAIL ui read pos.article';
  exception when insufficient_privilege then raise notice 'PASS % select pos.article -> insufficient_privilege (photo rolled back)', r_ui;
  end;
end $$;

\echo '== S13 Nach den Tests unveraendert (erwartet: 0 Testzeilen)'
select (select count(*) from pos.price_action where action_id like 'PA-T%') as pa,
       (select count(*) from loyalty.coupon) as coupons,
       (select count(*) from media.photo) as photos,
       (select regular_price from pos.article where article_number = 'article004') as ente;
