# mfg_crm reference: value domains and example queries

## Categorical value domains (exact values in the data)

- account_type: OEM, DISTRIBUTOR, MRO
- tier: Strategic, Key, Standard
- region: EMEA, AMER, APAC
- industry: Automotive OEM, Commercial Vehicles, Tool Wholesale,
  Tool Retail, Construction Supply, Industrial Maintenance,
  Automotive Aftermarket

## Example queries

OEM accounts ranked by line-down penalty exposure:

```sql
SELECT account_id, account_name, tier,
       line_down_penalty_eur_per_hour
FROM mfg_accounts
WHERE line_down_penalty_eur_per_hour IS NOT NULL
ORDER BY line_down_penalty_eur_per_hour DESC;
```

Revenue by region and account type:

```sql
SELECT region, account_type,
       COUNT(*)                    AS accounts,
       SUM(annual_revenue_eur)     AS revenue_eur
FROM mfg_accounts
GROUP BY region, account_type
ORDER BY revenue_eur DESC;
```

Accounts with open quality claims:

```sql
SELECT account_id, account_name, account_type, open_claims
FROM mfg_accounts
WHERE open_claims > 0
ORDER BY open_claims DESC;
```
