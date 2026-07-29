// POSLOG seed for the SAM meetup demo (matches retail_pdm/oms/crm)
db = db.getSiblingDB('retail_pos');

// Read-only user for the SAM MongoDB connector (demo credentials)
db.createUser({
  user: 'sam_ro',
  pwd: 'sam_ro',
  roles: [ { role: 'read', db: 'retail_pos' } ]
});

db.poslog_transactions.drop();
db.poslog_transactions.insertMany(
[
 {
  "transaction_id": "POS-20241018-NYC-0029",
  "store_id": "STR_NYC_MANHATTAN_001",
  "store_name": "Fifth Avenue Fresh Market",
  "terminal_id": "T-06",
  "operator_id": "OP-746",
  "business_date": "2024-10-18",
  "ts": {
   "$date": "2024-10-18T07:04:03Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 3,
    "unit_price": 16.99,
    "extended_price": 50.97
   }
  ],
  "tender": {
   "type": "DEBIT_CARD",
   "amount": 55.3
  },
  "subtotal": 50.97,
  "tax": 4.33,
  "total": 55.3,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241020-SEA-0046",
  "store_id": "STR_SEA_PIKE_005",
  "store_name": "Pike Place Artisan Foods",
  "terminal_id": "T-06",
  "operator_id": "OP-252",
  "business_date": "2024-10-20",
  "ts": {
   "$date": "2024-10-20T08:04:34Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 2,
    "unit_price": 16.99,
    "extended_price": 33.98
   }
  ],
  "tender": {
   "type": "CREDIT_CARD",
   "amount": 36.87
  },
  "subtotal": 33.98,
  "tax": 2.89,
  "total": 36.87,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241018-LV-0034",
  "store_id": "STR_LV_SUMMERLIN_015",
  "store_name": "Summerlin Gourmet Oasis",
  "terminal_id": "T-01",
  "operator_id": "OP-871",
  "business_date": "2024-10-18",
  "ts": {
   "$date": "2024-10-18T20:00:54Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 3,
    "unit_price": 16.99,
    "extended_price": 50.97
   },
   {
    "product_id": "ITM_023",
    "sku": "TRL_ALPINE_BULK_1LB",
    "description": "Alpine Trail Mix Bulk 1lb",
    "qty": 2.5,
    "unit_price": 12.99,
    "extended_price": 32.48
   }
  ],
  "tender": {
   "type": "DEBIT_CARD",
   "amount": 90.54
  },
  "subtotal": 83.45,
  "tax": 7.09,
  "total": 90.54,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241022-DEN-0063",
  "store_id": "STR_DEN_CAPITOL_008",
  "store_name": "Capitol Hill Whole Foods Coop",
  "terminal_id": "T-05",
  "operator_id": "OP-934",
  "business_date": "2024-10-22",
  "ts": {
   "$date": "2024-10-22T21:28:46Z"
  },
  "customer_id": "CUST_332156789",
  "loyalty_scanned": true,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 3,
    "unit_price": 16.99,
    "extended_price": 50.97
   }
  ],
  "tender": {
   "type": "MOBILE_PAY",
   "amount": 55.3
  },
  "subtotal": 50.97,
  "tax": 4.33,
  "total": 55.3,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241021-MIA-0002",
  "store_id": "STR_MIA_SOUTHBEACH_004",
  "store_name": "South Beach Organic Market",
  "terminal_id": "T-06",
  "operator_id": "OP-381",
  "business_date": "2024-10-21",
  "ts": {
   "$date": "2024-10-21T12:41:15Z"
  },
  "customer_id": "CUST_887234901",
  "loyalty_scanned": true,
  "lines": [
   {
    "product_id": "ITM_010",
    "sku": "SMT_ACAI_16OZ",
    "description": "Tropical Acai Smoothie Bowl 16oz",
    "qty": 2,
    "unit_price": 14.99,
    "extended_price": 29.98
   }
  ],
  "tender": {
   "type": "CREDIT_CARD",
   "amount": 32.53
  },
  "subtotal": 29.98,
  "tax": 2.55,
  "total": 32.53,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241018-SEA-0053",
  "store_id": "STR_SEA_PIKE_005",
  "store_name": "Pike Place Artisan Foods",
  "terminal_id": "T-04",
  "operator_id": "OP-720",
  "business_date": "2024-10-18",
  "ts": {
   "$date": "2024-10-18T19:20:32Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 3,
    "unit_price": 16.99,
    "extended_price": 50.97
   }
  ],
  "tender": {
   "type": "CREDIT_CARD",
   "amount": 55.3
  },
  "subtotal": 50.97,
  "tax": 4.33,
  "total": 55.3,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241019-LV-0071",
  "store_id": "STR_LV_SUMMERLIN_015",
  "store_name": "Summerlin Gourmet Oasis",
  "terminal_id": "T-04",
  "operator_id": "OP-434",
  "business_date": "2024-10-19",
  "ts": {
   "$date": "2024-10-19T12:13:21Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   }
  ],
  "tender": {
   "type": "MOBILE_PAY",
   "amount": 18.43
  },
  "subtotal": 16.99,
  "tax": 1.44,
  "total": 18.43,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241018-LA-0059",
  "store_id": "STR_LA_BEVHILLS_002",
  "store_name": "Beverly Hills Gourmet",
  "terminal_id": "T-03",
  "operator_id": "OP-330",
  "business_date": "2024-10-18",
  "ts": {
   "$date": "2024-10-18T10:43:51Z"
  },
  "customer_id": "CUST_332156789",
  "loyalty_scanned": true,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 3,
    "unit_price": 16.99,
    "extended_price": 50.97
   },
   {
    "product_id": "ITM_023",
    "sku": "TRL_ALPINE_BULK_1LB",
    "description": "Alpine Trail Mix Bulk 1lb",
    "qty": 2.4,
    "unit_price": 12.99,
    "extended_price": 31.18
   }
  ],
  "tender": {
   "type": "DEBIT_CARD",
   "amount": 89.13
  },
  "subtotal": 82.15,
  "tax": 6.98,
  "total": 89.13,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241022-LV-0006",
  "store_id": "STR_LV_SUMMERLIN_015",
  "store_name": "Summerlin Gourmet Oasis",
  "terminal_id": "T-04",
  "operator_id": "OP-132",
  "business_date": "2024-10-22",
  "ts": {
   "$date": "2024-10-22T14:12:01Z"
  },
  "customer_id": "CUST_112233445",
  "loyalty_scanned": true,
  "lines": [
   {
    "product_id": "ITM_046",
    "sku": "TRF_BLK_SHAVED_1OZ",
    "description": "Shaved Black Truffle 1oz",
    "qty": 1,
    "unit_price": 159.99,
    "extended_price": 159.99
   }
  ],
  "tender": {
   "type": "CREDIT_CARD",
   "amount": 173.59
  },
  "subtotal": 159.99,
  "tax": 13.6,
  "total": 173.59,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241022-NYC-0058",
  "store_id": "STR_NYC_MANHATTAN_001",
  "store_name": "Fifth Avenue Fresh Market",
  "terminal_id": "T-05",
  "operator_id": "OP-584",
  "business_date": "2024-10-22",
  "ts": {
   "$date": "2024-10-22T17:13:50Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   }
  ],
  "tender": {
   "type": "DEBIT_CARD",
   "amount": 18.43
  },
  "subtotal": 16.99,
  "tax": 1.44,
  "total": 18.43,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241022-SEA-0074",
  "store_id": "STR_SEA_PIKE_005",
  "store_name": "Pike Place Artisan Foods",
  "terminal_id": "T-05",
  "operator_id": "OP-865",
  "business_date": "2024-10-22",
  "ts": {
   "$date": "2024-10-22T09:38:45Z"
  },
  "customer_id": "CUST_332156789",
  "loyalty_scanned": true,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 2,
    "unit_price": 16.99,
    "extended_price": 33.98
   }
  ],
  "tender": {
   "type": "CREDIT_CARD",
   "amount": 36.87
  },
  "subtotal": 33.98,
  "tax": 2.89,
  "total": 36.87,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241020-SEA-0017",
  "store_id": "STR_SEA_PIKE_005",
  "store_name": "Pike Place Artisan Foods",
  "terminal_id": "T-06",
  "operator_id": "OP-763",
  "business_date": "2024-10-20",
  "ts": {
   "$date": "2024-10-20T11:44:04Z"
  },
  "customer_id": "CUST_332156789",
  "loyalty_scanned": true,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   }
  ],
  "tender": {
   "type": "DEBIT_CARD",
   "amount": 18.43
  },
  "subtotal": 16.99,
  "tax": 1.44,
  "total": 18.43,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241019-DEN-0062",
  "store_id": "STR_DEN_CAPITOL_008",
  "store_name": "Capitol Hill Whole Foods Coop",
  "terminal_id": "T-01",
  "operator_id": "OP-567",
  "business_date": "2024-10-19",
  "ts": {
   "$date": "2024-10-19T21:54:08Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 2,
    "unit_price": 16.99,
    "extended_price": 33.98
   }
  ],
  "tender": {
   "type": "MOBILE_PAY",
   "amount": 36.87
  },
  "subtotal": 33.98,
  "tax": 2.89,
  "total": 36.87,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241021-SEA-0041",
  "store_id": "STR_SEA_PIKE_005",
  "store_name": "Pike Place Artisan Foods",
  "terminal_id": "T-01",
  "operator_id": "OP-109",
  "business_date": "2024-10-21",
  "ts": {
   "$date": "2024-10-21T19:59:29Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   }
  ],
  "tender": {
   "type": "CREDIT_CARD",
   "amount": 18.43
  },
  "subtotal": 16.99,
  "tax": 1.44,
  "total": 18.43,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241021-LA-0013",
  "store_id": "STR_LA_BEVHILLS_002",
  "store_name": "Beverly Hills Gourmet",
  "terminal_id": "T-03",
  "operator_id": "OP-718",
  "business_date": "2024-10-21",
  "ts": {
   "$date": "2024-10-21T17:08:16Z"
  },
  "customer_id": "CUST_992847531",
  "loyalty_scanned": true,
  "lines": [
   {
    "product_id": "ITM_006",
    "sku": "WIN_OPUS_750ML",
    "description": "Opus One Napa Valley 2019",
    "qty": 2,
    "unit_price": 425.0,
    "extended_price": 850.0
   }
  ],
  "tender": {
   "type": "CREDIT_CARD",
   "amount": 922.25
  },
  "subtotal": 850.0,
  "tax": 72.25,
  "total": 922.25,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241022-NYC-0031",
  "store_id": "STR_NYC_MANHATTAN_001",
  "store_name": "Fifth Avenue Fresh Market",
  "terminal_id": "T-02",
  "operator_id": "OP-196",
  "business_date": "2024-10-22",
  "ts": {
   "$date": "2024-10-22T19:26:06Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 2,
    "unit_price": 16.99,
    "extended_price": 33.98
   }
  ],
  "tender": {
   "type": "MOBILE_PAY",
   "amount": 36.87
  },
  "subtotal": 33.98,
  "tax": 2.89,
  "total": 36.87,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241021-LA-0036",
  "store_id": "STR_LA_BEVHILLS_002",
  "store_name": "Beverly Hills Gourmet",
  "terminal_id": "T-05",
  "operator_id": "OP-777",
  "business_date": "2024-10-21",
  "ts": {
   "$date": "2024-10-21T18:50:45Z"
  },
  "customer_id": "CUST_332156789",
  "loyalty_scanned": true,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 2,
    "unit_price": 16.99,
    "extended_price": 33.98
   }
  ],
  "tender": {
   "type": "MOBILE_PAY",
   "amount": 36.87
  },
  "subtotal": 33.98,
  "tax": 2.89,
  "total": 36.87,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241020-SEA-0048",
  "store_id": "STR_SEA_PIKE_005",
  "store_name": "Pike Place Artisan Foods",
  "terminal_id": "T-04",
  "operator_id": "OP-735",
  "business_date": "2024-10-20",
  "ts": {
   "$date": "2024-10-20T15:56:47Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   }
  ],
  "tender": {
   "type": "DEBIT_CARD",
   "amount": 18.43
  },
  "subtotal": 16.99,
  "tax": 1.44,
  "total": 18.43,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241019-NYC-0057",
  "store_id": "STR_NYC_MANHATTAN_001",
  "store_name": "Fifth Avenue Fresh Market",
  "terminal_id": "T-03",
  "operator_id": "OP-393",
  "business_date": "2024-10-19",
  "ts": {
   "$date": "2024-10-19T20:00:13Z"
  },
  "customer_id": "CUST_332156789",
  "loyalty_scanned": true,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 3,
    "unit_price": 16.99,
    "extended_price": 50.97
   }
  ],
  "tender": {
   "type": "MOBILE_PAY",
   "amount": 55.3
  },
  "subtotal": 50.97,
  "tax": 4.33,
  "total": 55.3,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241022-LA-0056",
  "store_id": "STR_LA_BEVHILLS_002",
  "store_name": "Beverly Hills Gourmet",
  "terminal_id": "T-02",
  "operator_id": "OP-296",
  "business_date": "2024-10-22",
  "ts": {
   "$date": "2024-10-22T11:35:26Z"
  },
  "customer_id": "CUST_332156789",
  "loyalty_scanned": true,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 2,
    "unit_price": 16.99,
    "extended_price": 33.98
   }
  ],
  "tender": {
   "type": "MOBILE_PAY",
   "amount": 36.87
  },
  "subtotal": 33.98,
  "tax": 2.89,
  "total": 36.87,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241022-DEN-0011",
  "store_id": "STR_DEN_CAPITOL_008",
  "store_name": "Capitol Hill Whole Foods Coop",
  "terminal_id": "T-03",
  "operator_id": "OP-204",
  "business_date": "2024-10-22",
  "ts": {
   "$date": "2024-10-22T12:48:05Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_023",
    "sku": "TRL_ALPINE_BULK_1LB",
    "description": "Alpine Trail Mix Bulk 1lb",
    "qty": 1.6,
    "unit_price": 12.99,
    "extended_price": 20.78
   }
  ],
  "tender": {
   "type": "MOBILE_PAY",
   "amount": 22.55
  },
  "subtotal": 20.78,
  "tax": 1.77,
  "total": 22.55,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241020-DEN-0009",
  "store_id": "STR_DEN_CAPITOL_008",
  "store_name": "Capitol Hill Whole Foods Coop",
  "terminal_id": "T-05",
  "operator_id": "OP-384",
  "business_date": "2024-10-20",
  "ts": {
   "$date": "2024-10-20T12:28:51Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_023",
    "sku": "TRL_ALPINE_BULK_1LB",
    "description": "Alpine Trail Mix Bulk 1lb",
    "qty": 2.3,
    "unit_price": 12.99,
    "extended_price": 29.88
   }
  ],
  "tender": {
   "type": "CREDIT_CARD",
   "amount": 32.42
  },
  "subtotal": 29.88,
  "tax": 2.54,
  "total": 32.42,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241018-SEA-0019",
  "store_id": "STR_SEA_PIKE_005",
  "store_name": "Pike Place Artisan Foods",
  "terminal_id": "T-05",
  "operator_id": "OP-997",
  "business_date": "2024-10-18",
  "ts": {
   "$date": "2024-10-18T08:13:45Z"
  },
  "customer_id": "CUST_332156789",
  "loyalty_scanned": true,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   }
  ],
  "tender": {
   "type": "CASH",
   "amount": 18.43
  },
  "subtotal": 16.99,
  "tax": 1.44,
  "total": 18.43,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241021-NYC-0054",
  "store_id": "STR_NYC_MANHATTAN_001",
  "store_name": "Fifth Avenue Fresh Market",
  "terminal_id": "T-05",
  "operator_id": "OP-803",
  "business_date": "2024-10-21",
  "ts": {
   "$date": "2024-10-21T15:59:46Z"
  },
  "customer_id": "CUST_332156789",
  "loyalty_scanned": true,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   },
   {
    "product_id": "ITM_023",
    "sku": "TRL_ALPINE_BULK_1LB",
    "description": "Alpine Trail Mix Bulk 1lb",
    "qty": 1.37,
    "unit_price": 12.99,
    "extended_price": 17.8
   }
  ],
  "tender": {
   "type": "DEBIT_CARD",
   "amount": 37.75
  },
  "subtotal": 34.79,
  "tax": 2.96,
  "total": 37.75,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241022-LV-0064",
  "store_id": "STR_LV_SUMMERLIN_015",
  "store_name": "Summerlin Gourmet Oasis",
  "terminal_id": "T-06",
  "operator_id": "OP-383",
  "business_date": "2024-10-22",
  "ts": {
   "$date": "2024-10-22T19:15:49Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   }
  ],
  "tender": {
   "type": "MOBILE_PAY",
   "amount": 18.43
  },
  "subtotal": 16.99,
  "tax": 1.44,
  "total": 18.43,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241022-SEA-0015",
  "store_id": "STR_SEA_PIKE_005",
  "store_name": "Pike Place Artisan Foods",
  "terminal_id": "T-05",
  "operator_id": "OP-982",
  "business_date": "2024-10-22",
  "ts": {
   "$date": "2024-10-22T20:40:23Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 2,
    "unit_price": 16.99,
    "extended_price": 33.98
   }
  ],
  "tender": {
   "type": "DEBIT_CARD",
   "amount": 36.87
  },
  "subtotal": 33.98,
  "tax": 2.89,
  "total": 36.87,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241018-SEA-0016",
  "store_id": "STR_SEA_PIKE_005",
  "store_name": "Pike Place Artisan Foods",
  "terminal_id": "T-01",
  "operator_id": "OP-489",
  "business_date": "2024-10-18",
  "ts": {
   "$date": "2024-10-18T20:14:17Z"
  },
  "customer_id": "CUST_332156789",
  "loyalty_scanned": true,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   }
  ],
  "tender": {
   "type": "MOBILE_PAY",
   "amount": 18.43
  },
  "subtotal": 16.99,
  "tax": 1.44,
  "total": 18.43,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241019-SEA-0025",
  "store_id": "STR_SEA_PIKE_005",
  "store_name": "Pike Place Artisan Foods",
  "terminal_id": "T-01",
  "operator_id": "OP-471",
  "business_date": "2024-10-19",
  "ts": {
   "$date": "2024-10-19T14:01:56Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   }
  ],
  "tender": {
   "type": "CASH",
   "amount": 18.43
  },
  "subtotal": 16.99,
  "tax": 1.44,
  "total": 18.43,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241019-LV-0070",
  "store_id": "STR_LV_SUMMERLIN_015",
  "store_name": "Summerlin Gourmet Oasis",
  "terminal_id": "T-06",
  "operator_id": "OP-127",
  "business_date": "2024-10-19",
  "ts": {
   "$date": "2024-10-19T16:36:05Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   }
  ],
  "tender": {
   "type": "MOBILE_PAY",
   "amount": 18.43
  },
  "subtotal": 16.99,
  "tax": 1.44,
  "total": 18.43,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241022-LV-0067",
  "store_id": "STR_LV_SUMMERLIN_015",
  "store_name": "Summerlin Gourmet Oasis",
  "terminal_id": "T-05",
  "operator_id": "OP-812",
  "business_date": "2024-10-22",
  "ts": {
   "$date": "2024-10-22T13:24:01Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 2,
    "unit_price": 16.99,
    "extended_price": 33.98
   }
  ],
  "tender": {
   "type": "MOBILE_PAY",
   "amount": 36.87
  },
  "subtotal": 33.98,
  "tax": 2.89,
  "total": 36.87,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241021-LV-0061",
  "store_id": "STR_LV_SUMMERLIN_015",
  "store_name": "Summerlin Gourmet Oasis",
  "terminal_id": "T-01",
  "operator_id": "OP-897",
  "business_date": "2024-10-21",
  "ts": {
   "$date": "2024-10-21T21:48:27Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 2,
    "unit_price": 16.99,
    "extended_price": 33.98
   },
   {
    "product_id": "ITM_023",
    "sku": "TRL_ALPINE_BULK_1LB",
    "description": "Alpine Trail Mix Bulk 1lb",
    "qty": 1.88,
    "unit_price": 12.99,
    "extended_price": 24.42
   }
  ],
  "tender": {
   "type": "DEBIT_CARD",
   "amount": 63.36
  },
  "subtotal": 58.4,
  "tax": 4.96,
  "total": 63.36,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241022-SEA-0018",
  "store_id": "STR_SEA_PIKE_005",
  "store_name": "Pike Place Artisan Foods",
  "terminal_id": "T-06",
  "operator_id": "OP-670",
  "business_date": "2024-10-22",
  "ts": {
   "$date": "2024-10-22T21:40:14Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   }
  ],
  "tender": {
   "type": "CASH",
   "amount": 18.43
  },
  "subtotal": 16.99,
  "tax": 1.44,
  "total": 18.43,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241019-LA-0012",
  "store_id": "STR_LA_BEVHILLS_002",
  "store_name": "Beverly Hills Gourmet",
  "terminal_id": "T-01",
  "operator_id": "OP-467",
  "business_date": "2024-10-19",
  "ts": {
   "$date": "2024-10-19T19:22:54Z"
  },
  "customer_id": "CUST_992847531",
  "loyalty_scanned": true,
  "lines": [
   {
    "product_id": "ITM_006",
    "sku": "WIN_OPUS_750ML",
    "description": "Opus One Napa Valley 2019",
    "qty": 1,
    "unit_price": 425.0,
    "extended_price": 425.0
   }
  ],
  "tender": {
   "type": "CREDIT_CARD",
   "amount": 461.12
  },
  "subtotal": 425.0,
  "tax": 36.12,
  "total": 461.12,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241018-SEA-0038",
  "store_id": "STR_SEA_PIKE_005",
  "store_name": "Pike Place Artisan Foods",
  "terminal_id": "T-02",
  "operator_id": "OP-158",
  "business_date": "2024-10-18",
  "ts": {
   "$date": "2024-10-18T20:33:32Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 3,
    "unit_price": 16.99,
    "extended_price": 50.97
   }
  ],
  "tender": {
   "type": "CREDIT_CARD",
   "amount": 55.3
  },
  "subtotal": 50.97,
  "tax": 4.33,
  "total": 55.3,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241019-SEA-0066",
  "store_id": "STR_SEA_PIKE_005",
  "store_name": "Pike Place Artisan Foods",
  "terminal_id": "T-01",
  "operator_id": "OP-524",
  "business_date": "2024-10-19",
  "ts": {
   "$date": "2024-10-19T18:13:26Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   }
  ],
  "tender": {
   "type": "CASH",
   "amount": 18.43
  },
  "subtotal": 16.99,
  "tax": 1.44,
  "total": 18.43,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241018-SEA-0030",
  "store_id": "STR_SEA_PIKE_005",
  "store_name": "Pike Place Artisan Foods",
  "terminal_id": "T-04",
  "operator_id": "OP-319",
  "business_date": "2024-10-18",
  "ts": {
   "$date": "2024-10-18T11:42:34Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   }
  ],
  "tender": {
   "type": "DEBIT_CARD",
   "amount": 18.43
  },
  "subtotal": 16.99,
  "tax": 1.44,
  "total": 18.43,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241020-NYC-0047",
  "store_id": "STR_NYC_MANHATTAN_001",
  "store_name": "Fifth Avenue Fresh Market",
  "terminal_id": "T-03",
  "operator_id": "OP-915",
  "business_date": "2024-10-20",
  "ts": {
   "$date": "2024-10-20T07:19:55Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 3,
    "unit_price": 16.99,
    "extended_price": 50.97
   }
  ],
  "tender": {
   "type": "CREDIT_CARD",
   "amount": 55.3
  },
  "subtotal": 50.97,
  "tax": 4.33,
  "total": 55.3,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241021-SEA-0069",
  "store_id": "STR_SEA_PIKE_005",
  "store_name": "Pike Place Artisan Foods",
  "terminal_id": "T-06",
  "operator_id": "OP-795",
  "business_date": "2024-10-21",
  "ts": {
   "$date": "2024-10-21T13:21:51Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   }
  ],
  "tender": {
   "type": "MOBILE_PAY",
   "amount": 18.43
  },
  "subtotal": 16.99,
  "tax": 1.44,
  "total": 18.43,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241020-LA-0007",
  "store_id": "STR_LA_BEVHILLS_002",
  "store_name": "Beverly Hills Gourmet",
  "terminal_id": "T-01",
  "operator_id": "OP-323",
  "business_date": "2024-10-20",
  "ts": {
   "$date": "2024-10-20T18:47:14Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_046",
    "sku": "TRF_BLK_SHAVED_1OZ",
    "description": "Shaved Black Truffle 1oz",
    "qty": 1,
    "unit_price": 159.99,
    "extended_price": 159.99
   }
  ],
  "tender": {
   "type": "CREDIT_CARD",
   "amount": 173.59
  },
  "subtotal": 159.99,
  "tax": 13.6,
  "total": 173.59,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241019-LA-0065",
  "store_id": "STR_LA_BEVHILLS_002",
  "store_name": "Beverly Hills Gourmet",
  "terminal_id": "T-03",
  "operator_id": "OP-427",
  "business_date": "2024-10-19",
  "ts": {
   "$date": "2024-10-19T10:17:57Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 2,
    "unit_price": 16.99,
    "extended_price": 33.98
   }
  ],
  "tender": {
   "type": "CREDIT_CARD",
   "amount": 36.87
  },
  "subtotal": 33.98,
  "tax": 2.89,
  "total": 36.87,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241021-DEN-0027",
  "store_id": "STR_DEN_CAPITOL_008",
  "store_name": "Capitol Hill Whole Foods Coop",
  "terminal_id": "T-02",
  "operator_id": "OP-652",
  "business_date": "2024-10-21",
  "ts": {
   "$date": "2024-10-21T16:27:48Z"
  },
  "customer_id": "CUST_332156789",
  "loyalty_scanned": true,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   }
  ],
  "tender": {
   "type": "DEBIT_CARD",
   "amount": 18.43
  },
  "subtotal": 16.99,
  "tax": 1.44,
  "total": 18.43,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241021-MIA-0001",
  "store_id": "STR_MIA_SOUTHBEACH_004",
  "store_name": "South Beach Organic Market",
  "terminal_id": "T-06",
  "operator_id": "OP-214",
  "business_date": "2024-10-21",
  "ts": {
   "$date": "2024-10-21T09:14:01Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_010",
    "sku": "SMT_ACAI_16OZ",
    "description": "Tropical Acai Smoothie Bowl 16oz",
    "qty": 1,
    "unit_price": 14.99,
    "extended_price": 14.99
   }
  ],
  "tender": {
   "type": "CASH",
   "amount": 16.26
  },
  "subtotal": 14.99,
  "tax": 1.27,
  "total": 16.26,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241018-SEA-0022",
  "store_id": "STR_SEA_PIKE_005",
  "store_name": "Pike Place Artisan Foods",
  "terminal_id": "T-05",
  "operator_id": "OP-579",
  "business_date": "2024-10-18",
  "ts": {
   "$date": "2024-10-18T13:24:33Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   }
  ],
  "tender": {
   "type": "CASH",
   "amount": 18.43
  },
  "subtotal": 16.99,
  "tax": 1.44,
  "total": 18.43,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241018-DEN-0042",
  "store_id": "STR_DEN_CAPITOL_008",
  "store_name": "Capitol Hill Whole Foods Coop",
  "terminal_id": "T-02",
  "operator_id": "OP-478",
  "business_date": "2024-10-18",
  "ts": {
   "$date": "2024-10-18T08:56:18Z"
  },
  "customer_id": "CUST_332156789",
  "loyalty_scanned": true,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   },
   {
    "product_id": "ITM_023",
    "sku": "TRL_ALPINE_BULK_1LB",
    "description": "Alpine Trail Mix Bulk 1lb",
    "qty": 1.2,
    "unit_price": 12.99,
    "extended_price": 15.59
   }
  ],
  "tender": {
   "type": "DEBIT_CARD",
   "amount": 35.35
  },
  "subtotal": 32.58,
  "tax": 2.77,
  "total": 35.35,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241021-SEA-0033",
  "store_id": "STR_SEA_PIKE_005",
  "store_name": "Pike Place Artisan Foods",
  "terminal_id": "T-02",
  "operator_id": "OP-385",
  "business_date": "2024-10-21",
  "ts": {
   "$date": "2024-10-21T09:27:29Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   },
   {
    "product_id": "ITM_023",
    "sku": "TRL_ALPINE_BULK_1LB",
    "description": "Alpine Trail Mix Bulk 1lb",
    "qty": 1.57,
    "unit_price": 12.99,
    "extended_price": 20.39
   }
  ],
  "tender": {
   "type": "DEBIT_CARD",
   "amount": 40.56
  },
  "subtotal": 37.38,
  "tax": 3.18,
  "total": 40.56,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241022-MIA-0005",
  "store_id": "STR_MIA_SOUTHBEACH_004",
  "store_name": "South Beach Organic Market",
  "terminal_id": "T-05",
  "operator_id": "OP-189",
  "business_date": "2024-10-22",
  "ts": {
   "$date": "2024-10-22T16:33:37Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_010",
    "sku": "SMT_ACAI_16OZ",
    "description": "Tropical Acai Smoothie Bowl 16oz",
    "qty": 1,
    "unit_price": 14.99,
    "extended_price": 14.99
   }
  ],
  "tender": {
   "type": "CASH",
   "amount": 16.26
  },
  "subtotal": 14.99,
  "tax": 1.27,
  "total": 16.26,
  "status": "VOIDED"
 },
 {
  "transaction_id": "POS-20241018-LA-0024",
  "store_id": "STR_LA_BEVHILLS_002",
  "store_name": "Beverly Hills Gourmet",
  "terminal_id": "T-06",
  "operator_id": "OP-405",
  "business_date": "2024-10-18",
  "ts": {
   "$date": "2024-10-18T08:55:53Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 3,
    "unit_price": 16.99,
    "extended_price": 50.97
   }
  ],
  "tender": {
   "type": "DEBIT_CARD",
   "amount": 55.3
  },
  "subtotal": 50.97,
  "tax": 4.33,
  "total": 55.3,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241021-DEN-0043",
  "store_id": "STR_DEN_CAPITOL_008",
  "store_name": "Capitol Hill Whole Foods Coop",
  "terminal_id": "T-06",
  "operator_id": "OP-206",
  "business_date": "2024-10-21",
  "ts": {
   "$date": "2024-10-21T15:19:56Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   }
  ],
  "tender": {
   "type": "DEBIT_CARD",
   "amount": 18.43
  },
  "subtotal": 16.99,
  "tax": 1.44,
  "total": 18.43,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241020-MIA-0028",
  "store_id": "STR_MIA_SOUTHBEACH_004",
  "store_name": "South Beach Organic Market",
  "terminal_id": "T-02",
  "operator_id": "OP-330",
  "business_date": "2024-10-20",
  "ts": {
   "$date": "2024-10-20T14:07:04Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   }
  ],
  "tender": {
   "type": "CASH",
   "amount": 18.43
  },
  "subtotal": 16.99,
  "tax": 1.44,
  "total": 18.43,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241019-MIA-0035",
  "store_id": "STR_MIA_SOUTHBEACH_004",
  "store_name": "South Beach Organic Market",
  "terminal_id": "T-01",
  "operator_id": "OP-268",
  "business_date": "2024-10-19",
  "ts": {
   "$date": "2024-10-19T13:57:24Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 2,
    "unit_price": 16.99,
    "extended_price": 33.98
   }
  ],
  "tender": {
   "type": "CREDIT_CARD",
   "amount": 36.87
  },
  "subtotal": 33.98,
  "tax": 2.89,
  "total": 36.87,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241022-SEA-0023",
  "store_id": "STR_SEA_PIKE_005",
  "store_name": "Pike Place Artisan Foods",
  "terminal_id": "T-03",
  "operator_id": "OP-545",
  "business_date": "2024-10-22",
  "ts": {
   "$date": "2024-10-22T12:07:10Z"
  },
  "customer_id": "CUST_332156789",
  "loyalty_scanned": true,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   }
  ],
  "tender": {
   "type": "MOBILE_PAY",
   "amount": 18.43
  },
  "subtotal": 16.99,
  "tax": 1.44,
  "total": 18.43,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241022-MIA-0003",
  "store_id": "STR_MIA_SOUTHBEACH_004",
  "store_name": "South Beach Organic Market",
  "terminal_id": "T-02",
  "operator_id": "OP-242",
  "business_date": "2024-10-22",
  "ts": {
   "$date": "2024-10-22T08:55:47Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_010",
    "sku": "SMT_ACAI_16OZ",
    "description": "Tropical Acai Smoothie Bowl 16oz",
    "qty": 1,
    "unit_price": 14.99,
    "extended_price": 14.99
   }
  ],
  "tender": {
   "type": "MOBILE_PAY",
   "amount": 16.26
  },
  "subtotal": 14.99,
  "tax": 1.27,
  "total": 16.26,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241019-SEA-0060",
  "store_id": "STR_SEA_PIKE_005",
  "store_name": "Pike Place Artisan Foods",
  "terminal_id": "T-01",
  "operator_id": "OP-566",
  "business_date": "2024-10-19",
  "ts": {
   "$date": "2024-10-19T16:54:26Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   }
  ],
  "tender": {
   "type": "DEBIT_CARD",
   "amount": 18.43
  },
  "subtotal": 16.99,
  "tax": 1.44,
  "total": 18.43,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241019-SEA-0037",
  "store_id": "STR_SEA_PIKE_005",
  "store_name": "Pike Place Artisan Foods",
  "terminal_id": "T-05",
  "operator_id": "OP-162",
  "business_date": "2024-10-19",
  "ts": {
   "$date": "2024-10-19T16:47:47Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   }
  ],
  "tender": {
   "type": "CASH",
   "amount": 18.43
  },
  "subtotal": 16.99,
  "tax": 1.44,
  "total": 18.43,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241021-SEA-0068",
  "store_id": "STR_SEA_PIKE_005",
  "store_name": "Pike Place Artisan Foods",
  "terminal_id": "T-04",
  "operator_id": "OP-651",
  "business_date": "2024-10-21",
  "ts": {
   "$date": "2024-10-21T20:57:47Z"
  },
  "customer_id": "CUST_332156789",
  "loyalty_scanned": true,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   }
  ],
  "tender": {
   "type": "DEBIT_CARD",
   "amount": 18.43
  },
  "subtotal": 16.99,
  "tax": 1.44,
  "total": 18.43,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241019-DEN-0008",
  "store_id": "STR_DEN_CAPITOL_008",
  "store_name": "Capitol Hill Whole Foods Coop",
  "terminal_id": "T-01",
  "operator_id": "OP-674",
  "business_date": "2024-10-19",
  "ts": {
   "$date": "2024-10-19T17:38:12Z"
  },
  "customer_id": "CUST_778899001",
  "loyalty_scanned": true,
  "lines": [
   {
    "product_id": "ITM_023",
    "sku": "TRL_ALPINE_BULK_1LB",
    "description": "Alpine Trail Mix Bulk 1lb",
    "qty": 1.15,
    "unit_price": 12.99,
    "extended_price": 14.94
   }
  ],
  "tender": {
   "type": "MOBILE_PAY",
   "amount": 16.21
  },
  "subtotal": 14.94,
  "tax": 1.27,
  "total": 16.21,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241022-MIA-0052",
  "store_id": "STR_MIA_SOUTHBEACH_004",
  "store_name": "South Beach Organic Market",
  "terminal_id": "T-03",
  "operator_id": "OP-282",
  "business_date": "2024-10-22",
  "ts": {
   "$date": "2024-10-22T08:56:37Z"
  },
  "customer_id": "CUST_332156789",
  "loyalty_scanned": true,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 3,
    "unit_price": 16.99,
    "extended_price": 50.97
   }
  ],
  "tender": {
   "type": "CASH",
   "amount": 55.3
  },
  "subtotal": 50.97,
  "tax": 4.33,
  "total": 55.3,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241019-SEA-0039",
  "store_id": "STR_SEA_PIKE_005",
  "store_name": "Pike Place Artisan Foods",
  "terminal_id": "T-01",
  "operator_id": "OP-683",
  "business_date": "2024-10-19",
  "ts": {
   "$date": "2024-10-19T10:25:15Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 3,
    "unit_price": 16.99,
    "extended_price": 50.97
   }
  ],
  "tender": {
   "type": "CREDIT_CARD",
   "amount": 55.3
  },
  "subtotal": 50.97,
  "tax": 4.33,
  "total": 55.3,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241020-SEA-0044",
  "store_id": "STR_SEA_PIKE_005",
  "store_name": "Pike Place Artisan Foods",
  "terminal_id": "T-06",
  "operator_id": "OP-451",
  "business_date": "2024-10-20",
  "ts": {
   "$date": "2024-10-20T16:13:13Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   }
  ],
  "tender": {
   "type": "CASH",
   "amount": 18.43
  },
  "subtotal": 16.99,
  "tax": 1.44,
  "total": 18.43,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241020-MIA-0055",
  "store_id": "STR_MIA_SOUTHBEACH_004",
  "store_name": "South Beach Organic Market",
  "terminal_id": "T-01",
  "operator_id": "OP-837",
  "business_date": "2024-10-20",
  "ts": {
   "$date": "2024-10-20T17:54:57Z"
  },
  "customer_id": "CUST_332156789",
  "loyalty_scanned": true,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   }
  ],
  "tender": {
   "type": "CASH",
   "amount": 18.43
  },
  "subtotal": 16.99,
  "tax": 1.44,
  "total": 18.43,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241019-LV-0020",
  "store_id": "STR_LV_SUMMERLIN_015",
  "store_name": "Summerlin Gourmet Oasis",
  "terminal_id": "T-05",
  "operator_id": "OP-369",
  "business_date": "2024-10-19",
  "ts": {
   "$date": "2024-10-19T18:35:47Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 2,
    "unit_price": 16.99,
    "extended_price": 33.98
   },
   {
    "product_id": "ITM_023",
    "sku": "TRL_ALPINE_BULK_1LB",
    "description": "Alpine Trail Mix Bulk 1lb",
    "qty": 0.78,
    "unit_price": 12.99,
    "extended_price": 10.13
   }
  ],
  "tender": {
   "type": "MOBILE_PAY",
   "amount": 47.86
  },
  "subtotal": 44.11,
  "tax": 3.75,
  "total": 47.86,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241020-SEA-0050",
  "store_id": "STR_SEA_PIKE_005",
  "store_name": "Pike Place Artisan Foods",
  "terminal_id": "T-02",
  "operator_id": "OP-304",
  "business_date": "2024-10-20",
  "ts": {
   "$date": "2024-10-20T20:30:52Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   }
  ],
  "tender": {
   "type": "MOBILE_PAY",
   "amount": 18.43
  },
  "subtotal": 16.99,
  "tax": 1.44,
  "total": 18.43,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241022-LV-0045",
  "store_id": "STR_LV_SUMMERLIN_015",
  "store_name": "Summerlin Gourmet Oasis",
  "terminal_id": "T-01",
  "operator_id": "OP-441",
  "business_date": "2024-10-22",
  "ts": {
   "$date": "2024-10-22T11:02:49Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   },
   {
    "product_id": "ITM_023",
    "sku": "TRL_ALPINE_BULK_1LB",
    "description": "Alpine Trail Mix Bulk 1lb",
    "qty": 1.35,
    "unit_price": 12.99,
    "extended_price": 17.54
   }
  ],
  "tender": {
   "type": "DEBIT_CARD",
   "amount": 37.47
  },
  "subtotal": 34.53,
  "tax": 2.94,
  "total": 37.47,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241020-MIA-0072",
  "store_id": "STR_MIA_SOUTHBEACH_004",
  "store_name": "South Beach Organic Market",
  "terminal_id": "T-01",
  "operator_id": "OP-458",
  "business_date": "2024-10-20",
  "ts": {
   "$date": "2024-10-20T18:34:14Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   }
  ],
  "tender": {
   "type": "CREDIT_CARD",
   "amount": 18.43
  },
  "subtotal": 16.99,
  "tax": 1.44,
  "total": 18.43,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241020-MIA-0032",
  "store_id": "STR_MIA_SOUTHBEACH_004",
  "store_name": "South Beach Organic Market",
  "terminal_id": "T-06",
  "operator_id": "OP-761",
  "business_date": "2024-10-20",
  "ts": {
   "$date": "2024-10-20T07:43:06Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 2,
    "unit_price": 16.99,
    "extended_price": 33.98
   }
  ],
  "tender": {
   "type": "CREDIT_CARD",
   "amount": 36.87
  },
  "subtotal": 33.98,
  "tax": 2.89,
  "total": 36.87,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241021-DEN-0010",
  "store_id": "STR_DEN_CAPITOL_008",
  "store_name": "Capitol Hill Whole Foods Coop",
  "terminal_id": "T-04",
  "operator_id": "OP-448",
  "business_date": "2024-10-21",
  "ts": {
   "$date": "2024-10-21T11:44:17Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_023",
    "sku": "TRL_ALPINE_BULK_1LB",
    "description": "Alpine Trail Mix Bulk 1lb",
    "qty": 0.85,
    "unit_price": 12.99,
    "extended_price": 11.04
   }
  ],
  "tender": {
   "type": "DEBIT_CARD",
   "amount": 11.98
  },
  "subtotal": 11.04,
  "tax": 0.94,
  "total": 11.98,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241019-SEA-0026",
  "store_id": "STR_SEA_PIKE_005",
  "store_name": "Pike Place Artisan Foods",
  "terminal_id": "T-05",
  "operator_id": "OP-884",
  "business_date": "2024-10-19",
  "ts": {
   "$date": "2024-10-19T08:48:08Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   },
   {
    "product_id": "ITM_023",
    "sku": "TRL_ALPINE_BULK_1LB",
    "description": "Alpine Trail Mix Bulk 1lb",
    "qty": 1.47,
    "unit_price": 12.99,
    "extended_price": 19.1
   }
  ],
  "tender": {
   "type": "DEBIT_CARD",
   "amount": 39.16
  },
  "subtotal": 36.09,
  "tax": 3.07,
  "total": 39.16,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241020-LA-0051",
  "store_id": "STR_LA_BEVHILLS_002",
  "store_name": "Beverly Hills Gourmet",
  "terminal_id": "T-01",
  "operator_id": "OP-891",
  "business_date": "2024-10-20",
  "ts": {
   "$date": "2024-10-20T12:17:17Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   },
   {
    "product_id": "ITM_023",
    "sku": "TRL_ALPINE_BULK_1LB",
    "description": "Alpine Trail Mix Bulk 1lb",
    "qty": 0.89,
    "unit_price": 12.99,
    "extended_price": 11.56
   }
  ],
  "tender": {
   "type": "CASH",
   "amount": 30.98
  },
  "subtotal": 28.55,
  "tax": 2.43,
  "total": 30.98,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241019-SEA-0049",
  "store_id": "STR_SEA_PIKE_005",
  "store_name": "Pike Place Artisan Foods",
  "terminal_id": "T-04",
  "operator_id": "OP-921",
  "business_date": "2024-10-19",
  "ts": {
   "$date": "2024-10-19T12:50:42Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   },
   {
    "product_id": "ITM_023",
    "sku": "TRL_ALPINE_BULK_1LB",
    "description": "Alpine Trail Mix Bulk 1lb",
    "qty": 1.97,
    "unit_price": 12.99,
    "extended_price": 25.59
   }
  ],
  "tender": {
   "type": "DEBIT_CARD",
   "amount": 46.2
  },
  "subtotal": 42.58,
  "tax": 3.62,
  "total": 46.2,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241018-SEA-0073",
  "store_id": "STR_SEA_PIKE_005",
  "store_name": "Pike Place Artisan Foods",
  "terminal_id": "T-02",
  "operator_id": "OP-229",
  "business_date": "2024-10-18",
  "ts": {
   "$date": "2024-10-18T16:09:30Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   }
  ],
  "tender": {
   "type": "CREDIT_CARD",
   "amount": 18.43
  },
  "subtotal": 16.99,
  "tax": 1.44,
  "total": 18.43,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241022-LA-0004",
  "store_id": "STR_LA_BEVHILLS_002",
  "store_name": "Beverly Hills Gourmet",
  "terminal_id": "T-01",
  "operator_id": "OP-792",
  "business_date": "2024-10-22",
  "ts": {
   "$date": "2024-10-22T10:05:47Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_010",
    "sku": "SMT_ACAI_16OZ",
    "description": "Tropical Acai Smoothie Bowl 16oz",
    "qty": 1,
    "unit_price": 14.99,
    "extended_price": 14.99
   }
  ],
  "tender": {
   "type": "CASH",
   "amount": 16.26
  },
  "subtotal": 14.99,
  "tax": 1.27,
  "total": 16.26,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241022-NYC-0014",
  "store_id": "STR_NYC_MANHATTAN_001",
  "store_name": "Fifth Avenue Fresh Market",
  "terminal_id": "T-01",
  "operator_id": "OP-847",
  "business_date": "2024-10-22",
  "ts": {
   "$date": "2024-10-22T20:41:29Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_006",
    "sku": "WIN_OPUS_750ML",
    "description": "Opus One Napa Valley 2019",
    "qty": 1,
    "unit_price": 425.0,
    "extended_price": 425.0
   }
  ],
  "tender": {
   "type": "CREDIT_CARD",
   "amount": 461.12
  },
  "subtotal": 425.0,
  "tax": 36.12,
  "total": 461.12,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241022-SEA-0040",
  "store_id": "STR_SEA_PIKE_005",
  "store_name": "Pike Place Artisan Foods",
  "terminal_id": "T-06",
  "operator_id": "OP-421",
  "business_date": "2024-10-22",
  "ts": {
   "$date": "2024-10-22T10:42:15Z"
  },
  "customer_id": "CUST_332156789",
  "loyalty_scanned": true,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 2,
    "unit_price": 16.99,
    "extended_price": 33.98
   }
  ],
  "tender": {
   "type": "CASH",
   "amount": 36.87
  },
  "subtotal": 33.98,
  "tax": 2.89,
  "total": 36.87,
  "status": "COMPLETED"
 },
 {
  "transaction_id": "POS-20241022-MIA-0021",
  "store_id": "STR_MIA_SOUTHBEACH_004",
  "store_name": "South Beach Organic Market",
  "terminal_id": "T-04",
  "operator_id": "OP-193",
  "business_date": "2024-10-22",
  "ts": {
   "$date": "2024-10-22T09:32:48Z"
  },
  "customer_id": null,
  "loyalty_scanned": false,
  "lines": [
   {
    "product_id": "ITM_013",
    "sku": "COF_PIKE_12OZ",
    "description": "Pike Place Signature Roast 12oz",
    "qty": 1,
    "unit_price": 16.99,
    "extended_price": 16.99
   }
  ],
  "tender": {
   "type": "CREDIT_CARD",
   "amount": 18.43
  },
  "subtotal": 16.99,
  "tax": 1.44,
  "total": 18.43,
  "status": "COMPLETED"
 }
]
);
db.poslog_transactions.createIndex({ business_date: 1 });
db.poslog_transactions.createIndex({ 'lines.product_id': 1 });
db.poslog_transactions.createIndex({ customer_id: 1 });
print('POSLOG seed complete: ' + db.poslog_transactions.countDocuments({}) + ' transactions');
