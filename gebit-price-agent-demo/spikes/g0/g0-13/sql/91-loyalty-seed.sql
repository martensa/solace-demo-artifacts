-- 91-loyalty-seed.sql: Loyalty-Seed (fiktive Daten).
-- Quelle: spikes/loyalty-sql/20-loyalty-seed.sql (RL 2.6), Werte
-- unveraendert. G0-13-Korrekturen:
--   K4 jede Insert-Anweisung mit "on conflict do nothing" (das Original
--      verlaesst sich auf TRUNCATE in seed.sh und bricht im 2. Lauf mit
--      duplicate key ab); ein Re-Seed setzt Laufzeitstaende NICHT zurueck,
--      das bleibt ResetDemoState
--   K3 set role :r_loyalty, eine Transaktion
-- Idempotent.

\if :{?role_prefix}
\else
\set role_prefix gpos
\endif
\set r_pos :role_prefix _pos
\set r_engine :role_prefix _engine
\set r_loyalty :role_prefix _loyalty
\set r_ui :role_prefix _ui

begin;
set local role :"r_loyalty";
-- Seed (idempotent via TRUNCATE in seed.sh). Fictional data only.
set local search_path = loyalty;

insert into program values
 ('POINTS-ID','POINTS','Markt-Bonus','POINTS-ACCOUNT-ID','POINTS-CURRENCY-ID','Points',
  'promotion-base-points', 2.00)
on conflict do nothing;

insert into article_ref (article_number, article_id, name, category, points_eligible, coupon_eligible) values
 ('article001','IDarticle001','Tortilla Chips Meersalz 200 g','snacks',   true, true),
 ('article003','IDarticle003','Guacamole Dip 200 g',           'dips',     true, true),
 ('article004','IDarticle004','GEBIT Ente',                    'geschenke',true, true),
 ('article005','IDarticle005','Schaumbad Lavendel 500 ml',     'drogerie', true, true),
 ('article007','IDarticle007','Espresso Bohnen 500 g',         'kaffee',   true, true),
 ('article008','IDarticle008','Cantuccini 200 g',              'gebaeck',  true, true),
 ('article017','IDarticle017','Valentins-Pralinen 200 g',      'suesswaren',true, true),
 ('article019','IDarticle019','Fruchtgummi Baeren 200 g',      'suesswaren',true, true),
 ('article028','IDarticle028','Kochbuch Rheinische Kueche',    'buch',     false, false),
 ('article030','IDarticle030','Kaffeepads Crema 36 Stueck',    'kaffee',   true, true)
on conflict do nothing;

insert into tag_vocabulary values
 ('kaffee','Kaffee'), ('gebaeck','Gebaeck'), ('suesswaren','Suesswaren'),
 ('snacks','Snacks'), ('dips','Dips'), ('getraenke_alkoholfrei','Alkoholfreie Getraenke'),
 ('drogerie','Drogerie'), ('geschenke','Geschenke'), ('buch','Buch')
on conflict do nothing;

insert into member (member_id, program_id, customer_ref, persona_key, persona_label, anonymous, salutation) values
 ('M-0001','POINTS-ID','CUST-DEMO-0001','kaffeepause','Kaffeepause', false,'FORMAL'),
 ('M-0002','POINTS-ID','CUST-DEMO-0002','filmabend',  'Filmabend',   false,'INFORMAL'),
 ('M-0003','POINTS-ID','CUST-DEMO-0003','badezeit',   'Badezeit',    false,'FORMAL'),
 ('M-0004','POINTS-ID','CUST-DEMO-0004','nur_basis',  'Nur Basis',   false,'FORMAL'),
 ('M-0099','POINTS-ID', null,           'gast',       'Gastkarte',   true, 'FORMAL')
on conflict do nothing;

insert into card values
 ('CLUB-0001','M-0001','PHYSICAL','ACTIVE', now()), ('CLUB-0002','M-0002','PHYSICAL','ACTIVE', now()),
 ('CLUB-0003','M-0003','PHYSICAL','ACTIVE', now()), ('CLUB-0004','M-0004','PHYSICAL','ACTIVE', now()),
 ('CLUB-GAST','M-0099','GUEST','ACTIVE', now())
on conflict do nothing;

insert into consent (member_id, offers, profiling, digital_receipt, policy_version, source) values
 ('M-0001', true, true,  true,  'demo-2027-02', 'seed'),
 ('M-0002', true, true,  false, 'demo-2027-02', 'seed'),
 ('M-0003', true, true,  false, 'demo-2027-02', 'seed'),
 ('M-0004', true, false, false, 'demo-2027-02', 'seed'),
 ('M-0099', false,false, false, 'demo-2027-02', 'seed')
on conflict do nothing;

insert into member_tag (member_id, tag, source) values
 ('M-0001','kaffee','EXPLICIT'), ('M-0001','gebaeck','EXPLICIT'), ('M-0001','suesswaren','EXPLICIT'),
 ('M-0002','snacks','EXPLICIT'), ('M-0002','dips','EXPLICIT'), ('M-0002','getraenke_alkoholfrei','EXPLICIT'),
 ('M-0003','drogerie','EXPLICIT'), ('M-0003','geschenke','EXPLICIT')
on conflict do nothing;

insert into account (account_id, member_id, program_id, account_type, balance) values
 ('ACC-M-0001-POINTS','M-0001','POINTS-ID','POINTS-ACCOUNT-ID',1240),
 ('ACC-M-0002-POINTS','M-0002','POINTS-ID','POINTS-ACCOUNT-ID', 380),
 ('ACC-M-0003-POINTS','M-0003','POINTS-ID','POINTS-ACCOUNT-ID', 655),
 ('ACC-M-0004-POINTS','M-0004','POINTS-ID','POINTS-ACCOUNT-ID',  90),
 ('ACC-M-0099-POINTS','M-0099','POINTS-ID','POINTS-ACCOUNT-ID',   0)
on conflict do nothing;

insert into offer (offer_id, kind, target_article, condition_article, match_tags, discount_type,
                   discount_value, max_discount_eur, min_basket_eur, valid_days, in_catalogue,
                   approval, prefix, promotion_code, promotion_id, text_key, priority) values
 ('OFF-GUAC-30',      'TIED_OFFER',      'article003','article001','{snacks,dips}','RELATIVE',30, 1.00, 0, 0, true,'NONE','GPOS','GUAC30','promo-guac-30','offer.guac30',10),
 ('OFF-CANTUCCINI-30','PERSONAL_COUPON', 'article008','article007','{gebaeck,kaffee}','RELATIVE',30, 1.00, 0, 7, true,'NONE',null,null,'promo-cantuccini-30','coupon.cantuccini30',20),
 ('OFF-KAFFEEPADS-30','PERSONAL_COUPON', 'article030', null,      '{kaffee}','RELATIVE',30, 2.00, 0, 7, true,'NONE',null,null,'promo-kaffeepads-30','coupon.kaffeepads30',30),
 ('OFF-SCHAUMBAD-30', 'CHECKOUT_COUPON', 'article005','article004','{drogerie,geschenke}','RELATIVE',30, 1.00, 0,14, true,'NONE','GPOS',null,'promo-schaumbad-30','voucher.schaumbad30',40),
 ('OFF-WELCOME-10',   'CHECKOUT_COUPON',  null,        null,      '{}','RELATIVE',10, 2.00,10,14, true,'NONE','GPOS',null,'promo-welcome-10','voucher.welcome10',90),
 ('OFF-SPECIAL',      'SPECIAL_COUPON',   null,        null,      '{}','RELATIVE',50, 5.00, 0,14, false,'HUMAN',null,null,'promo-special','coupon.special',99)
on conflict do nothing;

commit;
