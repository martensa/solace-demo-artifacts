# mfg_scm reference: value domains and example queries

## Categorical value domains (exact values in the data)

- plant_id: PLANT_HAM, PLANT_GRZ
- mfg_suppliers.role: PRIMARY, ALTERNATE
- mfg_purchase_orders.status: CONFIRMED, IN_TRANSIT, DELIVERED

## Example queries

Stock position and planned cover for one material:

```sql
SELECT plant_id, on_hand_qty, safety_stock, reorder_point,
       planned_daily_consumption,
       ROUND(on_hand_qty::numeric
             / NULLIF(planned_daily_consumption, 0), 1)
         AS planned_days_cover
FROM mfg_inventory
WHERE material_id = 'MAT_CLT_HD22';
```

Sourcing options for a material (primary vs alternate):

```sql
SELECT supplier_id, supplier_name, role, lead_time_days,
       expedite_lead_time_days, qualified, unit_cost_eur,
       on_time_delivery_rate
FROM mfg_suppliers
WHERE material_id = 'MAT_CLT_HD22'
ORDER BY role;
```

Inbound supply (open POs) for a material:

```sql
SELECT po_id, supplier_id, plant_id, qty, eta, status
FROM mfg_purchase_orders
WHERE material_id = 'MAT_CLT_HD22'
  AND status IN ('CONFIRMED', 'IN_TRANSIT')
ORDER BY eta;
```

Materials below reorder point (plan view):

```sql
SELECT plant_id, material_id, description, on_hand_qty,
       reorder_point
FROM mfg_inventory
WHERE on_hand_qty < reorder_point;
```
