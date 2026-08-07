# mfg_pdm reference: value domains and example queries

## Categorical value domains (exact values in the data)

- material_type: FINISHED_GOOD, COMPONENT
- division: POWER_TOOLS, AUTOMOTIVE, SHARED
- mfg_material_master.status: ACTIVE, OBSOLETE
- mfg_eco.status: RELEASED, CLOSED (no DRAFT rows in the data)
- change_type: COMPONENT_CHANGE, SPEC_CHANGE, DOC_CHANGE
- mfg_eco_distribution.status: ACKNOWLEDGED, PENDING

## Example queries

Unacknowledged engineering changes per plant (the distribution
gap):

```sql
SELECT d.eco_id, d.plant_id, d.plant_name, d.sent_at,
       e.title, e.effective_date
FROM mfg_eco_distribution d
JOIN mfg_eco e ON e.eco_id = d.eco_id
WHERE d.status = 'PENDING';
```

What a specific ECO changes and where it applies:

```sql
SELECT eco_id, title, change_type, affected_materials,
       released_date, effective_date, status
FROM mfg_eco
WHERE eco_id = 'ECO-2025-118';
```

Where-used for a component (BOM explosion upward):

```sql
SELECT b.parent_material_id, m.description, b.qty_per,
       b.valid_from, b.introduced_by_eco
FROM mfg_bom b
JOIN mfg_material_master m ON m.material_id = b.parent_material_id
WHERE b.component_material_id = 'MAT_CLT_HD22';
```

Obsolete components and their successors:

```sql
SELECT material_id, description, revision, superseded_by
FROM mfg_material_master
WHERE status = 'OBSOLETE';
```
