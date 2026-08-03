#!/bin/bash
set -e
mongoimport --username root --password root --authenticationDatabase admin \
  --db retail_pos --collection poslog_transactions --drop \
  --file /docker-entrypoint-initdb.d/poslog-data.ndjson
mongosh --username root --password root --authenticationDatabase admin retail_pos --quiet --eval '
db.poslog_transactions.createIndex({ "items.item_id": 1 });
db.poslog_transactions.createIndex({ "store.store_id": 1 });
db.poslog_transactions.createIndex({ "customer.customer_id": 1 });
db.poslog_transactions.createIndex({ timestamp: 1 });
print("POSLOG seed complete: " + db.poslog_transactions.countDocuments({}) + " transactions");'
