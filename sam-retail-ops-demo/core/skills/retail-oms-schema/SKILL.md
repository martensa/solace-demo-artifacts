---
name: retail-oms-schema
description: Exact schema of the retail_oms postgres database (table retail_sales_orders, LINE-ITEM grain). Load before writing any SQL against the Retail OMS DB connector to get correct names, the order-level aggregation rules and query pitfalls.
---

# Retail OMS database schema

Database `retail_oms` has exactly ONE table: `retail_sales_orders`.

CRITICAL GRAIN: one row per ORDER LINE ITEM, not per order. An
order (order_id) has one row per product line; order-level columns
(order_total, order_tax, order_discount, order_items_count) repeat
on every line of that order.

## Table: retail_sales_orders

| Column | Type | Notes |
|---|---|---|
| order_id | text | order key, repeats per line, e.g. ORD_005 |
| transaction_id | text | one per order |
| customer_id | text | joins to retail_crm.retail_customers |
| store_id / store_name | text | |
| order_date | date | demo data is single-day (2024-10-22) |
| order_time | time | |
| receipt_number / invoice_id | text | |
| product_id / sku | text | joins to retail_pdm.retail_product_master |
| quantity | double precision | line quantity |
| unit_price | money | line unit price |
| total_price | money | line amount |
| discount | double precision | line discount |
| tax_amount | money | line tax |
| line_subtotal | money | line subtotal |
| promotion_id | text | nullable |
| cashier_id / cashier_name | text | |
| payment_method | text | CASH, CREDIT_CARD, DEBIT_CARD, MOBILE_PAY |
| order_total | money | ORDER level - repeats per line! |
| order_tax | money | ORDER level - repeats per line! |
| order_discount | double precision | ORDER level - repeats per line! |
| order_items_count | double precision | ORDER level - repeats per line! |

## Query rules

1. NEVER sum order_total/order_tax across raw rows - multi-line
   orders would be counted multiple times. Deduplicate to order
   grain first:
   `SELECT order_id, MAX(order_total::numeric) ... GROUP BY order_id`
   or aggregate line columns (total_price, line_subtotal) instead.
2. money columns need casts for math: `SUM(total_price::numeric)`.
3. The demo dataset covers a single day; do not filter on
   CURRENT_DATE or "last N days" - use the data's own dates.
4. Cross-system: customer master lives in retail_crm, product
   master in retail_pdm (separate databases/agents). No cross-
   database JOINs; correlate via customer_id / product_id / sku.

For value domains and ready-made example queries, read
`references/schema.md`.
