---
name: mfg-oms-schema
description: Exact schema of the mfg_oms postgres database (tables mfg_customer_orders, mfg_production_orders). Load before writing any SQL against the Acme OMS DB connector to get correct table, column names, data types and query pitfalls.
---

# Acme Manufacturing OMS database schema

Database `mfg_oms` has exactly TWO tables: `mfg_customer_orders`
(B2B orders) and `mfg_production_orders` (the plant production
orders that fulfil them).

## Table: mfg_customer_orders

| Column | Type | Notes |
|---|---|---|
| order_id | text | primary key, e.g. ORD-2025-30412 |
| account_id | text | joins to mfg_crm.mfg_accounts (cross-DB) |
| product_id | text | joins to mfg_pdm.mfg_material_master (cross-DB) |
| product_name | text | denormalized description |
| qty | integer | |
| unit_price_eur / order_value_eur | numeric | |
| order_date / requested_delivery | date | |
| status | text | OPEN, IN_PRODUCTION, SHIPPED, DELIVERED |
| plant_id | text | PLANT_HAM (Hamburg), PLANT_GRZ (Graz) |
| notes | text | free text, may be NULL |

## Table: mfg_production_orders

| Column | Type | Notes |
|---|---|---|
| prod_order_id | text | primary key, e.g. PRD-118-4718 |
| order_id | text | the customer order it fulfils |
| plant_id / line_id | text | e.g. PLANT_GRZ / L3 |
| product_id | text | finished good material id |
| qty | integer | |
| status | text | RELEASED, IN_PROCESS, QUALITY_HOLD, COMPLETED |
| hold_reason | text | NULL unless QUALITY_HOLD |
| scheduled_start / scheduled_end | date | |

## Query rules

1. Use exactly these table/column names; there are no other tables.
2. JOIN the two tables via `order_id` to connect customer impact
   with plant execution.
3. Cross-system: account master data lives in mfg_crm, product and
   ECO master data in mfg_pdm -- different databases, no cross-DB
   JOINs; correlate via ids at the analysis level.
4. Small tables (~12 and ~8 rows): plain SELECTs, no LIMIT needed.

For value domains and example queries, read
`references/schema.md`.
