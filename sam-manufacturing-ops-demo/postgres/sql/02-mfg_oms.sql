-- mfg_oms: order management for Acme Manufacturing.
-- Two tables: customer orders and the production orders that
-- fulfil them. Storyline anchors:
--   ORD-2025-30412 (Volta Motors, CK-350 clutch kits, Plant 1)
--   ORD-2025-30388 (ToolMart, IX-450 impact drivers, Plant 2)
--     -> production order PRD-118-4718 on QUALITY_HOLD after the
--        EOL torque failures on Line L3 (ECO-2025-118 story).
-- Idempotent: drop + recreate.

DROP TABLE IF EXISTS mfg_customer_orders;
DROP TABLE IF EXISTS mfg_production_orders;

CREATE TABLE mfg_customer_orders (
    order_id            text PRIMARY KEY,
    account_id          text NOT NULL,   -- joins mfg_crm.mfg_accounts (cross-DB)
    product_id          text NOT NULL,   -- joins mfg_pdm.mfg_material_master
    product_name        text,
    qty                 integer NOT NULL,
    unit_price_eur      numeric,
    order_value_eur     numeric,
    order_date          date,
    requested_delivery  date,
    status              text NOT NULL,   -- OPEN | IN_PRODUCTION | SHIPPED | DELIVERED
    plant_id            text,            -- PLANT_HAM | PLANT_GRZ
    notes               text
);

CREATE TABLE mfg_production_orders (
    prod_order_id   text PRIMARY KEY,
    order_id        text,                -- customer order it fulfils
    plant_id        text NOT NULL,
    line_id         text,
    product_id      text NOT NULL,
    qty             integer NOT NULL,
    status          text NOT NULL,       -- RELEASED | IN_PROCESS | QUALITY_HOLD | COMPLETED
    hold_reason     text,
    scheduled_start date,
    scheduled_end   date
);

INSERT INTO mfg_customer_orders VALUES
('ORD-2025-30412', 'ACC_VOLTA',    'FG_CK350', 'CK-350 Clutch Kit',              4000,  98.00, 392000, '2025-07-10', '2025-08-15', 'IN_PRODUCTION', 'PLANT_HAM', 'Strategic OEM program; new HD-22 clutch disc per ECO-2025-118'),
('ORD-2025-30388', 'ACC_TOOLMART', 'FG_IX450', 'IX-450 Cordless Impact Driver',  1200, 189.00, 226800, '2025-07-08', '2025-08-20', 'IN_PRODUCTION', 'PLANT_GRZ', 'Autumn campaign stock for DACH retail'),
('ORD-2025-30395', 'ACC_ATLAS',    'FG_BR120', 'BR-120 Brake Caliper Front',     6000,  74.50, 447000, '2025-07-09', '2025-09-01', 'IN_PRODUCTION', 'PLANT_HAM', NULL),
('ORD-2025-30401', 'ACC_SCANDIA',  'FG_WB060', 'WB-60 Wheel Bearing Unit',       3500,  41.00, 143500, '2025-07-09', '2025-08-25', 'IN_PRODUCTION', 'PLANT_HAM', NULL),
('ORD-2025-30360', 'ACC_NIPPOND',  'FG_CK350', 'CK-350 Clutch Kit',              2500,  98.00, 245000, '2025-07-01', '2025-08-05', 'SHIPPED',       'PLANT_HAM', 'First batch on new HD-22 disc'),
('ORD-2025-30355', 'ACC_BUILDPRO', 'FG_AG900', 'AG-900 Angle Grinder 125mm',     2000, 129.00, 258000, '2025-06-28', '2025-08-10', 'IN_PRODUCTION', 'PLANT_GRZ', NULL),
('ORD-2025-30340', 'ACC_MOTORE',   'FG_CK350', 'CK-350 Clutch Kit',               800,  98.00,  78400, '2025-06-25', '2025-07-30', 'DELIVERED',     'PLANT_HAM', 'Aftermarket batch, still HD-20 disc (pre-ECO)'),
('ORD-2025-30328', 'ACC_FIXFAST',  'FG_HD720', 'HD-720 Rotary Hammer',            450, 249.00, 112050, '2025-06-20', '2025-07-25', 'DELIVERED',     'PLANT_GRZ', NULL),
('ORD-2025-30422', 'ACC_ORIENTT',  'FG_IX450', 'IX-450 Cordless Impact Driver',   600, 189.00, 113400, '2025-07-15', '2025-09-10', 'OPEN',          'PLANT_GRZ', 'Awaiting capacity slot after ORD-2025-30388'),
('ORD-2025-30425', 'ACC_HANSEI',   'FG_BR120', 'BR-120 Brake Caliper Front',     1500,  74.50, 111750, '2025-07-18', '2025-09-15', 'OPEN',          'PLANT_HAM', NULL),
('ORD-2025-30430', 'ACC_VOLTA',    'FG_CK350', 'CK-350 Clutch Kit',              4000,  98.00, 392000, '2025-07-25', '2025-09-15', 'OPEN',          'PLANT_HAM', 'Follow-up call-off, same program as ORD-2025-30412'),
('ORD-2025-30310', 'ACC_FERRAM',   'FG_AG900', 'AG-900 Angle Grinder 125mm',      900, 129.00, 116100, '2025-06-12', '2025-07-20', 'DELIVERED',     'PLANT_GRZ', NULL);

INSERT INTO mfg_production_orders VALUES
('PRD-118-4711', 'ORD-2025-30412', 'PLANT_HAM', 'L2', 'FG_CK350', 4000, 'IN_PROCESS',   NULL,                                              '2025-07-22', '2025-08-12'),
('PRD-118-4718', 'ORD-2025-30388', 'PLANT_GRZ', 'L3', 'FG_IX450', 1200, 'QUALITY_HOLD', 'EOL torque test failures on L3 station EOL-2',    '2025-07-24', '2025-08-16'),
('PRD-118-4703', 'ORD-2025-30395', 'PLANT_HAM', 'L4', 'FG_BR120', 6000, 'IN_PROCESS',   NULL,                                              '2025-07-20', '2025-08-28'),
('PRD-118-4705', 'ORD-2025-30401', 'PLANT_HAM', 'L5', 'FG_WB060', 3500, 'IN_PROCESS',   NULL,                                              '2025-07-21', '2025-08-20'),
('PRD-118-4680', 'ORD-2025-30360', 'PLANT_HAM', 'L2', 'FG_CK350', 2500, 'COMPLETED',    NULL,                                              '2025-07-05', '2025-07-30'),
('PRD-118-4692', 'ORD-2025-30355', 'PLANT_GRZ', 'L1', 'FG_AG900', 2000, 'IN_PROCESS',   NULL,                                              '2025-07-15', '2025-08-08'),
('PRD-118-4655', 'ORD-2025-30340', 'PLANT_HAM', 'L2', 'FG_CK350',  800, 'COMPLETED',    NULL,                                              '2025-06-28', '2025-07-24'),
('PRD-118-4640', 'ORD-2025-30328', 'PLANT_GRZ', 'L2', 'FG_HD720',  450, 'COMPLETED',    NULL,                                              '2025-06-24', '2025-07-20');
