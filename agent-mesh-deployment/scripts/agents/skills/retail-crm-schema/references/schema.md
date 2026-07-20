# retail_crm reference: value domains and example queries

## Categorical value domains (exact values in the data)

- customer_type: ARTIST, ENVIRONMENTAL_MEMBER, FAMILY_MEMBER,
  LOYALTY_PREMIUM, LOYALTY_STANDARD, MEMBER_OWNER, SNOWBIRD,
  STUDENT, TECH_PROFESSIONAL, TOURIST, VIP
- membership_tier: Artist, Bronze, Diamond, Environmental,
  Family Gold, Gold, Owner, Platinum, Seasonal, Silver, Student,
  Tech Plus
- region: Midwest, Mountain West, Northeast, Pacific Northwest,
  Southeast, Southwest, West Coast
- lifestyle: College Student, Creative Professional,
  Eco-Conscious Family, Eco-Conscious Outdoors,
  Health-Conscious Family, Health & Wellness Tourist,
  Luxury Consumer, Seasonal Resident, Tech Professional,
  Urban Foodie, Urban Professional, Young Professional
- age_group (text ranges): 18-22, 22-28, 25-34, 26-32, 27-34,
  28-35, 30-38, 32-40, 35-42, 35-44, 45-54, 65+
- estimated_income (text ranges): 15000-25000, 35000-55000,
  45000-65000, 65000-85000, 75000-95000, 75000-100000,
  85000-110000, 85000-115000, 95000-125000, 95000-135000,
  125000-175000, 150000+, 500000+

## Example queries

Top customers by lifetime spend:

```sql
SELECT customer_id, customer_type, membership_tier,
       total_spend::numeric AS lifetime_spend
FROM retail_customers
ORDER BY total_spend::numeric DESC
LIMIT 10;
```

Preference profile per region:

```sql
SELECT region,
       COUNT(*)                                   AS customers,
       COUNT(*) FILTER (WHERE preference_organic) AS organic,
       COUNT(*) FILTER (WHERE preference_premium) AS premium,
       COUNT(*) FILTER (WHERE preference_budget_conscious) AS budget
FROM retail_customers
GROUP BY region
ORDER BY customers DESC;
```

Average spend by membership tier:

```sql
SELECT membership_tier,
       COUNT(*)                          AS customers,
       AVG(total_spend::numeric)::int    AS avg_spend,
       AVG(total_transactions)::numeric(10,1) AS avg_txns
FROM retail_customers
GROUP BY membership_tier
ORDER BY avg_spend DESC;
```
