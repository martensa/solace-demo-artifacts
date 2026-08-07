-- mfg_crm: customer master data for Acme Manufacturing.
-- One table (mfg_accounts), one row per B2B account. OEM accounts
-- carry a line_down_penalty_eur_per_hour -- the contractual
-- penalty Acme pays when its parts stop the customer's line
-- (the C-level number behind the supply-chain movement).
-- Idempotent: drop + recreate.

DROP TABLE IF EXISTS mfg_accounts;

CREATE TABLE mfg_accounts (
    account_id                     text PRIMARY KEY,
    account_name                   text NOT NULL,
    account_type                   text NOT NULL, -- OEM | DISTRIBUTOR | MRO
    tier                           text NOT NULL, -- Strategic | Key | Standard
    industry                       text,
    city                           text,
    country                        text,
    region                         text,          -- EMEA | AMER | APAC
    contact_name                   text,
    contact_email                  text,
    annual_revenue_eur             numeric,
    open_claims                    integer DEFAULT 0,
    line_down_penalty_eur_per_hour numeric,       -- NULL for non-OEM
    customer_since                 date,
    last_order_date                date
);

INSERT INTO mfg_accounts VALUES
('ACC_VOLTA',      'Volta Motors AG',            'OEM',         'Strategic', 'Automotive OEM',        'Wolfsburg',  'Germany',        'EMEA', 'Dr. Ingrid Sommer',  'i.sommer@volta-motors.example',      1850000, 1, 45000, '2014-03-01', '2025-07-28'),
('ACC_ATLAS',      'Atlas Automotive Group',     'OEM',         'Strategic', 'Automotive OEM',        'Detroit',    'USA',            'AMER', 'Marcus Hale',        'm.hale@atlas-auto.example',           1420000, 0, 38000, '2016-09-01', '2025-07-30'),
('ACC_NIPPOND',    'NipponDrive Co., Ltd.',      'OEM',         'Key',       'Automotive OEM',        'Nagoya',     'Japan',          'APAC', 'Keiko Tanaka',       'k.tanaka@nippondrive.example',         980000, 0, 30000, '2018-04-01', '2025-07-22'),
('ACC_SCANDIA',    'Scandia Trucks AB',          'OEM',         'Key',       'Commercial Vehicles',   'Gothenburg', 'Sweden',         'EMEA', 'Lars Ekdahl',        'l.ekdahl@scandia-trucks.example',       760000, 2, 25000, '2017-11-01', '2025-07-15'),
('ACC_TOOLMART',   'ToolMart Distribution GmbH', 'DISTRIBUTOR', 'Strategic', 'Tool Wholesale',        'Cologne',    'Germany',        'EMEA', 'Petra Vogel',        'p.vogel@toolmart.example',              640000, 0, NULL,  '2015-06-01', '2025-08-01'),
('ACC_BUILDPRO',   'BuildPro Wholesale Inc.',    'DISTRIBUTOR', 'Key',       'Construction Supply',   'Chicago',    'USA',            'AMER', 'Dana Whitfield',     'd.whitfield@buildpro.example',          510000, 0, NULL,  '2019-02-01', '2025-07-25'),
('ACC_FERRAM',     'Ferramenta Brasil S.A.',     'DISTRIBUTOR', 'Standard',  'Tool Retail',           'Sao Paulo',  'Brazil',         'AMER', 'Joao Pereira',       'j.pereira@ferramenta.example',          230000, 1, NULL,  '2020-08-01', '2025-06-30'),
('ACC_ORIENTT',    'Orient Tools Trading LLC',   'DISTRIBUTOR', 'Standard',  'Tool Wholesale',        'Dubai',      'UAE',            'EMEA', 'Amir Haddad',        'a.haddad@orienttools.example',          190000, 0, NULL,  '2021-01-01', '2025-07-10'),
('ACC_FIXFAST',    'FixFast MRO Services',       'MRO',         'Key',       'Industrial Maintenance','Rotterdam',  'Netherlands',    'EMEA', 'Sanne de Vries',     's.devries@fixfast.example',             340000, 0, NULL,  '2018-10-01', '2025-07-29'),
('ACC_PACRIM',     'PacRim Machinery Services',  'MRO',         'Standard',  'Industrial Maintenance','Singapore',  'Singapore',      'APAC', 'Wei Lim',            'w.lim@pacrim.example',                  150000, 0, NULL,  '2022-05-01', '2025-06-18'),
('ACC_MOTORE',     'Motore Ricambi S.p.A.',      'DISTRIBUTOR', 'Key',       'Automotive Aftermarket','Turin',      'Italy',          'EMEA', 'Chiara Rossi',       'c.rossi@motore-ricambi.example',        420000, 0, NULL,  '2017-03-01', '2025-07-31'),
('ACC_HANSEI',     'Hansei Mobility Parts',      'OEM',         'Standard',  'Automotive OEM',        'Seoul',      'South Korea',    'APAC', 'Minjun Park',        'm.park@hansei-mobility.example',        450000, 0, 20000, '2021-09-01', '2025-05-20');
