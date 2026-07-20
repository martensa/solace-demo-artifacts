---
name: retail-pdm-schema
description: Exact schema of the retail_pdm postgres database (table retail_product_master). Load before writing any SQL against the Retail PDM DB connector to get correct table, column names, data types and query pitfalls.
---

# Retail PDM database schema

Database `retail_pdm` has exactly ONE table: `retail_product_master`
(product master data, one row per product, ~52 rows).

## Table: retail_product_master

| Column | Type | Notes |
|---|---|---|
| product_id | text | primary key, joins to retail_oms.retail_sales_orders.product_id |
| sku | text | alt key, also in retail_oms |
| product_name | text | |
| category_main | text | e.g. Produce, Dairy, Seafood |
| category_sub | text | |
| department | text | e.g. Fresh Produce, Wine Cellar |
| brand | text | |
| supplier_id / supplier_name | text | |
| unit_price | money | selling price |
| cost_price | money | |
| unit_measure | text | e.g. pound, bottle, jar |
| barcode | text | |
| organic / local / artisan / luxury / premium | boolean | product flags |
| attributes | text | free text |
| stock_level | integer | |
| dimensions_cm | text | |
| weight_kg | double precision | |
| margin_percent | double precision | |
| inventory_status | text | e.g. In Stock, Low Stock, Seasonal |
| popularity_score | double precision | |
| seasonality | text | e.g. Year-Round, Oct-Jan |

## Query rules

1. Use exactly these table/column names; there are no other tables.
2. money columns (`unit_price`, `cost_price`) need casts for math:
   `AVG(unit_price::numeric)`.
3. "Low inventory" questions: filter `inventory_status` (e.g.
   'Low Stock', 'Limited') or sort by `stock_level` - there is no
   separate minimum-level column.
4. Cross-system: sales lines live in retail_oms (own database and
   agent). No cross-database JOINs; correlate via product_id/sku.

For category/department/status value domains and example queries,
read `references/schema.md`.
