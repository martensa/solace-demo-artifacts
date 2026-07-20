# retail_pdm reference: value domains and example queries

## Value domains

- category_main (23): Alcohol, Bakery, Beverages, Bulk Foods,
  Condiments, Confectionery, Dairy, Dairy Alternatives,
  Energy Foods, Fresh Prepared, Gourmet, Grains, Health Foods,
  Meat, Pantry, Poultry, Prepared Foods, Produce, Protein Snacks,
  Seafood, Snacks, Sports Nutrition, Sweeteners
- department (46), e.g.: Fresh Produce, Fresh Meat, Fresh Seafood,
  Wine Cellar, Premium Liquor, Bulk Bins, Deli, Grab & Go,
  Health & Wellness, Sports Nutrition, Specialty Foods, ...
- inventory_status: Bulk Bin, Fresh, Fresh Daily, Fresh Limited,
  Fresh Smoked, In Stock, Limited, Limited Edition, Low Stock,
  Made to Order, Seasonal, Small Batch, Weekly Harvest
- seasonality: Year-Round, Seasonal, Holiday Peak, Feb-Apr,
  Jun-Sep, Mar-Oct, May-Sep, Nov-Mar, Oct-Jan, Oct-Mar, Sep-May,
  Sep-Nov
- unit_measure: bag, bar, bottle, bowl, box, bundle, carton,
  container, gallon, jar, kit, loaf, ounce, pack, package, pound,
  steak, tin, tube, wedge

## Example queries

Average price and margin per main category:

```sql
SELECT category_main,
       COUNT(*)                            AS products,
       AVG(unit_price::numeric)::numeric(10,2) AS avg_price,
       AVG(margin_percent)::numeric(10,1)  AS avg_margin_pct
FROM retail_product_master
GROUP BY category_main
ORDER BY avg_price DESC;
```

Low / constrained inventory:

```sql
SELECT product_id, product_name, category_main,
       stock_level, inventory_status
FROM retail_product_master
WHERE inventory_status IN ('Low Stock', 'Limited', 'Fresh Limited')
   OR stock_level < 20
ORDER BY stock_level ASC;
```

Suppliers with the most active products:

```sql
SELECT supplier_name,
       COUNT(*) AS products,
       COUNT(*) FILTER (WHERE organic) AS organic_products
FROM retail_product_master
GROUP BY supplier_name
ORDER BY products DESC
LIMIT 10;
```
