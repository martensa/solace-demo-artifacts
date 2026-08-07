---
name: mfg-crm-schema
description: Exact schema of the mfg_crm postgres database (table mfg_accounts). Load before writing any SQL against the Acme CRM DB connector to get correct table, column names, data types and query pitfalls.
---

# Acme Manufacturing CRM database schema

Database `mfg_crm` has exactly ONE table: `mfg_accounts`
(B2B account master data, one row per account).

## Table: mfg_accounts

| Column | Type | Notes |
|---|---|---|
| account_id | text | primary key, e.g. ACC_VOLTA; joins to mfg_oms.mfg_customer_orders.account_id |
| account_name | text | |
| account_type | text | OEM, DISTRIBUTOR, MRO |
| tier | text | Strategic, Key, Standard |
| industry | text | e.g. Automotive OEM, Tool Wholesale |
| city / country / region | text | region: EMEA, AMER, APAC |
| contact_name / contact_email | text | primary contact |
| annual_revenue_eur | numeric | revenue Acme makes with this account |
| open_claims | integer | open quality claims |
| line_down_penalty_eur_per_hour | numeric | OEM accounts only, NULL otherwise |
| customer_since | date | |
| last_order_date | date | |

## Query rules

1. Use exactly these table/column names; there are no other tables.
2. `line_down_penalty_eur_per_hour` is NULL for non-OEM accounts:
   filter with `IS NOT NULL` when ranking penalty exposure.
3. Cross-system: order data lives in a DIFFERENT database
   (mfg_oms, own connector/agent). You cannot JOIN across
   databases; correlate via `account_id` at the analysis level.
4. Small table (~12 rows): plain SELECTs are fine, no LIMIT needed.

For categorical value domains and ready-made example queries, read
`references/schema.md`.
