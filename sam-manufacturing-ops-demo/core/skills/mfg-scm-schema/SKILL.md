---
name: mfg-scm-schema
description: Exact schema of the mfg_scm postgres database (tables mfg_inventory, mfg_suppliers, mfg_purchase_orders). Load before writing any SQL against the Acme SCM DB connector to get correct table, column names, data types and query pitfalls.
---

# Acme Manufacturing SCM database schema

Database `mfg_scm` has exactly THREE tables: inventory per plant
and material, suppliers, and purchase orders.

## Table: mfg_inventory

| Column | Type | Notes |
|---|---|---|
| plant_id | text | PLANT_HAM, PLANT_GRZ (PK with material_id) |
| material_id | text | joins mfg_pdm.mfg_material_master (cross-DB) |
| description | text | |
| on_hand_qty | integer | |
| safety_stock / reorder_point | integer | |
| planned_daily_consumption | integer | MRP PLANNING parameter -- the ACTUAL rate lives in the plant telemetry store (MongoDB, Shop Floor Analyst) |
| last_updated | timestamp | |

## Table: mfg_suppliers

| Column | Type | Notes |
|---|---|---|
| supplier_id | text | primary key |
| supplier_name | text | |
| material_id | text | material this supplier delivers |
| role | text | PRIMARY, ALTERNATE |
| lead_time_days | integer | standard lead time |
| expedite_lead_time_days | integer | NULL if no expedite option |
| qualified | boolean | |
| unit_cost_eur | numeric | |
| on_time_delivery_rate | numeric | 0..1 |
| country | text | |

## Table: mfg_purchase_orders

| Column | Type | Notes |
|---|---|---|
| po_id | text | primary key |
| supplier_id / material_id / plant_id | text | |
| qty | integer | |
| ordered_date / eta | date | |
| status | text | CONFIRMED, IN_TRANSIT, DELIVERED |

## Query rules

1. Use exactly these table/column names; there are no other tables.
2. Days-of-cover math: `planned_daily_consumption` is the PLAN.
   When the question involves the observed/actual rate, state that
   actual consumption lives in the MongoDB plant store (Shop Floor
   Analyst) and compute cover for both rates when given one.
3. Open supply = mfg_purchase_orders with status CONFIRMED or
   IN_TRANSIT; DELIVERED POs are history.
4. Alternate sourcing: mfg_suppliers role = 'ALTERNATE' AND
   qualified = true; compare `expedite_lead_time_days` against
   the stockout horizon.
5. Small tables (max ~10 rows): plain SELECTs, no LIMIT needed.

For value domains and example queries, read
`references/schema.md`.
