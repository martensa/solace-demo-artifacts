#!/bin/bash
set -e
mongoimport --username root --password root --authenticationDatabase admin \
  --db mfg_plant --collection station_telemetry --drop \
  --file /docker-entrypoint-initdb.d/station-telemetry.ndjson
mongoimport --username root --password root --authenticationDatabase admin \
  --db mfg_plant --collection material_consumption --drop \
  --file /docker-entrypoint-initdb.d/material-consumption.ndjson
mongosh --username root --password root --authenticationDatabase admin mfg_plant --quiet --eval '
db.station_telemetry.createIndex({ "plant.plant_id": 1, line_id: 1 });
db.station_telemetry.createIndex({ "product.material_id": 1 });
db.station_telemetry.createIndex({ result: 1 });
db.station_telemetry.createIndex({ ts: 1 });
db.material_consumption.createIndex({ "plant.plant_id": 1, material_id: 1 });
db.material_consumption.createIndex({ ts: 1 });
print("Plant seed complete: " + db.station_telemetry.countDocuments({}) +
      " telemetry docs, " + db.material_consumption.countDocuments({}) +
      " consumption docs");'
