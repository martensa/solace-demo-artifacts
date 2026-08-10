--
-- PostgreSQL database dump
--

\restrict 4Z8poQwxKFVlZsNq8nc1fOAgyFAOMKGneLlMW6GfrYjJGCxRV5yAy9HguGPbAMd

-- Dumped from database version 18.3 (Debian 18.3-1.pgdg13+1)
-- Dumped by pg_dump version 18.3 (Debian 18.3-1.pgdg13+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

DROP TABLE IF EXISTS public.retail_customers;
SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: retail_customers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.retail_customers (
    customer_id text,
    customer_type text,
    loyalty_card text,
    membership_tier text,
    membership_since date,
    age_group text,
    estimated_income text,
    household_size integer,
    lifestyle text,
    city text,
    state text,
    region text,
    preference_organic boolean,
    preference_premium boolean,
    preference_local boolean,
    preference_health_conscious boolean,
    preference_sustainable boolean,
    preference_budget_conscious boolean,
    total_transactions integer,
    total_spend money,
    first_transaction_date date,
    last_transaction_date date
);


--
-- Data for Name: retail_customers; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.retail_customers (customer_id, customer_type, loyalty_card, membership_tier, membership_since, age_group, estimated_income, household_size, lifestyle, city, state, region, preference_organic, preference_premium, preference_local, preference_health_conscious, preference_sustainable, preference_budget_conscious, total_transactions, total_spend, first_transaction_date, last_transaction_date) FROM stdin;
CUST_847392156	LOYALTY_PREMIUM	FIFTH_PLATINUM_847392156	Platinum	2023-03-15	35-44	150000+	3	Urban Professional	New York	NY	Northeast	t	t	f	t	f	f	1	$366.86	2024-10-22	2024-10-22
CUST_992847531	VIP	VIP_DIAMOND_992847531	Diamond	2022-01-10	45-54	500000+	4	Luxury Consumer	Beverly Hills	CA	West Coast	t	t	f	f	f	f	1	$1,667.69	2024-10-22	2024-10-22
CUST_445566778	LOYALTY_STANDARD	COMMUNITY_SILVER_445566778	Silver	2023-08-22	28-35	65000-85000	2	Young Professional	Chicago	IL	Midwest	f	f	t	f	t	t	2	$90.81	2024-10-22	2024-10-22
CUST_887234901	TOURIST	\N	\N	\N	25-34	75000-100000	2	Health & Wellness Tourist	Miami Beach	FL	Southeast	t	f	f	t	f	f	1	$73.18	2024-10-22	2024-10-22
CUST_332156789	LOYALTY_STANDARD	PIKE_BRONZE_332156789	Bronze	2024-02-15	22-28	45000-65000	1	Urban Foodie	Seattle	WA	Pacific Northwest	f	f	t	f	f	f	1	$69.22	2024-10-22	2024-10-22
CUST_556677889	LOYALTY_PREMIUM	MIDTOWN_GOLD_556677889	Gold	2023-05-12	32-40	95000-125000	3	Health-Conscious Family	Atlanta	GA	Southeast	t	f	f	t	t	f	2	$116.46	2024-10-22	2024-10-22
CUST_223344556	STUDENT	STUDENT_DISCOUNT_223344556	Student	2024-09-01	18-22	15000-25000	1	College Student	Boston	MA	Northeast	f	f	f	t	f	t	2	$90.45	2024-10-22	2024-10-22
CUST_778899001	MEMBER_OWNER	COOP_OWNER_778899001	Owner	2022-06-20	28-35	75000-95000	2	Eco-Conscious Outdoors	Denver	CO	Mountain West	t	f	t	f	t	f	1	$71.89	2024-10-22	2024-10-22
CUST_998877665	SNOWBIRD	SEASONAL_SILVER_998877665	Seasonal	2023-11-15	65+	125000-175000	2	Seasonal Resident	Scottsdale	AZ	Southwest	f	t	f	t	f	f	1	$128.16	2024-10-22	2024-10-22
CUST_112233445	ENVIRONMENTAL_MEMBER	ECO_GREEN_112233445	Environmental	2023-04-03	30-38	85000-110000	3	Eco-Conscious Family	Portland	OR	Pacific Northwest	f	f	t	f	t	f	2	$750.19	2024-10-22	2024-10-22
CUST_667788990	TECH_PROFESSIONAL	TECH_PLUS_667788990	Tech Plus	2024-01-15	26-32	95000-135000	1	Tech Professional	Austin	TX	Southwest	f	f	t	f	f	f	2	$159.86	2024-10-22	2024-10-22
CUST_334455667	FAMILY_MEMBER	FAMILY_GOLD_334455667	Family Gold	2022-09-10	35-42	85000-115000	4	Health-Conscious Family	Minneapolis	MN	Midwest	t	f	t	f	f	f	1	$63.68	2024-10-22	2024-10-22
CUST_889900112	ARTIST	ARTS_SUPPORTER_889900112	Artist	2023-11-28	27-34	35000-55000	1	Creative Professional	Kansas City	MO	Midwest	f	f	t	f	f	t	1	$48.75	2024-10-22	2024-10-22
\.


--
-- PostgreSQL database dump complete
--

\unrestrict 4Z8poQwxKFVlZsNq8nc1fOAgyFAOMKGneLlMW6GfrYjJGCxRV5yAy9HguGPbAMd

