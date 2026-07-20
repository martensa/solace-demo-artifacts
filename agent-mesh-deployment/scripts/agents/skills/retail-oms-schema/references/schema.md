# retail_oms reference: value domains and example queries

## Value domains

- payment_method: CASH, CREDIT_CARD, DEBIT_CARD, MOBILE_PAY
- store_name (17 stores), e.g.: Austin Downtown Foodie Market,
  Beverly Hills Gourmet, Capitol Hill Whole Foods Coop,
  Pike Place Artisan Foods, South Beach Organic Market, ...
- order_date: 2024-10-22 (single-day demo dataset)
- Scale: 52 line rows, 17 orders

## Example queries

Revenue per order (correct order-grain dedup):

```sql
SELECT order_id,
       MAX(customer_id)            AS customer_id,
       MAX(store_name)             AS store_name,
       MAX(order_total::numeric)   AS order_total
FROM retail_sales_orders
GROUP BY order_id
ORDER BY order_total DESC;
```

Total revenue by store (line-level aggregation, no double count):

```sql
SELECT store_name,
       COUNT(DISTINCT order_id)      AS orders,
       SUM(total_price::numeric)     AS revenue
FROM retail_sales_orders
GROUP BY store_name
ORDER BY revenue DESC;
```

Payment method distribution at order grain:

```sql
SELECT payment_method,
       COUNT(*) AS orders
FROM (
  SELECT order_id, MAX(payment_method) AS payment_method
  FROM retail_sales_orders
  GROUP BY order_id
) o
GROUP BY payment_method
ORDER BY orders DESC;
```

Top products by units sold (join keys for PDM correlation):

```sql
SELECT product_id, sku,
       SUM(quantity)             AS units,
       SUM(total_price::numeric) AS revenue
FROM retail_sales_orders
GROUP BY product_id, sku
ORDER BY revenue DESC
LIMIT 10;
```
