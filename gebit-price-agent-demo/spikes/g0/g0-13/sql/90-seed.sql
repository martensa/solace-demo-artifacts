-- 90-seed.sql: Stamm- und Presetdaten fuer pos und engine (G0-13-Umfang).
-- Werte: D 7.2 (ohne MHD-Artikel 010, 010M), RL 3.2-3.8 und
-- spikes/loyalty-tools/calc_triggers.py; GTINs synthetisch (GS1 20-29) [A].
-- Nicht enthalten: 8 Wochen sales_daily und 60 Tage Preishistorie
-- (gen_history.py, AP03); Loyalty-Seed in 91-loyalty-seed.sql.
-- Gesetzt ohne Quelle [A]: Einstand Tortilla 0,80, shelf_slot,
-- sold_until_start TR2/TR3/TR6, plan_today TR3/TR6, Konfidenz 0,22
-- (Ente -> Schaumbad), Zeitstempel der Preishistorie.
-- Idempotent: Stammdaten per Upsert, Presets per "on conflict do nothing".
-- Laeuft je Schema als Eigentuemer-Rolle (kein Fremdschreiben).

\if :{?role_prefix}
\else
\set role_prefix gpos
\endif
\set r_pos :role_prefix _pos
\set r_engine :role_prefix _engine
\set r_loyalty :role_prefix _loyalty
\set r_ui :role_prefix _ui

begin;

-- ---------------------------------------------------------------- pos
set local role :"r_pos";

insert into pos.till (till_id, store_id, location, kind) values
 ('01','101','Root.DE.999.101.01','booth'),
 ('02','101','Root.DE.999.101.02','background'),
 ('03','101','Root.DE.999.101.03','background'),
 ('04','101','Root.DE.999.101.04','background'),
 ('05','101','Root.DE.999.101.05','background')
on conflict (till_id) do update set store_id = excluded.store_id,
  location = excluded.location, kind = excluded.kind;

insert into pos.article (article_number, article_id, gtin, name, category, vat,
                         regular_price, cost_net, net_qty, unit, excluded_reason, shelf_slot) values
 ('article001','IDarticle001','2000000000015','Tortilla Chips Meersalz 200 g','food',      7, 1.79, 0.80, 0.200,'kg', null, 'B1'),
 ('article003','IDarticle003','2000000000039','Guacamole Dip 200 g',          'food',      7, 2.99, 1.35, 0.200,'kg', null, 'B2'),
 ('article004','IDarticle004','2000000000046','GEBIT Ente',                   'non_food', 19, 8.67, 4.40, null, null, null, 'A1'),
 ('article005','IDarticle005','2000000000053','Schaumbad Lavendel 500 ml',    'non_food', 19, 2.95, 0.95, 0.500,'l',  null, 'A2'),
 ('article007','IDarticle007','2000000000077','Espresso Bohnen 500 g',        'food',      7, 7.99, 4.20, 0.500,'kg', null, 'A3'),
 ('article008','IDarticle008','2000000000084','Cantuccini 200 g',             'food',      7, 2.29, 0.95, 0.200,'kg', null, 'A4'),
 ('article011','IDarticle011','2000000000114','Knusper-Müsli 750 g',          'food',      7, 3.99, 1.85, 0.750,'kg', null, 'C1'),
 ('article017','IDarticle017','2000000000176','Valentins-Pralinen 200 g',     'food',      7, 6.99, 3.20, 0.200,'kg', null, 'C2'),
 ('article019','IDarticle019','2000000000190','Fruchtgummi Bären 200 g',      'food',      7, 1.29, 0.45, 0.200,'kg', null, 'C3'),
 ('article025','IDarticle025','2000000000251','GEBIT Mehrweg-Einkaufstasche', 'non_food', 19, 1.50, 0.60, null, null, null, 'D1'),
 ('article028','IDarticle028','2000000000282','Kochbuch „Rheinische Küche“',  'book',      7,19.90,12.00, null, null, 'price_bound', 'D2'),
 ('article030','IDarticle030','2000000000305','Kaffeepads Crema 36 Stück',    'food',      7, 4.99, 2.45, 0.252,'kg', null, 'B3')
on conflict (article_number) do update set article_id = excluded.article_id,
  gtin = excluded.gtin, name = excluded.name, category = excluded.category,
  vat = excluded.vat, regular_price = excluded.regular_price,
  cost_net = excluded.cost_net, net_qty = excluded.net_qty, unit = excluded.unit,
  excluded_reason = excluded.excluded_reason, shelf_slot = excluded.shelf_slot;

insert into pos.article_price (article_number, store_id, regular_price)
select article_number, '101', regular_price from pos.article
on conflict (article_number, store_id) do update set regular_price = excluded.regular_price;

-- laufende Zentralaktion Fruchtgummi -15 % (TR7, Kollision G01); die
-- Pflichtspalten von Anhang A tragen Seed-Werte, visit_id 'seed'
-- uebersteht den Besuchs-Reset [A]
insert into pos.price_action (action_id, article_number, store_id, kind, regular_price,
  action_price, pct_shown, ref30, valid_from, valid_to, proposal_id, visit_id,
  approver_role, approver_ref) values
 ('PA-SEED-019','article019','101','PROMOTION',1.29,1.09,15,1.29,
  '2027-02-14 08:00+01','2027-02-21 20:00+01','seed-zentrale-article019','seed',
  'zentrale','seed')
on conflict (action_id) do nothing;

-- ------------------------------------------------------------- engine
set local role :"r_engine";

insert into engine.scenario (scenario_id, name, store_date, store_time_start,
                             time_factor, hero_article, params) values
 ('TR1','Die Ente schwimmt nicht',     '2027-02-17','14:00',20,'article004','{"horizon_end":"2027-02-19T20:00"}'),
 ('TR2','Zu viel Kaffee im Anmarsch',  '2027-02-17','14:00',20,'article030','{"horizon_end":"2027-02-19T20:00","target_days":2}'),
 ('TR3','Die Konkurrenz wirbt mit 6,99','2027-02-17','14:00',20,'article007','{"competitor_price":6.99,"plan_velocity_per_h":1.5}'),
 ('TR6','Nach dem Valentinstag',       '2027-02-17','14:00',20,'article017','{"horizon_end":"2027-02-23T20:00"}'),
 ('T2', 'Referenzpreis-Falle',         '2027-02-17','14:00',20,'article004','{"base":"TR1"}')
on conflict (scenario_id) do update set name = excluded.name,
  store_date = excluded.store_date, store_time_start = excluded.store_time_start,
  time_factor = excluded.time_factor, hero_article = excluded.hero_article,
  params = excluded.params;

insert into engine.scenario_article (scenario_id, article_number, plan_today,
  sold_until_start, stock, velocity_per_h, elasticity, horizon_h, leftover_weight,
  active_promo) values
 ('TR1','article004',30,   5, 42,0.85,-2.0,30,0.4,null),
 ('TR1','article019',null,null,null,null,null,null,null,'{"pct":15,"until":"2027-02-21"}'),
 ('TR2','article030',16.8, 8, 40,1.40,-2.2,30,0.3,null),
 ('TR3','article007',18,   5, 72,0.90,null,42,null,null),
 ('TR6','article017',4,    2, 60,0.36,-2.0,66,0.6,null),
 ('T2', 'article004',30,   5, 42,0.85,-2.0,30,0.4,null)
on conflict (scenario_id, article_number) do update set plan_today = excluded.plan_today,
  sold_until_start = excluded.sold_until_start, stock = excluded.stock,
  velocity_per_h = excluded.velocity_per_h, elasticity = excluded.elasticity,
  horizon_h = excluded.horizon_h, leftover_weight = excluded.leftover_weight,
  active_promo = excluded.active_promo;

insert into engine.store_note (note_id, scenario_id, article_number, source, note) values
 ('TR1-article004-1','TR1','article004','Lieferavis','Freitag nach Ladenschluss kommen 24 weitere Enten.'),
 ('TR2-article030-1','TR2','article030','Lieferavis','Donnerstag 07:00 kommen 72 Kaffeepads (bestellt 24, der Lieferant schickt ein Aktionsdisplay).'),
 ('T2-article004-1', 'T2', 'article004','Lieferavis','Freitag nach Ladenschluss kommen 24 weitere Enten.')
on conflict (note_id) do nothing;

insert into engine.inbound_delivery (delivery_id, scenario_id, article_number,
  quantity, expected_at, note) values
 ('DLV-TR2-030','TR2','article030',72,'2027-02-18 07:00+01','bestellt 24, Aktionsdisplay')
on conflict (delivery_id) do nothing;

insert into engine.season_calendar (article_number, season, season_end, step_plan) values
 ('article017','valentinstag','2027-02-14','[{"pct":30},{"pct":42,"needs":"zweitfreigabe"}]')
on conflict (article_number) do nothing;

-- ref30-Quelle: Ente mit Aktionswoche vor 6 Wochen (6,89, ausserhalb des
-- 30-Tage-Fensters, D 7.4); T2 ergaenzt 01.-07.02. zu 7,49
insert into engine.price_history (scenario_id, article_number, store_id, price,
  valid_from, valid_to, kind, announced) values
 ('TR1','article004','101',8.67,'2026-12-01 00:00+01','2027-01-04 00:00+01','REGULAR',false),
 ('TR1','article004','101',6.89,'2027-01-04 00:00+01','2027-01-11 00:00+01','PROMO',  true),
 ('TR1','article004','101',8.67,'2027-01-11 00:00+01',null,                 'REGULAR',false),
 ('TR2','article030','101',4.99,'2026-12-01 00:00+01',null,                 'REGULAR',false),
 ('TR3','article007','101',7.99,'2026-12-01 00:00+01',null,                 'REGULAR',false),
 ('TR6','article017','101',6.99,'2026-12-01 00:00+01',null,                 'REGULAR',false),
 ('T2', 'article004','101',8.67,'2026-12-01 00:00+01','2027-01-04 00:00+01','REGULAR',false),
 ('T2', 'article004','101',6.89,'2027-01-04 00:00+01','2027-01-11 00:00+01','PROMO',  true),
 ('T2', 'article004','101',8.67,'2027-01-11 00:00+01','2027-02-01 00:00+01','REGULAR',false),
 ('T2', 'article004','101',7.49,'2027-02-01 00:00+01','2027-02-08 00:00+01','PROMO',  true),
 ('T2', 'article004','101',8.67,'2027-02-08 00:00+01',null,                 'REGULAR',false)
on conflict (scenario_id, article_number, store_id, valid_from) do nothing;

-- Affinitaeten aus synthetischen Bons (D 7.3, RL calc TR4)
insert into engine.affinity_rule (antecedent, consequent, lift, confidence) values
 ('article004','article005',3.1,0.22),
 ('article001','article003',2.6,0.18)
on conflict (antecedent, consequent) do nothing;

commit;
