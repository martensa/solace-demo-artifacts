--
-- PostgreSQL database dump
--

\restrict dQA9TehAAvgOESuzA7s7vD1vjZzg1410PnhCor2aVBSaGTo9D7TwvuToEtIeZFZ

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

DROP TABLE IF EXISTS public.retail_product_master;
SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: retail_product_master; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.retail_product_master (
    product_id text,
    sku text,
    product_name text,
    category_main text,
    category_sub text,
    department text,
    brand text,
    supplier_id text,
    supplier_name text,
    unit_price money,
    cost_price money,
    unit_measure text,
    barcode text,
    organic boolean,
    local boolean,
    artisan boolean,
    luxury boolean,
    premium boolean,
    attributes text,
    stock_level integer,
    dimensions_cm text,
    weight_kg double precision,
    margin_percent double precision,
    inventory_status text,
    popularity_score double precision,
    seasonality text
);


--
-- Data for Name: retail_product_master; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.retail_product_master (product_id, sku, product_name, category_main, category_sub, department, brand, supplier_id, supplier_name, unit_price, cost_price, unit_measure, barcode, organic, local, artisan, luxury, premium, attributes, stock_level, dimensions_cm, weight_kg, margin_percent, inventory_status, popularity_score, seasonality) FROM stdin;
ITM_001	ORG_KALE_MASSAGE_200G	Organic Massaged Kale 200g	Produce	Leafy Greens	Fresh Foods	Urban Harvest	SUP_URBAN_HARVEST_001	Urban Harvest Co.	$5.99	$3.80	package	0123456789001	t	f	f	f	f	organic	245	20x15x5	0.2	36.6	In Stock	8.5	Year-Round
ITM_002	SMKD_SALMON_8OZ	Wild Alaskan Smoked Salmon 8oz	Seafood	Smoked Fish	Deli	Pacific Northwest	SUP_PACIFIC_NW_002	Pacific Northwest Seafood	$24.99	$16.00	package	0123456789002	f	f	f	f	t	premium	58	25x15x3	0.23	36	Low Stock	9.2	Year-Round
ITM_003	CHM_DOM_750ML	Dom Pérignon Vintage Champagne 750ml	Alcohol	Champagne	Liquor	Dom Pérignon	SUP_LUXURY_WINES_003	Luxury Wine Imports	$299.99	$210.00	bottle	0123456789003	f	f	f	t	f	luxury	42	30x10x10	1.65	30	In Stock	9.8	Holiday Peak
ITM_004	TRF_WHITE_1OZ	White Alba Truffle 1oz	Gourmet	Truffles	Specialty Foods	Piedmont Delicacies	SUP_PIEDMONT_004	Piedmont Italian Imports	$189.99	$135.00	ounce	0123456789004	f	f	f	t	f	luxury,imported	15	10x10x5	0.03	28.9	Limited	9.5	Oct-Jan
ITM_005	CAV_BELUGA_50G	Beluga Caviar 50g	Gourmet	Caviar	Specialty Foods	Imperial Sturgeon	SUP_IMPERIAL_005	Imperial Caviar House	$449.99	$320.00	tin	0123456789005	f	f	f	t	f	luxury,imported	28	15x10x5	0.05	28.9	In Stock	9.7	Holiday Peak
ITM_006	WIN_OPUS_750ML	Opus One Napa Valley 2019	Alcohol	Premium Wine	Wine Cellar	Opus One	SUP_OPUS_ONE_006	Opus One Winery	$425.00	$300.00	bottle	0123456789006	f	f	f	t	f	luxury,vintage	67	30x10x10	1.5	29.4	In Stock	9.4	Year-Round
ITM_007	LOC_MILK_1GAL	Local Organic Whole Milk 1 Gallon	Dairy	Milk	Refrigerated	Prairie Farm Organic	SUP_PRAIRIE_FARM_007	Prairie Farm Dairy	$6.99	$4.50	gallon	0123456789007	t	t	f	f	f	organic,local	385	25x15x30	3.88	35.6	In Stock	8.8	Year-Round
ITM_008	BRD_ARTISAN_SOURD	Artisan Sourdough Bread	Bakery	Artisan Bread	Fresh Bakery	Chicago Bread Works	SUP_CHI_BREAD_008	Chicago Bread Works	$4.99	$2.80	loaf	0123456789008	f	t	t	f	f	local,artisan	156	35x12x10	0.9	43.9	Fresh Daily	9	Year-Round
ITM_009	COF_CHI_ROAST_12OZ	Chicago Dark Roast Coffee 12oz	Beverages	Coffee	Grocery	Windy City Roasters	SUP_WINDY_ROAST_009	Windy City Coffee Roasters	$12.99	$8.00	bag	0123456789009	f	t	f	f	f	local,fair_trade	234	20x10x8	0.34	38.4	In Stock	8.7	Year-Round
ITM_010	SMT_ACAI_16OZ	Tropical Acai Smoothie Bowl 16oz	Fresh Prepared	Smoothie Bowls	Prepared Foods	Beach Bowl Co	SUP_BEACH_BOWL_010	Beach Bowl Company	$14.99	$8.50	bowl	0123456789010	t	f	f	f	f	organic,fresh_made	0	15x15x8	0.45	43.3	Made to Order	9.1	Year-Round
ITM_011	JUI_GRNS_20OZ	Cold-Pressed Green Juice 20oz	Beverages	Fresh Juice	Refrigerated	Miami Green	SUP_MIAMI_GREEN_011	Miami Green Juice Co	$8.99	$5.50	bottle	0123456789011	t	f	f	f	f	organic,cold_pressed	145	8x8x20	0.6	38.8	In Stock	8.9	Year-Round
ITM_012	SNK_CHIA_BAR	Coconut Chia Energy Bar	Health Foods	Energy Bars	Health & Wellness	Tropical Fuel	SUP_TROPICAL_FUEL_012	Tropical Fuel Foods	$3.49	$2.10	bar	0123456789012	t	f	f	f	f	organic,vegan	567	12x5x2	0.08	39.8	In Stock	8.3	Year-Round
ITM_013	COF_PIKE_12OZ	Pike Place Signature Roast 12oz	Beverages	Artisan Coffee	Specialty Beverages	Pike Roasters	SUP_PIKE_ROAST_013	Pike Place Roasters	$16.99	$10.50	bag	0123456789013	f	t	f	f	f	local,small_batch	187	20x10x8	0.34	38.2	In Stock	9.2	Year-Round
ITM_014	CHZ_BEECHER_8OZ	Beecher's Flagship Cheese 8oz	Dairy	Artisan Cheese	Specialty Dairy	Beecher's	SUP_BEECHERS_014	Beecher's Handmade Cheese	$12.99	$8.00	wedge	0123456789014	f	t	t	f	f	local,artisan	94	15x10x5	0.23	38.4	In Stock	9	Year-Round
ITM_015	FIS_SALMON_1LB	Wild Pacific Salmon Fillet 1lb	Seafood	Fresh Fish	Fresh Seafood	Pacific Catch	SUP_PACIFIC_CATCH_015	Pacific Northwest Fisheries	$18.99	$12.50	pound	0123456789015	f	f	f	f	f	wild_caught,sustainable	78	30x15x3	0.45	34.2	Fresh Daily	9.3	May-Sep
ITM_016	CHK_ORG_FREERANGE_3LB	Organic Free-Range Chicken 3lbs	Poultry	Organic Chicken	Fresh Meat	Georgia Organic Farms	SUP_GA_ORGANIC_016	Georgia Organic Farms	$16.99	$11.50	package	0123456789016	t	f	f	f	f	organic,free_range	124	30x20x8	1.36	32.3	Fresh	8.8	Year-Round
ITM_017	VEG_KALE_BUNDLE	Organic Kale Bundle	Produce	Leafy Greens	Fresh Produce	Southern Greens Co	SUP_SOUTHERN_GREENS_017	Southern Greens Company	$4.99	$3.00	bundle	0123456789017	t	t	f	f	f	organic,local	298	25x15x10	0.3	39.9	In Stock	8.6	Year-Round
ITM_018	BRD_GF_WHOLE_GRAIN	Gluten-Free Whole Grain Bread	Bakery	Specialty Bread	Specialty Bakery	Atlanta Gluten Free	SUP_ATL_GF_018	Atlanta Gluten Free Bakery	$7.99	$5.00	loaf	0123456789018	f	f	f	f	f	gluten_free,whole_grain	156	35x12x10	0.6	37.4	In Stock	8.4	Year-Round
ITM_019	YOG_GRK_ORG_32OZ	Organic Greek Yogurt 32oz	Dairy	Yogurt	Refrigerated Dairy	Mountain High Organic	SUP_MOUNTAIN_HIGH_019	Mountain High Dairy	$6.99	$4.20	container	0123456789019	t	f	f	f	f	organic,probiotic	267	15x10x12	0.9	39.9	In Stock	8.9	Year-Round
ITM_020	RMN_CUP_VARIETY_6PK	Gourmet Ramen Cup Variety 6-Pack	Pantry	Instant Meals	Packaged Foods	Campus Kitchen	SUP_CAMPUS_KITCHEN_020	Campus Kitchen Foods	$8.99	$5.40	pack	0123456789020	f	f	f	f	f	student_friendly,quick_prep	345	25x20x15	0.6	39.9	In Stock	7.8	Sep-May
ITM_021	ENR_DRK_STUDY_4PK	Study Focus Energy Drink 4-Pack	Beverages	Energy Drinks	Refrigerated Beverages	Brain Boost	SUP_BRAIN_BOOST_021	Brain Boost Beverages	$7.99	$4.80	pack	0123456789021	f	f	f	f	f	caffeine,student_focused	234	20x15x20	1.6	39.9	In Stock	7.9	Sep-May
ITM_022	SNK_TRL_STUDY_8OZ	Study Trail Mix 8oz	Snacks	Trail Mix	Packaged Snacks	Scholar Snacks	SUP_SCHOLAR_SNACKS_022	Scholar Snacks Company	$4.99	$3.00	bag	0123456789022	f	f	f	f	f	brain_food,nuts_seeds	456	20x12x5	0.23	39.9	In Stock	8.2	Year-Round
ITM_023	TRL_ALPINE_BULK_1LB	Alpine Trail Mix Bulk 1lb	Bulk Foods	Trail Mix	Bulk Bins	Bulk Bin	SUP_ROCKY_MTN_BULK_023	Rocky Mountain Bulk Foods	$12.99	$7.80	pound	BULK_WEIGHED_023	t	f	f	f	f	organic,bulk	800	Bulk Bin	0.45	40	Bulk Bin	8.5	Year-Round
ITM_024	QNO_COL_ORG_2LB	Colorado Organic Quinoa 2lbs	Grains	Ancient Grains	Bulk Grains	Colorado Quinoa Company	SUP_CO_QUINOA_024	Colorado Quinoa Company	$14.99	$9.50	bag	0123456789024	t	t	f	f	f	organic,local	178	25x15x8	0.91	36.6	In Stock	8.7	Year-Round
ITM_025	HNY_WILDFLR_LOC_16OZ	Colorado Wildflower Honey 16oz	Sweeteners	Raw Honey	Natural Sweeteners	Rocky Mountain Apiaries	SUP_RM_APIARIES_025	Rocky Mountain Apiaries	$11.99	$7.20	jar	0123456789025	f	t	f	f	f	raw,local	123	12x8x12	0.68	39.9	In Stock	8.8	Jun-Sep
ITM_026	CAC_PAD_FRESH_2LB	Fresh Prickly Pear Cactus Pads 2lbs	Produce	Desert Vegetables	Specialty Produce	Sonoran Harvest	SUP_SONORAN_026	Sonoran Desert Farms	$8.99	$5.40	container	0123456789026	f	t	f	f	f	desert_native,local	67	25x20x5	0.91	39.9	Seasonal	7.5	Mar-Oct
ITM_027	TEQ_AGAVE_PREMIUM_750ML	Premium Agave Tequila 750ml	Alcohol	Premium Spirits	Liquor	Casa Azul	SUP_CASA_AZUL_027	Casa Azul Imports	$89.99	$62.00	bottle	0123456789027	f	f	f	f	t	premium,imported	89	30x10x10	1.65	31.1	In Stock	9	Year-Round
ITM_028	SAL_HOT_DESERT_8OZ	Desert Heat Gourmet Salsa 8oz	Condiments	Artisan Salsa	Specialty Foods	Desert Fire Foods	SUP_DESERT_FIRE_028	Desert Fire Foods	$6.99	$4.20	jar	0123456789028	f	t	t	f	f	artisan,local	234	10x8x8	0.23	39.9	In Stock	8.3	Year-Round
ITM_029	MLK_OAT_PORTLAND_32OZ	Portland Oat Milk 32oz	Dairy Alternatives	Plant Milk	Refrigerated Alternatives	Portland Oat Co	SUP_PDX_OAT_029	Portland Oat Company	$5.99	$3.60	carton	0123456789029	f	t	f	f	f	plant_based,local	312	20x10x25	1	39.9	In Stock	8.9	Year-Round
ITM_030	BRD_GRAIN_ZERO_WASTE	Zero-Waste Multigrain Bread	Bakery	Sustainable Bread	Eco Bakery	Sustainable Bakehouse	SUP_SUSTAIN_BAKE_030	Sustainable Bakehouse	$6.99	$4.20	loaf	0123456789030	f	t	f	f	f	zero_waste,local	145	35x12x10	0.6	39.9	Fresh Daily	8.4	Year-Round
ITM_031	VEG_BOX_SEASONAL_5LB	Seasonal Vegetable Box 5lbs	Produce	Vegetable Boxes	Farm Share	Hawthorne Urban Farm	SUP_HAWTHORNE_FARM_031	Hawthorne Urban Farm	$24.99	$15.00	box	FARM_SHARE_031	t	t	f	f	f	organic,local	45	40x30x15	2.27	40	Weekly Harvest	9.1	Seasonal
ITM_032	BBQ_BRSKT_READY_1LB	Austin BBQ Brisket Ready-to-Eat 1lb	Prepared Foods	BBQ Meats	Hot Foods	Franklin's Choice	SUP_FRANKLINS_032	Franklin's BBQ Foods	$18.99	$12.50	container	0123456789032	f	t	t	f	f	local,artisan	0	20x15x8	0.45	34.2	Made to Order	9.3	Year-Round
ITM_033	BER_IPA_CRAFT_6PK	Austin Craft IPA 6-Pack	Alcohol	Craft Beer	Beer & Wine	Lone Star Brewing	SUP_LONE_STAR_033	Lone Star Craft Brewing	$12.99	$8.50	pack	0123456789033	f	t	f	f	f	local,craft	234	25x15x20	2.16	34.6	In Stock	8.8	Year-Round
ITM_034	SAL_VERDE_HOT_12OZ	Austin Hot Salsa Verde 12oz	Condiments	Local Salsas	Specialty Condiments	Keep Austin Hot	SUP_KEEP_HOT_034	Keep Austin Hot Foods	$5.99	$3.60	jar	0123456789034	f	t	f	f	f	local,spicy	345	10x8x10	0.34	39.9	In Stock	8.2	Year-Round
ITM_035	WLD_RICE_MN_2LB	Minnesota Wild Rice 2lbs	Grains	Native Grains	Local Grains	Northwoods Harvest	SUP_NORTHWOODS_035	Northwoods Wild Foods	$16.99	$10.20	bag	0123456789035	f	t	f	f	f	native,local	98	25x15x8	0.91	40	In Stock	8.6	Sep-Nov
ITM_036	MPL_SYR_ORG_16OZ	Organic Maple Syrup 16oz	Sweeteners	Maple Products	Natural Sweeteners	Northland Maple	SUP_NORTHLAND_036	Northland Maple Co	$12.99	$7.80	bottle	0123456789036	t	t	f	f	f	organic,local	156	10x8x20	0.68	40	In Stock	9	Feb-Apr
ITM_037	CHZ_CURD_WI_12OZ	Wisconsin Cheese Curds 12oz	Dairy	Specialty Cheese	Regional Dairy	Wisconsin Creamery	SUP_WI_CREAMERY_037	Wisconsin Artisan Creamery	$8.99	$5.40	bag	0123456789037	f	f	t	f	f	artisan,regional	187	15x12x5	0.34	39.9	Fresh	8.9	Year-Round
ITM_038	BCN_SMKD_TN_1LB	Tennessee Smoked Bacon 1lb	Meat	Smoked Meats	Specialty Meats	Music City Smokehouse	SUP_MUSIC_SMOKE_038	Music City Smokehouse	$13.99	$9.50	package	0123456789038	f	t	t	f	f	local,artisan	123	25x15x3	0.45	32.1	Fresh Smoked	9.1	Year-Round
ITM_039	GRTS_STONE_32OZ	Stone-Ground White Grits 32oz	Grains	Southern Grains	Regional Specialties	Tennessee Mill Co	SUP_TN_MILL_039	Tennessee Stone Mill Company	$7.99	$4.80	bag	0123456789039	f	t	f	f	f	traditional,local	234	20x15x8	0.91	39.9	In Stock	8.3	Year-Round
ITM_040	WSK_HONEY_TN_375ML	Tennessee Honey Whiskey 375ml	Alcohol	Regional Spirits	Premium Liquor	Jack Daniel's	SUP_JACK_DANIELS_040	Jack Daniel's Distillery	$19.99	$14.00	bottle	0123456789040	f	t	f	f	t	local,premium	178	25x8x8	0.8	30	In Stock	9.2	Year-Round
ITM_041	SAL_KIT_FAMILY_4SRV	Family Salad Kit 4 Servings	Prepared Foods	Meal Kits	Ready-to-Eat	Fresh Family	SUP_FRESH_FAMILY_041	Fresh Family Foods	$9.99	$6.00	kit	0123456789041	f	f	f	f	f	family_size,healthy	89	30x25x10	1.2	39.9	Fresh Daily	8.6	Year-Round
ITM_042	YOG_PARFAIT_BERRY_12OZ	Mixed Berry Yogurt Parfait 12oz	Prepared Foods	Breakfast Items	Grab & Go	Morning Fresh	SUP_MORNING_FRESH_042	Morning Fresh Foods	$4.99	$3.00	container	0123456789042	f	f	f	f	f	healthy,protein	0	12x12x8	0.34	39.9	Made to Order	8.7	Year-Round
ITM_043	TEA_GREEN_IMMUNE_20BAG	Immune Support Green Tea 20 Bags	Beverages	Wellness Teas	Health & Wellness	Wellness Garden	SUP_WELLNESS_GARDEN_043	Wellness Garden Teas	$6.99	$4.20	box	0123456789043	f	f	f	f	f	wellness,herbal	287	15x10x5	0.2	39.9	In Stock	8.5	Oct-Mar
ITM_044	STK_WAGYU_A5_8OZ	Japanese A5 Wagyu Steak 8oz	Meat	Premium Beef	Luxury Meats	Tokyo Premium	SUP_TOKYO_PREMIUM_044	Tokyo Premium Meats	$149.99	$105.00	steak	0123456789044	f	f	f	t	f	luxury,imported	23	25x20x3	0.23	30	Limited	9.6	Year-Round
ITM_045	CHM_KRUG_750ML	Krug Grande Cuvée Champagne 750ml	Alcohol	Luxury Champagne	Premium Wine	Krug	SUP_LUXURY_CHAMPAGNE_045	Luxury Champagne Imports	$189.99	$135.00	bottle	0123456789045	f	f	f	t	f	luxury,imported	34	30x10x10	1.65	28.9	In Stock	9.5	Holiday Peak
ITM_046	TRF_BLK_SHAVED_1OZ	Shaved Black Truffle 1oz	Gourmet	Fresh Truffles	Specialty Items	Périgord Treasures	SUP_PERIGORD_046	Périgord Gourmet Imports	$159.99	$115.00	container	0123456789046	f	f	f	t	f	luxury,imported	18	10x10x5	0.03	28.1	Fresh Limited	9.4	Nov-Mar
ITM_047	BAR_CLIFF_VAR_12PK	Clif Bar Variety Pack 12ct	Energy Foods	Energy Bars	Sports Nutrition	Clif Bar	SUP_CLIF_BAR_047	Clif Bar & Company	$18.99	$11.40	box	0123456789047	f	f	f	f	f	high_protein,outdoor	412	25x20x10	1.44	40	In Stock	8.8	Year-Round
ITM_048	ELT_TABS_SPORT_20CT	Electrolyte Tablets Sport 20ct	Sports Nutrition	Hydration	Performance	Nuun	SUP_NUUN_048	Nuun Hydration	$7.99	$4.80	tube	0123456789048	f	f	f	f	f	electrolytes,endurance	523	5x5x15	0.24	39.9	In Stock	8.6	Year-Round
ITM_049	JRK_BEEF_HIGH_PROT_3OZ	High-Protein Beef Jerky 3oz	Protein Snacks	Jerky	High-Protein Foods	Mountain Peak	SUP_MOUNTAIN_PEAK_049	Mountain Peak Foods	$8.99	$5.40	package	0123456789049	f	f	f	f	f	high_protein,portable	634	15x10x2	0.09	39.9	In Stock	8.7	Year-Round
ITM_050	COF_KC_ART_ROAST_8OZ	KC Arts Roast Coffee 8oz	Beverages	Local Coffee	Artisan Beverages	Crossroads Coffee	SUP_CROSSROADS_050	Crossroads Coffee Collective	$9.99	$6.00	bag	0123456789050	f	t	f	f	f	local,artist_collaboration	98	20x10x8	0.23	39.9	Limited Edition	8.4	Year-Round
ITM_051	CHC_ARTISAN_BAR_3OZ	Local Artisan Chocolate Bar 3oz	Confectionery	Artisan Chocolate	Local Arts	KC Chocolate Works	SUP_KC_CHOCOLATE_051	Kansas City Chocolate Works	$6.99	$4.20	bar	0123456789051	f	t	t	f	f	artisan,local	245	15x8x2	0.09	39.9	Small Batch	8.5	Year-Round
ITM_052	BRD_RUSTIC_ARTS_LOAF	Rustic Arts District Bread	Bakery	Artisan Bread	Local Bakery	District Bakehouse	SUP_DISTRICT_BAKE_052	Arts District Bakehouse	$5.99	$3.60	loaf	0123456789052	f	t	t	f	f	artisan,local	178	35x12x10	0.6	39.9	Fresh Daily	8.6	Year-Round
\.


--
-- PostgreSQL database dump complete
--

\unrestrict dQA9TehAAvgOESuzA7s7vD1vjZzg1410PnhCor2aVBSaGTo9D7TwvuToEtIeZFZ

