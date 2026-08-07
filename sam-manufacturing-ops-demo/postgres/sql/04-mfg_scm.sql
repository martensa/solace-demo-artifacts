-- mfg_scm: supply chain / inventory for Acme Manufacturing.
-- Three tables: inventory per plant+material, suppliers and open
-- purchase orders. Storyline anchor: HD-22 clutch disc at Plant 1
-- (Hamburg) -- on-hand 1850 with planned consumption 120/day
-- looks comfortable, but the OBSERVED rate (MongoDB consumption
-- events) is ~450/day since the ECO-2025-118 ramp-up: ~4 days of
-- cover against a 10-day primary lead time and a PO arriving in
-- 9 days. The qualified alternate (FrictionWorks, 3 days) is the
-- way out. Idempotent: drop + recreate.

DROP TABLE IF EXISTS mfg_inventory;
DROP TABLE IF EXISTS mfg_suppliers;
DROP TABLE IF EXISTS mfg_purchase_orders;

CREATE TABLE mfg_inventory (
    plant_id                  text NOT NULL,
    material_id               text NOT NULL,
    description               text,
    on_hand_qty               integer NOT NULL,
    safety_stock              integer,
    reorder_point             integer,
    planned_daily_consumption integer,  -- MRP planning parameter
    last_updated              timestamp,
    PRIMARY KEY (plant_id, material_id)
);

CREATE TABLE mfg_suppliers (
    supplier_id           text PRIMARY KEY,
    supplier_name         text NOT NULL,
    material_id           text NOT NULL,
    role                  text NOT NULL,  -- PRIMARY | ALTERNATE
    lead_time_days        integer,
    expedite_lead_time_days integer,      -- NULL if no expedite option
    qualified             boolean,
    unit_cost_eur         numeric,
    on_time_delivery_rate numeric,        -- 0..1
    country               text
);

CREATE TABLE mfg_purchase_orders (
    po_id        text PRIMARY KEY,
    supplier_id  text NOT NULL,
    material_id  text NOT NULL,
    plant_id     text NOT NULL,
    qty          integer NOT NULL,
    ordered_date date,
    eta          date,
    status       text NOT NULL  -- CONFIRMED | IN_TRANSIT | DELIVERED
);

INSERT INTO mfg_inventory VALUES
('PLANT_HAM', 'MAT_CLT_HD22', 'HD-22 Clutch Disc (sintered)',  1850,  800, 1200, 120, '2025-08-05 05:00:00'),
('PLANT_GRZ', 'MAT_CLT_HD22', 'HD-22 Clutch Disc (sintered)',   950,  400,  600,  60, '2025-08-05 05:00:00'),
('PLANT_HAM', 'MAT_CLT_HD20', 'HD-20 Clutch Disc (hardened)',   310,    0,    0,   0, '2025-08-05 05:00:00'),
('PLANT_HAM', 'MAT_SPR_KIT',  'Diaphragm Spring Kit',          5200, 1500, 2200, 160, '2025-08-05 05:00:00'),
('PLANT_HAM', 'MAT_PST_AL42', 'AL-42 Brake Piston',            9800, 2400, 3600, 420, '2025-08-05 05:00:00'),
('PLANT_HAM', 'MAT_BRG_6205', '6205-2RS Deep Groove Bearing', 14500, 3000, 5000, 610, '2025-08-05 05:00:00'),
('PLANT_GRZ', 'MAT_MTR_BL18', 'BL-18 Brushless Motor 18V',     4100, 1200, 1800, 210, '2025-08-05 05:00:00'),
('PLANT_GRZ', 'MAT_BAT_5AH',  'PowerPack 18V 5.0Ah',           3600, 1000, 1500, 190, '2025-08-05 05:00:00'),
('PLANT_GRZ', 'MAT_GRB_SET',  'Gearbox Set 3-Speed',           2900,  800, 1200, 150, '2025-08-05 05:00:00'),
('PLANT_GRZ', 'MAT_BRG_6205', '6205-2RS Deep Groove Bearing',  5600, 1400, 2200, 240, '2025-08-05 05:00:00');

INSERT INTO mfg_suppliers VALUES
('SUP_SINTERTECH', 'SinterTech GmbH',            'MAT_CLT_HD22', 'PRIMARY',   10, 6,    true,  7.90, 0.97, 'Germany'),
('SUP_FRICTIONW',  'FrictionWorks s.r.o.',       'MAT_CLT_HD22', 'ALTERNATE',  5, 3,    true,  8.55, 0.94, 'Czech Republic'),
('SUP_HARDMETAL',  'HardMetal Forming Ltd.',     'MAT_CLT_HD20', 'PRIMARY',   14, NULL, true,  6.80, 0.91, 'UK'),
('SUP_VOLTCELL',   'VoltCell Energy',            'MAT_BAT_5AH',  'PRIMARY',   21, 14,   true, 24.50, 0.95, 'South Korea'),
('SUP_DYNAMO',     'Dynamo Drives S.p.A.',       'MAT_MTR_BL18', 'PRIMARY',   15, 10,   true, 18.20, 0.96, 'Italy'),
('SUP_STEELSPRING','SteelSpring Federn GmbH',    'MAT_SPR_KIT',  'PRIMARY',    8, 4,    true,  5.40, 0.98, 'Germany'),
('SUP_ALUCAST',    'AluCast Precision',          'MAT_PST_AL42', 'PRIMARY',   12, 7,    true,  4.10, 0.93, 'Poland'),
('SUP_ROLLTECH',   'RollTech Bearings',          'MAT_BRG_6205', 'PRIMARY',    7, 3,    true,  2.30, 0.99, 'Slovakia');

INSERT INTO mfg_purchase_orders VALUES
('PO-88213', 'SUP_SINTERTECH',  'MAT_CLT_HD22', 'PLANT_HAM', 5000, '2025-08-04', '2025-08-14', 'CONFIRMED'),
('PO-88190', 'SUP_SINTERTECH',  'MAT_CLT_HD22', 'PLANT_GRZ', 2000, '2025-07-28', '2025-08-08', 'IN_TRANSIT'),
('PO-88101', 'SUP_STEELSPRING', 'MAT_SPR_KIT',  'PLANT_HAM', 4000, '2025-07-22', '2025-08-01', 'DELIVERED'),
('PO-88155', 'SUP_ROLLTECH',    'MAT_BRG_6205', 'PLANT_HAM', 8000, '2025-07-25', '2025-08-02', 'DELIVERED'),
('PO-88170', 'SUP_DYNAMO',      'MAT_MTR_BL18', 'PLANT_GRZ', 2500, '2025-07-26', '2025-08-11', 'IN_TRANSIT'),
('PO-88205', 'SUP_ALUCAST',     'MAT_PST_AL42', 'PLANT_HAM', 6000, '2025-08-01', '2025-08-13', 'CONFIRMED'),
('PO-88220', 'SUP_VOLTCELL',    'MAT_BAT_5AH',  'PLANT_GRZ', 3000, '2025-08-04', '2025-08-26', 'CONFIRMED');
