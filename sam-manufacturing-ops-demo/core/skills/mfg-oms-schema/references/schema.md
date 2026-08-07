# mfg_oms reference: value domains and example queries

## Categorical value domains (exact values in the data)

- mfg_customer_orders.status: OPEN, IN_PRODUCTION, SHIPPED,
  DELIVERED
- mfg_production_orders.status: RELEASED, IN_PROCESS,
  QUALITY_HOLD, COMPLETED
- plant_id: PLANT_HAM (Plant 1 - Hamburg, automotive components),
  PLANT_GRZ (Plant 2 - Graz, power tools)
- line_id: L1..L5

## Example queries

Production orders on quality hold, with the affected customer
order:

```sql
SELECT p.prod_order_id, p.plant_id, p.line_id, p.product_id,
       p.hold_reason, c.order_id, c.account_id, c.qty,
       c.order_value_eur, c.requested_delivery
FROM mfg_production_orders p
JOIN mfg_customer_orders c ON c.order_id = p.order_id
WHERE p.status = 'QUALITY_HOLD';
```

Open order book by plant:

```sql
SELECT plant_id, status,
       COUNT(*)              AS orders,
       SUM(order_value_eur)  AS value_eur
FROM mfg_customer_orders
GROUP BY plant_id, status
ORDER BY plant_id, status;
```

All orders for one product (e.g. the CK-350 clutch kit):

```sql
SELECT order_id, account_id, qty, status, requested_delivery
FROM mfg_customer_orders
WHERE product_id = 'FG_CK350'
ORDER BY requested_delivery;
```
