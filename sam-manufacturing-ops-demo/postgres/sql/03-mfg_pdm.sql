-- mfg_pdm: product master data for Acme Manufacturing.
-- Four tables: material master, BOM, engineering change orders
-- and the per-plant ECO distribution status. Storyline anchor:
-- ECO-2025-118 replaces the HD-20 clutch disc with the sintered
-- HD-22 and raises the EOL torque test spec from 18.0 +/-0.5 Nm
-- to 22.0 +/-0.5 Nm. Plant 1 (Hamburg) acknowledged; Plant 2
-- (Graz) is stuck at PENDING -- the master-data root cause of
-- the quality incident. Idempotent: drop + recreate.

DROP TABLE IF EXISTS mfg_material_master;
DROP TABLE IF EXISTS mfg_bom;
DROP TABLE IF EXISTS mfg_eco;
DROP TABLE IF EXISTS mfg_eco_distribution;

CREATE TABLE mfg_material_master (
    material_id    text PRIMARY KEY,
    description    text NOT NULL,
    material_type  text NOT NULL,  -- FINISHED_GOOD | COMPONENT
    division       text,           -- POWER_TOOLS | AUTOMOTIVE | SHARED
    revision       text,
    status         text NOT NULL,  -- ACTIVE | OBSOLETE
    superseded_by  text,           -- material_id, for OBSOLETE parts
    uom            text,
    unit_cost_eur  numeric,
    eol_test_spec  text            -- current spec for finished goods
);

CREATE TABLE mfg_bom (
    parent_material_id    text NOT NULL,
    component_material_id text NOT NULL,
    qty_per               numeric NOT NULL,
    uom                   text,
    valid_from            date,
    introduced_by_eco     text,
    PRIMARY KEY (parent_material_id, component_material_id)
);

CREATE TABLE mfg_eco (
    eco_id             text PRIMARY KEY,
    title              text NOT NULL,
    description        text,
    change_type        text,        -- COMPONENT_CHANGE | SPEC_CHANGE | DOC_CHANGE
    affected_materials text,        -- comma-separated material_ids
    released_date      date,
    effective_date     date,
    status             text NOT NULL -- DRAFT | RELEASED | CLOSED
);

CREATE TABLE mfg_eco_distribution (
    eco_id          text NOT NULL,
    plant_id        text NOT NULL,
    plant_name      text,
    sent_at         timestamp,
    acknowledged_at timestamp,      -- NULL while PENDING
    status          text NOT NULL,  -- ACKNOWLEDGED | PENDING
    PRIMARY KEY (eco_id, plant_id)
);

INSERT INTO mfg_material_master VALUES
('FG_IX450',     'IX-450 Cordless Impact Driver 18V', 'FINISHED_GOOD', 'POWER_TOOLS', 'C', 'ACTIVE',   NULL,           'EA',  76.40, 'EOL torque 22.0 +/-0.5 Nm (per ECO-2025-118)'),
('FG_AG900',     'AG-900 Angle Grinder 125mm',        'FINISHED_GOOD', 'POWER_TOOLS', 'A', 'ACTIVE',   NULL,           'EA',  52.10, 'EOL runout <= 0.05 mm, no-load current <= 3.2 A'),
('FG_HD720',     'HD-720 Rotary Hammer SDS+',         'FINISHED_GOOD', 'POWER_TOOLS', 'B', 'ACTIVE',   NULL,           'EA', 104.80, 'EOL impact energy 2.7 +/-0.2 J'),
('FG_CK350',     'CK-350 Clutch Kit',                 'FINISHED_GOOD', 'AUTOMOTIVE',  'D', 'ACTIVE',   NULL,           'EA',  41.30, 'EOL engagement torque 22.0 +/-0.5 Nm (per ECO-2025-118)'),
('FG_BR120',     'BR-120 Brake Caliper Front',        'FINISHED_GOOD', 'AUTOMOTIVE',  'B', 'ACTIVE',   NULL,           'EA',  33.90, 'EOL pressure hold 60 bar / 10 s, leak <= 0.1 bar'),
('FG_WB060',     'WB-60 Wheel Bearing Unit',          'FINISHED_GOOD', 'AUTOMOTIVE',  'A', 'ACTIVE',   NULL,           'EA',  17.60, 'EOL vibration <= 1.8 mm/s RMS'),
('MAT_CLT_HD20', 'HD-20 Clutch Disc (hardened)',      'COMPONENT',     'SHARED',      'B', 'OBSOLETE', 'MAT_CLT_HD22', 'EA',   6.80, NULL),
('MAT_CLT_HD22', 'HD-22 Clutch Disc (sintered)',      'COMPONENT',     'SHARED',      'C', 'ACTIVE',   NULL,           'EA',   7.90, NULL),
('MAT_MTR_BL18', 'BL-18 Brushless Motor 18V',         'COMPONENT',     'POWER_TOOLS', 'D', 'ACTIVE',   NULL,           'EA',  18.20, NULL),
('MAT_BAT_5AH',  'PowerPack 18V 5.0Ah',               'COMPONENT',     'POWER_TOOLS', 'F', 'ACTIVE',   NULL,           'EA',  24.50, NULL),
('MAT_SPR_KIT',  'Diaphragm Spring Kit',              'COMPONENT',     'AUTOMOTIVE',  'B', 'ACTIVE',   NULL,           'EA',   5.40, NULL),
('MAT_PST_AL42', 'AL-42 Brake Piston',                'COMPONENT',     'AUTOMOTIVE',  'C', 'ACTIVE',   NULL,           'EA',   4.10, NULL),
('MAT_BRG_6205', '6205-2RS Deep Groove Bearing',      'COMPONENT',     'SHARED',      'A', 'ACTIVE',   NULL,           'EA',   2.30, NULL),
('MAT_GRB_SET',  'Gearbox Set 3-Speed',               'COMPONENT',     'POWER_TOOLS', 'B', 'ACTIVE',   NULL,           'EA',  11.70, NULL);

INSERT INTO mfg_bom VALUES
('FG_IX450', 'MAT_CLT_HD22', 1, 'EA', '2025-07-20', 'ECO-2025-118'),
('FG_IX450', 'MAT_MTR_BL18', 1, 'EA', '2024-02-01', NULL),
('FG_IX450', 'MAT_BAT_5AH',  1, 'EA', '2024-02-01', NULL),
('FG_IX450', 'MAT_GRB_SET',  1, 'EA', '2024-02-01', NULL),
('FG_AG900', 'MAT_MTR_BL18', 1, 'EA', '2023-09-01', NULL),
('FG_AG900', 'MAT_BRG_6205', 2, 'EA', '2023-09-01', NULL),
('FG_HD720', 'MAT_MTR_BL18', 1, 'EA', '2023-05-01', NULL),
('FG_HD720', 'MAT_GRB_SET',  1, 'EA', '2023-05-01', NULL),
('FG_CK350', 'MAT_CLT_HD22', 1, 'EA', '2025-07-20', 'ECO-2025-118'),
('FG_CK350', 'MAT_SPR_KIT',  1, 'EA', '2022-11-01', NULL),
('FG_CK350', 'MAT_BRG_6205', 1, 'EA', '2022-11-01', NULL),
('FG_BR120', 'MAT_PST_AL42', 2, 'EA', '2023-03-01', NULL),
('FG_BR120', 'MAT_BRG_6205', 1, 'EA', '2023-03-01', NULL),
('FG_WB060', 'MAT_BRG_6205', 2, 'EA', '2022-06-01', NULL);

INSERT INTO mfg_eco VALUES
('ECO-2025-118', 'HD-22 sintered clutch disc introduction',
 'Replace hardened HD-20 clutch disc with sintered HD-22 in all clutch-bearing assemblies (IX-450 impact mechanism, CK-350 clutch kit). End-of-line torque test specification raised from 18.0 +/-0.5 Nm to 22.0 +/-0.5 Nm. Test station calibration files must be updated before building with HD-22.',
 'COMPONENT_CHANGE', 'MAT_CLT_HD22,FG_IX450,FG_CK350',
 '2025-07-18', '2025-07-20', 'RELEASED'),
('ECO-2025-104', 'PowerPack 18V cell supplier requalification',
 'Second-source battery cells for PowerPack 18V 5.0Ah; no fit/form/function change.',
 'DOC_CHANGE', 'MAT_BAT_5AH',
 '2025-06-02', '2025-06-05', 'CLOSED'),
('ECO-2025-097', 'BR-120 piston seal groove tolerance update',
 'Tighten AL-42 piston seal groove tolerance after field returns; revision B to C.',
 'SPEC_CHANGE', 'MAT_PST_AL42,FG_BR120',
 '2025-05-14', '2025-05-20', 'CLOSED'),
('ECO-2025-121', 'AG-900 guard label artwork update',
 'Updated safety label artwork for EU market; documentation only.',
 'DOC_CHANGE', 'FG_AG900',
 '2025-07-29', '2025-08-11', 'RELEASED');

INSERT INTO mfg_eco_distribution VALUES
('ECO-2025-118', 'PLANT_HAM', 'Plant 1 - Hamburg', '2025-07-18 09:12:00', '2025-07-21 07:45:00', 'ACKNOWLEDGED'),
('ECO-2025-118', 'PLANT_GRZ', 'Plant 2 - Graz',    '2025-07-18 09:12:00', NULL,                  'PENDING'),
('ECO-2025-104', 'PLANT_GRZ', 'Plant 2 - Graz',    '2025-06-02 10:30:00', '2025-06-03 08:15:00', 'ACKNOWLEDGED'),
('ECO-2025-097', 'PLANT_HAM', 'Plant 1 - Hamburg', '2025-05-14 11:05:00', '2025-05-15 06:50:00', 'ACKNOWLEDGED'),
('ECO-2025-121', 'PLANT_GRZ', 'Plant 2 - Graz',    '2025-07-29 14:20:00', '2025-07-30 07:10:00', 'ACKNOWLEDGED');
