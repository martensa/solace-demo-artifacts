-- 95-checks.sql: mandatory checks after DDL and seed (spec 5.7), including the golden
-- values of 6.8 recomputed in SQL from the seeded rows (signals 6.6, prices 6.7).
-- Run as DB admin in DB gpos after 90..92:
--   psql -X -v ON_ERROR_STOP=1 [-v role_prefix=gpos] [-v demo_date=2027-02-16]
--        [-v verbose=1] -d gpos -f 95-checks.sql
-- Read-only: everything lives in temporary objects of this session. Any deviation
-- ends in raise exception listing every failed check; verbose=1 prints all checks.
-- Business time for ref30 and open actions: demo date 12:00 Europe/Berlin.
\encoding UTF8
\if :{?role_prefix}
\else
\set role_prefix gpos
\endif
\if :{?demo_date}
\else
\set demo_date 2027-02-16
\endif
\set r_pos :role_prefix _pos
\set r_wws :role_prefix _wws
\set r_loyalty :role_prefix _loyalty
\set r_engine :role_prefix _engine
\pset footer off

create temp table gpos_check (
  id       serial primary key,
  name     text not null,
  expected text not null,
  actual   text);

-- ------------------------------------------------------------------ helper objects

create temp view chk_d as
select :'demo_date'::date as d,
       (:'demo_date'::date + time '12:00') at time zone 'Europe/Berlin' as t;

-- 6.7 steps 1+2: target truncated to cents, then the largest price point <= target
create function pg_temp.chk_point(regular numeric, step int) returns numeric
language sql immutable as $$
  select round(max(eu * 100 + e) / 100.0, 2)
    from (select floor(regular * (100 - step))::int as target) x,
         generate_series(0, x.target / 100) as eu, unnest(array[99, 89, 79, 49]) as e
   where eu * 100 + e <= x.target
$$;

-- 6.7 step 3: net margin in percent (unrounded)
create function pg_temp.chk_margin(price numeric, vat numeric, cost numeric)
returns numeric language sql immutable as $$
  select (price / (1 + vat / 100) - cost) / (price / (1 + vat / 100)) * 100
$$;

-- weekly units from wws.sales_daily: week k = [D-56+7(k-1), D-50+7(k-1)]
create temp view chk_week as
select ap.article_number, ap.store_id, w.k, coalesce(sum(s.units), 0)::int as units
  from wws.article_price ap
  cross join chk_d
  cross join generate_series(1, 8) as w(k)
  left join wws.sales_daily s
    on s.article_number = ap.article_number and s.store_id = ap.store_id
   and s.day between chk_d.d - 56 + 7 * (w.k - 1) and chk_d.d - 50 + 7 * (w.k - 1)
 group by ap.article_number, ap.store_id, w.k;

create temp view chk_perf as
select w.article_number, w.store_id,
       string_agg(w.units::text, ',' order by w.k) as weekly,
       sum(w.units) filter (where w.k = 8) as sold_7d,
       sp.plan_week as plan_7d,
       sum(w.units) filter (where w.k = 8) / sp.plan_week as sell_through,
       avg(w.units) filter (where w.k >= 5) as avg_week_28d,
       st.on_hand as stock,
       st.on_hand / nullif(avg(w.units) filter (where w.k >= 5), 0) as weeks_of_supply,
       avg(w.units) filter (where w.k >= 7) as avg_recent,
       avg(w.units) filter (where w.k in (5, 6)) as avg_prior,
       sum(w.units) filter (where w.k >= 7) / 14.0 as avg_day_14d,
       chk_d.d - a.listed_since as listed_days
  from chk_week w
  join wws.article a on a.article_number = w.article_number
  join wws.sales_plan sp on sp.article_number = w.article_number and sp.store_id = w.store_id
  join wws.stock st on st.article_number = w.article_number and st.store_id = w.store_id
  cross join chk_d
 group by w.article_number, w.store_id, sp.plan_week, st.on_hand, a.listed_since, chk_d.d;

create temp view chk_action as
select pa.*
  from wws.price_action pa cross join chk_d
 where pa.ended_at is null and pa.valid_from <= chk_d.t and chk_d.t < pa.valid_to;

-- ref30: lowest price of all history rows overlapping [t - 30 days, t]
create temp view chk_ref30 as
select h.article_number, h.store_id, min(h.price) as ref30
  from wws.price_history h cross join chk_d
 where h.valid_from <= chk_d.t
   and coalesce(h.valid_to, 'infinity') > chk_d.t - interval '30 days'
 group by h.article_number, h.store_id;

create temp view chk_signal as
select p.*, s.season_code, s.end_date as season_end_date,
       s.end_date - chk_d.d as days_to_end,
       case when s.season_code is null then 'none'
            when chk_d.d < s.start_date then 'before'
            when chk_d.d > s.end_date then 'ended' else 'running' end as season_status,
       case when p.avg_recent >= 1.15 * p.avg_prior then 'rising'
            when p.avg_recent <= 0.85 * p.avg_prior then 'falling'
            else 'stable' end as trend,
       (p.sell_through < 0.5 and p.weeks_of_supply > 6.0 and p.listed_days >= 28)
         as slow_seller,
       coalesce(s.start_date <= chk_d.d and (
         (s.end_date - chk_d.d between 0 and 14
          and (p.stock - p.avg_day_14d * (s.end_date - chk_d.d)) / nullif(p.stock, 0) >= 0.4)
         or (s.end_date < chk_d.d and p.stock > 0)), false) as season_end,
       p.stock - p.avg_day_14d * greatest(s.end_date - chk_d.d, 0) as leftover,
       a.price_bound, ap.regular_price, a.vat_pct, a.cost_net, a.base_unit, a.net_quantity,
       r.ref30, act.action_id, act.action_price, act.valid_to as action_valid_to,
       coalesce(act.action_price, ap.regular_price) as effective_price
  from chk_perf p
  join wws.article a on a.article_number = p.article_number
  join wws.article_price ap on ap.article_number = p.article_number
                           and ap.store_id = p.store_id
  cross join chk_d
  left join wws.season s on s.season_code = a.season_code
  left join chk_ref30 r on r.article_number = p.article_number and r.store_id = p.store_id
  left join chk_action act on act.article_number = p.article_number
                          and act.store_id = p.store_id;

create temp view chk_s101 as
select g.*,
       coalesce(nullif(concat_ws('+', case when g.season_end then 'season_end' end,
                                      case when g.slow_seller then 'slow_seller' end), ''),
                'none') as signals,
       case when g.season_end then
              case when g.days_to_end < 0 then 30 when g.days_to_end <= 7 then 20 else 10 end
            when g.slow_seller then case when g.sell_through < 0.3 then 20 else 10 end
       end as suggested_step,
       (select coalesce(max(st.step) filter (where pg_temp.chk_margin(
                pg_temp.chk_point(g.regular_price, st.step), g.vat_pct, g.cost_net) >= 20), 0)
          from unnest(array[10, 20, 30]) as st(step)) as max_step
  from chk_signal g
 where g.store_id = '101';

-- one line per step: "<regular> -> <point>, -<pct_shown> %, margin <m>" (+ ", blocked")
create function pg_temp.chk_step(article text, step int) returns text
language sql stable as $$
  select format('%s -> %s, -%s %%, margin %s%s', s.regular_price, x.p,
                floor((s.ref30 - x.p) / s.ref30 * 100), round(x.m, 1),
                case when x.m < 20 then ', blocked' else '' end)
    from chk_s101 s,
         lateral (select pg_temp.chk_point(s.regular_price, step) as p) y,
         lateral (select y.p as p, pg_temp.chk_margin(y.p, s.vat_pct, s.cost_net) as m) x
   where s.article_number = article
$$;

-- 6.7 step 6: base price per kg or l
create function pg_temp.chk_base_price(article text, step int) returns text
language sql stable as $$
  select format('%s EUR/%s', round(pg_temp.chk_point(s.regular_price, step) * 1000
                                   / s.net_quantity, 2),
                case s.base_unit when 'g' then 'kg' else 'l' end)
    from chk_s101 s
   where s.article_number = article and s.base_unit in ('g', 'ml')
$$;

-- member purchase days per article (lines exist only with profiling consent)
create temp view chk_member_buy as
select distinct p.member_id, l.article_number,
       (p.closed_at at time zone 'Europe/Berlin')::date as day
  from loyalty.purchase p
  join loyalty.purchase_line l on l.purchase_transaction_id = p.purchase_transaction_id
 where p.transaction_type = 'SALE';

create temp view chk_gap as
select b.member_id, b.article_number,
       b.day - lag(b.day) over (partition by b.member_id, b.article_number order by b.day)
         as gap
  from chk_member_buy b cross join chk_d
 where b.day between chk_d.d - 84 and chk_d.d - 1;

create temp view chk_cardholder as
select w.article_number,
       string_agg(w.member_purchases::text, ',' order by w.week_start) as weekly,
       avg(w.member_purchases) filter (where w.week_start < chk_d.d - 28) as prior,
       avg(w.member_purchases) filter (where w.week_start >= chk_d.d - 28) as recent
  from loyalty.article_week_stats w cross join chk_d
 group by w.article_number, chk_d.d;

create temp view chk_behaviour as
select b.member_id, b.article_number, c.profiling,
       count(*) filter (where b.day between chk_d.d - 56 and chk_d.d - 1) as buys_8w,
       count(*) filter (where b.day between chk_d.d - 84 and chk_d.d - 1) as buys_12w,
       chk_d.d - max(b.day) filter (where b.day < chk_d.d) as days_since_last,
       (select percentile_cont(0.5) within group (order by g.gap)
          from chk_gap g
         where g.member_id = b.member_id and g.article_number = b.article_number
           and g.gap is not null) as median_interval,
       ch.prior, ch.recent, (ch.prior - ch.recent) / nullif(ch.prior, 0) * 100 as drop_pct
  from chk_member_buy b
  join loyalty.consent c on c.member_id = b.member_id
  join chk_cardholder ch on ch.article_number = b.article_number
  cross join chk_d
 group by b.member_id, b.article_number, c.profiling, ch.prior, ch.recent, chk_d.d;

create temp view chk_customer_behaviour as
select v.*, v.days_since_last / nullif(v.median_interval, 0) as overdue_factor,
       (v.profiling and v.buys_8w >= 2
        and v.days_since_last / nullif(v.median_interval, 0) >= 1.5
        and v.drop_pct >= 30 and v.prior >= 5) as fires
  from chk_behaviour v;

-- last regular price change (6.7 step 8)
create temp view chk_last_change as
select distinct on (x.article_number, x.store_id)
       x.article_number, x.store_id,
       (x.valid_from at time zone 'Europe/Berlin')::date as changed_on,
       x.prev_price as old_price, x.price as new_price
  from (select h.*, lag(h.price) over (partition by h.article_number, h.store_id
                                        order by h.valid_from) as prev_price
          from wws.price_history h where h.kind = 'REGULAR') x
 where x.prev_price is not null and x.prev_price <> x.price
 order by x.article_number, x.store_id, x.valid_from desc;

-- ------------------------------------------------------------------- structure

insert into gpos_check (name, expected, actual) values
('wws.article: articles', '30', (select count(*)::text from wws.article)),
('wws.article: gtin = 2099100 + last 5 digits + check digit', '0',
 (select count(*)::text from wws.article
   where gtin <> '2099100' || right(article_number, 5) || (
     (10 - (select sum(substr(gtin, i, 1)::int * case when i % 2 = 0 then 3 else 1 end)
              from generate_series(1, 12) as i) % 10) % 10)::text)),
('wws.season: seasons', 'ostern,valentinstag,winter',
 (select string_agg(season_code, ',' order by season_code) from wws.season)),
('wws.article_price: prices per store', '101:30,199:30',
 (select string_agg(store_id || ':' || n, ',' order by store_id)
    from (select store_id, count(*) as n from wws.article_price group by store_id) x)),
('wws.sales_plan: rows', '60', (select count(*)::text from wws.sales_plan)),
('wws.stock: rows', '60', (select count(*)::text from wws.stock)),
('wws.sales_daily: rows', '2880', (select count(*)::text from wws.sales_daily)),
('wws.sales_daily: article/store pairs with 8 x 6 rows in [D-56, D-1]', '60',
 (select count(*)::text from (
    select 1 from wws.sales_daily s cross join chk_d
     group by s.article_number, s.store_id, chk_d.d
    having count(*) = 48 and min(s.day) >= chk_d.d - 56 and max(s.day) <= chk_d.d - 1) x)),
('wws.sales_daily: rows on a Sunday', '0',
 (select count(*)::text from wws.sales_daily where extract(isodow from day) = 7)),
('wws.price_history: rows', '64', (select count(*)::text from wws.price_history)),
('wws.inbound_delivery: deliveries', '100012@101 2027-02-18 x24,100012@199 2027-02-18 x24',
 (select string_agg(format('%s@%s %s x%s', article_number, store_id, expected_on, quantity),
                    ',' order by store_id) from wws.inbound_delivery)),
('wws.price_action: open actions', 'PA-SEED-100009 CENTRAL 100009@101,'
 'PA-SEED-100009-199 CENTRAL 100009@199',
 (select string_agg(format('%s %s %s@%s', action_id, kind, article_number, store_id),
                    ',' order by store_id) from wws.price_action where ended_at is null)),
('store 199 mirrors store 101 (prices, plan, stock, daily, history, actions, deliveries)',
 '1', (select count(distinct h)::text from (
    select store_id, md5(string_agg(x, '|' order by x)) as h from (
      select store_id, format('price %s %s', article_number, regular_price) as x
        from wws.article_price
      union all select store_id, format('plan %s %s', article_number, plan_week)
        from wws.sales_plan
      union all select store_id, format('stock %s %s', article_number, on_hand)
        from wws.stock
      union all select store_id, format('daily %s %s %s', article_number, day, units)
        from wws.sales_daily
      union all select store_id, format('hist %s %s %s %s %s', article_number, valid_from,
                                        valid_to, price, kind) from wws.price_history
      union all select store_id, format('action %s %s %s %s %s %s %s %s %s', article_number,
                                        kind, regular_price, action_price, pct_shown, ref30,
                                        valid_from, valid_to, ended_at) from wws.price_action
      union all select store_id, format('delivery %s %s %s', article_number, expected_on,
                                        quantity) from wws.inbound_delivery) i
     group by store_id) s)),
('pos.till: tills', '01|101|Root.DE.999.101.01|booth,98|199|Root.DE.999.199.98|probe,'
 '99|199|Root.DE.999.199.99|test',
 (select string_agg(concat_ws('|', till_id, store_id, location, kind), ',' order by till_id)
    from pos.till where active)),
('loyalty.program', 'POINTS-ID|POINTS|Markt-Bonus|POINTS-ACCOUNT-ID|2.00',
 (select string_agg(concat_ws('|', program_id, program_name, display_name, account_type,
                              earn_eur_per_point), ',') from loyalty.program)),
('loyalty.article_ref: same 30 articles as wws.article (number, id, name, category)',
 '30|0', (select (select count(*) from loyalty.article_ref) || '|' || count(*) from (
    (select article_number, article_id, name, category from loyalty.article_ref
     except select article_number, article_id, name, category from wws.article)
    union all
    (select article_number, article_id, name, category from wws.article
     except select article_number, article_id, name, category from loyalty.article_ref)) d)),
('loyalty.tag_vocabulary: tags', '10', (select count(*)::text from loyalty.tag_vocabulary)),
('loyalty.member: members, cards, segment', 'M-1001|CLUB-1001|PHYSICAL|Stammkundin, '
 'preisbewusst,M-1002|CLUB-1002|PHYSICAL|Familie, Wocheneinkauf,M-1003|CLUB-1003|'
 'PHYSICAL|Spontaneinkauf,M-1004|CLUB-1004|PHYSICAL|Genießer, saisonaffin,'
 'M-1005|CLUB-GAST|GUEST|Gast',
 (select string_agg(concat_ws('|', m.member_id, c.card_value, c.card_type, m.segment_label),
                    ',' order by m.member_id)
    from loyalty.member m join loyalty.card c on c.member_id = m.member_id)),
('loyalty.consent: offers/profiling', 'M-1001 t/t,M-1002 t/t,M-1003 t/f,M-1004 t/t,'
 'M-1005 f/f',
 (select string_agg(format('%s %s/%s', member_id, left(offers::text, 1),
                           left(profiling::text, 1)), ',' order by member_id)
    from loyalty.consent)),
('loyalty.purchase: purchases per member (days with an entry)',
 'M-1001=12,M-1002=13,M-1003=12,M-1004=15,M-1005=0',
 (select string_agg(m.member_id || '=' || (select count(*) from loyalty.purchase p
                                            where p.member_id = m.member_id),
                    ',' order by m.member_id) from loyalty.member m)),
('loyalty.purchase: all seeded, before D, location 101/01, 10:30', '0',
 (select count(*)::text from loyalty.purchase p cross join chk_d
   where not p.is_seed or (p.closed_at at time zone 'Europe/Berlin')::date >= chk_d.d
      or p.location <> 'Root.DE.999.101.01'
      or (p.closed_at at time zone 'Europe/Berlin')::time <> time '10:30')),
('loyalty.purchase_line: lines without profiling consent', '0',
 (select count(*)::text from loyalty.purchase_line l
    join loyalty.purchase p on p.purchase_transaction_id = l.purchase_transaction_id
    join loyalty.consent c on c.member_id = p.member_id where not c.profiling)),
('loyalty.purchase: total = sum of lines (profiling members)', '0',
 (select count(*)::text from loyalty.purchase p
    join loyalty.consent c on c.member_id = p.member_id and c.profiling
   where p.total_eur <> (select sum(l.effective_value_eur) from loyalty.purchase_line l
                          where l.purchase_transaction_id = p.purchase_transaction_id))),
('loyalty.purchase: M-1003 totals without lines (4 Craft-Pils + Chips)', '9.35',
 (select string_agg(distinct total_eur::text, ',' order by total_eur::text)
    from loyalty.purchase where member_id = 'M-1003')),
('loyalty.article_week_stats: rows', '240',
 (select count(*)::text from loyalty.article_week_stats)),
('loyalty.article_week_stats: week starts D-56 + 7(k-1)',
 (select string_agg((chk_d.d - 56 + 7 * k)::text, ',' order by k)
    from chk_d, generate_series(0, 7) as k),
 (select string_agg(distinct week_start::text, ',' order by week_start::text)
    from loyalty.article_week_stats)),
('loyalty.article_week_stats: rule 6.5 (w x 0.55, x 0.8, half up) except 100012', '0',
 (select count(*)::text from loyalty.article_week_stats s
    join chk_week w on w.article_number = s.article_number and w.store_id = '101'
    cross join chk_d
   where s.article_number <> '100012' and s.week_start = chk_d.d - 56 + 7 * (w.k - 1)
     and (s.member_purchases <> round(w.units * 0.55)
          or s.distinct_members <> round(s.member_purchases * 0.8)))),
('relations and schemas not owned by their service role', '0',
 (select count(*)::text from (
    select n.nspname, pg_get_userbyid(c.relowner) as owner
      from pg_class c join pg_namespace n on n.oid = c.relnamespace
     where n.nspname in ('pos', 'wws', 'loyalty', 'engine')
    union all
    select nspname, pg_get_userbyid(nspowner) from pg_namespace
     where nspname in ('pos', 'wws', 'loyalty', 'engine')) o
   where o.owner <> case o.nspname when 'pos' then :'r_pos' when 'wws' then :'r_wws'
                                   when 'loyalty' then :'r_loyalty' else :'r_engine' end)),
('engine role: select on pos.till/basket/basket_line, no insert on pos.basket',
 'true,true,true,false',
 (select concat_ws(',', has_table_privilege(:'r_engine', 'pos.till', 'select')::text,
                   has_table_privilege(:'r_engine', 'pos.basket', 'select')::text,
                   has_table_privilege(:'r_engine', 'pos.basket_line', 'select')::text,
                   has_table_privilege(:'r_engine', 'pos.basket', 'insert')::text))),
('search_path per service role in this DB', '4',
 (select count(*)::text from pg_db_role_setting s join pg_roles r on r.oid = s.setrole
   where s.setdatabase = (select oid from pg_database where datname = current_database())
     and (r.rolname, s.setconfig) in ((:'r_pos', '{search_path=pos}'::text[]),
                                      (:'r_wws', '{search_path=wws}'::text[]),
                                      (:'r_loyalty', '{search_path=loyalty}'::text[]),
                                      (:'r_engine', '{search_path=engine}'::text[])))),
('engine.proposal.note and engine.approval.sam_error_at',
 'note text not null default '''',sam_error_at timestamp with time zone',
 (select string_agg(format('%s %s%s', column_name, data_type,
                           case when is_nullable = 'NO' then ' not null default '
                                     || split_part(column_default, '::', 1) else '' end),
                    ',' order by table_name desc)
    from information_schema.columns
   where table_schema = 'engine' and (table_name, column_name) in
         (('proposal', 'note'), ('approval', 'sam_error_at')))),
('partial unique indexes (one open proposal per till, one open action)',
 'CREATE UNIQUE INDEX price_action_one_open ON wws.price_action USING btree '
 '(article_number, store_id) WHERE (ended_at IS NULL)|CREATE UNIQUE INDEX '
 'proposal_one_open_per_till ON engine.proposal USING btree (store_id, till_id) '
 'WHERE (status = ANY (ARRAY[''ready''::text, ''pending''::text]))',
 (select string_agg(indexdef, '|' order by indexname) from pg_indexes
   where (schemaname, indexname) in (('engine', 'proposal_one_open_per_till'),
                                     ('wws', 'price_action_one_open'))));

-- --------------------------------------------------------- golden values (6.8)

insert into gpos_check (name, expected, actual) values
-- signals of all 30 articles without a card
('6.8 articles with a signal (store 101)',
 '100001:slow_seller,100002:slow_seller,100008:season_end,100009:season_end+slow_seller,'
 '100028:slow_seller',
 (select string_agg(article_number || ':' || signals, ',' order by article_number)
    from chk_s101 where signals <> 'none')),
('6.8 on plan: 24 articles, no signal, sell_through within [0.95, 1.09]', '24|0',
 (select count(*) || '|' || count(*) filter (where sell_through not between 0.95 and 1.09)
    from chk_s101 where signals = 'none' and sell_through >= 0.8)),
-- S1 GEBIT Ente
('S1 100001 weekly units', '34,36,31,28,22,16,12,9',
 (select weekly from chk_s101 where article_number = '100001')),
('S1 100001 sold/plan, sell_through, avg 28d, stock, weeks of supply',
 '9/35 0.26 14.75 96 6.5',
 (select format('%s/%s %s %s %s %s', sold_7d, trim_scale(plan_7d), round(sell_through, 2),
                round(avg_week_28d, 2), stock, round(weeks_of_supply, 1))
    from chk_s101 where article_number = '100001')),
('S1 100001 trend, listed days, max/suggested step', 'falling 168 20/20',
 (select format('%s %s %s/%s', trend, listed_days, max_step, least(suggested_step, max_step))
    from chk_s101 where article_number = '100001')),
('S1 100001 step 20', '9.99 -> 7.99, -20 %, margin 22.6', pg_temp.chk_step('100001', 20)),
('S1 100001 step 30', '9.99 -> 6.99, -30 %, margin 11.5, blocked',
 pg_temp.chk_step('100001', 30)),
('S1 100001 effective price, ref30', '9.99 9.99',
 (select format('%s %s', effective_price, ref30) from chk_s101
   where article_number = '100001')),
-- S2 Herzpralinen
('S2 100008 weekly units', '0,0,0,0,12,26,38,52',
 (select weekly from chk_s101 where article_number = '100008')),
('S2 100008 season, end, days to end, stock, leftover, avg day 14d',
 'valentinstag ended 2027-02-14 -2 46 46 6.4',
 (select format('%s %s %s %s %s %s %s', season_code, season_status, season_end_date,
                days_to_end, stock, round(leftover), round(avg_day_14d, 1))
    from chk_s101 where article_number = '100008')),
('S2 100008 max/suggested step', '30/30',
 (select format('%s/%s', max_step, least(suggested_step, max_step)) from chk_s101
   where article_number = '100008')),
('S2 100008 step 30', '7.99 -> 5.49, -31 %, margin 39.6', pg_temp.chk_step('100008', 30)),
('S2 100008 base price at 5.49, ref30', '27.45 EUR/kg 7.99',
 (select pg_temp.chk_base_price('100008', 30) || ' ' || ref30 from chk_s101
   where article_number = '100008')),
-- S3 Espresso: article side
('S3 100012 without card: signals, sell_through, insight', 'none 0.57 neutral',
 (select format('%s %s %s', signals, round(sell_through, 2),
                case when sell_through >= 0.8 then 'on_plan' else 'neutral' end)
    from chk_s101 where article_number = '100012')),
('S3 100012 price history (101)',
 '2026-11-18 12.99 REGULAR until 2027-01-11,2027-01-11 14.49 REGULAR open',
 (select string_agg(format('%s %s %s %s',
                           to_char(valid_from at time zone 'Europe/Berlin', 'YYYY-MM-DD'),
                           price, kind,
                           coalesce('until ' || to_char(valid_to at time zone 'Europe/Berlin',
                                                        'YYYY-MM-DD'), 'open')),
                    ',' order by valid_from)
    from wws.price_history
   where article_number = '100012' and store_id = '101' and kind = 'REGULAR')),
('S3 100012 last price change, ref30', '2027-01-11 12.99 -> 14.49, ref30 14.49',
 (select format('%s %s -> %s, ref30 %s', c.changed_on, c.old_price, c.new_price, s.ref30)
    from chk_last_change c join chk_s101 s on s.article_number = c.article_number
   where c.article_number = '100012' and c.store_id = '101')),
-- S3 Espresso + M-1001 (Kaffeepause)
('S3 M-1001 Espresso purchase days and line values',
 '2026-12-01 12.99,2026-12-15 12.99,2026-12-29 12.99,2027-01-12 14.49',
 (select string_agg(format('%s %s', (p.closed_at at time zone 'Europe/Berlin')::date,
                           l.effective_value_eur), ',' order by p.closed_at)
    from loyalty.purchase p
    join loyalty.purchase_line l on l.purchase_transaction_id = p.purchase_transaction_id
   where p.member_id = 'M-1001' and l.article_number = '100012')),
('S3 M-1001/100012 buys 8w, 12w, days since last, median interval, overdue factor',
 '2 4 35 14 2.5',
 (select format('%s %s %s %s %s', buys_8w, buys_12w, days_since_last, median_interval,
                round(overdue_factor::numeric, 1))
    from chk_customer_behaviour where member_id = 'M-1001' and article_number = '100012')),
('S3 M-1001/100012 window edges D-56 and D-84: days to the nearest purchase', '7,7',
 (select string_agg((select min(abs(b.day - e.edge)) from chk_member_buy b
                      where b.member_id = 'M-1001' and b.article_number = '100012')::text,
                    ',' order by e.edge desc)
    from (select chk_d.d - 56 as edge from chk_d
          union all select chk_d.d - 84 from chk_d) e)),
('S3 100012 cardholder weekly, prior -> recent, drop %',
 '22,24,21,23,13,12,11,12 22.5 -> 12.0 46.7',
 (select format('%s %s -> %s %s', weekly, round(prior, 1), round(recent, 1),
                round((prior - recent) / prior * 100, 1))
    from chk_cardholder where article_number = '100012')),
('S3 customer_behaviour fires only for M-1001/100012', 'M-1001/100012',
 (select string_agg(member_id || '/' || article_number, ',' order by member_id, article_number)
    from chk_customer_behaviour where fires)),
('S3 100012 max/suggested step (customer_behaviour 10)', '10/10',
 (select format('%s/%s', max_step, least(10, max_step)) from chk_s101
   where article_number = '100012')),
('S3 100012 step 10', '14.49 -> 12.99, -10 %, margin 26.7', pg_temp.chk_step('100012', 10)),
('S3 100012 step 20', '14.49 -> 11.49, -20 %, margin 17.1, blocked',
 pg_temp.chk_step('100012', 20)),
('S3 100012 base price at 12.99', '12.99 EUR/kg', pg_temp.chk_base_price('100012', 10)),
('S3 100012 note (increase within 90 days, new price >= old price)',
 'Rücknahme der Preiserhöhung vom 11.01.',
 (select case when c.changed_on >= chk_d.d - 90 and c.new_price > c.old_price
                   and pg_temp.chk_point(c.new_price, 10) >= c.old_price
              then 'Rücknahme der Preiserhöhung vom ' || to_char(c.changed_on, 'DD.MM.')
              else '' end
    from chk_last_change c cross join chk_d
   where c.article_number = '100012' and c.store_id = '101')),
-- S6 Espresso + M-1003 (no profiling consent), S1 variant Ente + M-1002
('S6 M-1003 profiling consent and stored purchase lines', 'false 0',
 (select format('%s %s', c.profiling::text, (select count(*) from loyalty.purchase_line l
                                        join loyalty.purchase p using (purchase_transaction_id)
                                       where p.member_id = c.member_id))
    from loyalty.consent c where c.member_id = 'M-1003')),
('6.8 M-1002/100001: buys in 8 weeks, customer_behaviour', '1 false',
 (select format('%s %s', buys_8w, fires::text) from chk_customer_behaviour
   where member_id = 'M-1002' and article_number = '100001')),
-- S8 Plüschhase
('S8 100002 weekly units (rising 4 -> 14)', '4,5,6,7,8,10,12,14',
 (select weekly from chk_s101 where article_number = '100002')),
('S8 100002 sold/plan, sell_through, avg 28d, stock, weeks of supply',
 '14/30 0.47 11.00 90 8.2',
 (select format('%s/%s %s %s %s %s', sold_7d, trim_scale(plan_7d), round(sell_through, 2),
                round(avg_week_28d, 2), stock, round(weeks_of_supply, 1))
    from chk_s101 where article_number = '100002')),
('S8 100002 trend (avg w7..8 vs w5..6), season, max/suggested step',
 'rising 13.0 vs 9.0, ostern before, 30/10',
 (select format('%s %s vs %s, %s %s, %s/%s', trend, round(avg_recent, 1),
                round(avg_prior, 1), season_code, season_status, max_step,
                least(suggested_step, max_step))
    from chk_s101 where article_number = '100002')),
-- S5 Glühwein and Kochbuch (only blocked candidates)
('S5 100009 sold/plan, days to end, leftover/stock', '9/30 12 103/120',
 (select format('%s/%s %s %s/%s', sold_7d, trim_scale(plan_7d), days_to_end,
                round(leftover), stock)
    from chk_s101 where article_number = '100009')),
('S5 100009 blocked by the open central action',
 'PA-SEED-100009 2.99 until 2027-02-21 20:00, pct_shown 14 vs 3.49',
 (select format('%s %s until %s, pct_shown %s vs %s', s.action_id, s.action_price,
                to_char(s.action_valid_to at time zone 'Europe/Berlin',
                        'YYYY-MM-DD HH24:MI'), pa.pct_shown, pa.ref30)
    from chk_s101 s join wws.price_action pa on pa.action_id = s.action_id
   where s.article_number = '100009')),
('S5 100009 effective price, ref30', '2.99 2.99',
 (select format('%s %s', effective_price, ref30) from chk_s101
   where article_number = '100009')),
('S5 100028 sold/plan, weeks of supply, price bound', '0/4 14.0 true',
 (select format('%s/%s %s %s', sold_7d, trim_scale(plan_7d), round(weeks_of_supply, 1),
                price_bound::text)
    from chk_s101 where article_number = '100028')),
('6.3 ref30 of the heroes', '100001 9.99,100008 7.99,100009 2.99,100012 14.49',
 (select string_agg(article_number || ' ' || ref30, ',' order by article_number)
    from chk_s101 where article_number in ('100001', '100008', '100009', '100012')));

-- ------------------------------------------------------------------------ verdict

\if :{?verbose}
select id, name, expected, actual,
       case when expected is not distinct from actual then 'ok' else 'FAIL' end as result
  from gpos_check order by id;
\endif

do $$
declare
  failed int;
  total int;
  report text;
begin
  select count(*) filter (where expected is distinct from actual), count(*)
    into failed, total from gpos_check;
  if failed > 0 then
    select string_agg(format('[%s] %s: expected "%s", got "%s"', id, name, expected,
                             coalesce(actual, 'NULL')), E'\n' order by id)
      into report from gpos_check where expected is distinct from actual;
    raise exception '95-checks: % of % checks failed', failed, total
      using detail = report;
  end if;
end $$;

\pset tuples_only on
select format('95-checks: all %s checks passed (demo date %s)', count(*), :'demo_date')
  from gpos_check;
