---
name: retail-crm-schema
description: Exact schema of the retail_crm postgres database (table retail_customers). Load before writing any SQL against the Retail CRM DB connector to get correct table, column names, data types and query pitfalls.
---

# Retail CRM database schema

Database `retail_crm` has exactly ONE table: `retail_customers`
(customer master data, one row per customer).

## Table: retail_customers

| Column | Type | Notes |
|---|---|---|
| customer_id | text | primary key, e.g. CUST_001; joins to retail_oms.retail_sales_orders.customer_id |
| customer_type | text | categorical, e.g. VIP, STUDENT, TOURIST |
| loyalty_card | text | card number |
| membership_tier | text | categorical, e.g. Gold, Platinum, Diamond |
| membership_since | date | |
| age_group | text | RANGE STRING like '25-34', NOT numeric |
| estimated_income | text | RANGE STRING like '75000-100000', NOT numeric |
| household_size | integer | |
| lifestyle | text | categorical, e.g. Urban Foodie |
| city / state / region | text | region e.g. Northeast, West Coast |
| preference_organic | boolean | |
| preference_premium | boolean | |
| preference_local | boolean | |
| preference_health_conscious | boolean | |
| preference_sustainable | boolean | |
| preference_budget_conscious | boolean | |
| total_transactions | integer | lifetime aggregate |
| total_spend | money | lifetime aggregate |
| first_transaction_date | date | |
| last_transaction_date | date | |

## Query rules

1. Use exactly these table/column names; there are no other tables.
2. `total_spend` is postgres `money`: cast for math and sorting,
   e.g. `SUM(total_spend::numeric)`, `ORDER BY total_spend::numeric`.
3. `age_group` and `estimated_income` are text ranges; filter with
   string equality or `LIKE`, never with numeric comparisons.
4. Cross-system: order data lives in a DIFFERENT database
   (retail_oms, own connector/agent). You cannot JOIN across
   databases; correlate via `customer_id` at the analysis level.
5. Small table (~13 rows): plain SELECTs are fine, no LIMIT needed.

For categorical value domains and ready-made example queries, read
`references/schema.md`.
