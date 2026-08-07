---
name: mfg-pdm-schema
description: Exact schema of the mfg_pdm postgres database (tables mfg_material_master, mfg_bom, mfg_eco, mfg_eco_distribution). Load before writing any SQL against the Acme PDM DB connector to get correct table, column names, data types and query pitfalls.
---

# Acme Manufacturing PDM database schema

Database `mfg_pdm` has exactly FOUR tables: material master, BOM,
engineering change orders (ECO) and the per-plant ECO
distribution status.

## Table: mfg_material_master

| Column | Type | Notes |
|---|---|---|
| material_id | text | primary key, e.g. FG_IX450, MAT_CLT_HD22 |
| description | text | |
| material_type | text | FINISHED_GOOD, COMPONENT |
| division | text | POWER_TOOLS, AUTOMOTIVE, SHARED |
| revision | text | current revision letter |
| status | text | ACTIVE, OBSOLETE |
| superseded_by | text | material_id, set for OBSOLETE parts |
| uom | text | |
| unit_cost_eur | numeric | |
| eol_test_spec | text | end-of-line test spec (finished goods) |

## Table: mfg_bom

| Column | Type | Notes |
|---|---|---|
| parent_material_id | text | finished good |
| component_material_id | text | component |
| qty_per | numeric | |
| uom | text | |
| valid_from | date | |
| introduced_by_eco | text | eco_id or NULL |

## Table: mfg_eco

| Column | Type | Notes |
|---|---|---|
| eco_id | text | primary key, e.g. ECO-2025-118 |
| title / description | text | |
| change_type | text | COMPONENT_CHANGE, SPEC_CHANGE, DOC_CHANGE |
| affected_materials | text | comma-separated material_ids |
| released_date / effective_date | date | |
| status | text | DRAFT, RELEASED, CLOSED |

## Table: mfg_eco_distribution

| Column | Type | Notes |
|---|---|---|
| eco_id | text | |
| plant_id | text | PLANT_HAM, PLANT_GRZ |
| plant_name | text | |
| sent_at | timestamp | when the change was distributed |
| acknowledged_at | timestamp | NULL while PENDING |
| status | text | ACKNOWLEDGED, PENDING |

## Query rules

1. Use exactly these table/column names; there are no other tables.
2. `affected_materials` is a comma-separated text field: filter
   with `LIKE '%FG_IX450%'`, not equality.
3. The distribution gap question ("which plant has not adopted a
   change?") is `mfg_eco_distribution WHERE status = 'PENDING'`.
4. Cross-system: orders live in mfg_oms, stock in mfg_scm --
   different databases, correlate via material_id/plant_id at the
   analysis level.
5. Small tables (max ~14 rows): plain SELECTs, no LIMIT needed.

For value domains and example queries, read
`references/schema.md`.
