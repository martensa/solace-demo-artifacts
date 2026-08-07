// Read-only user for the SAM MongoDB connectors (demo creds).
// The data itself is imported by 02-import.sh (mongoimport) from
// station-telemetry.ndjson and material-consumption.ndjson --
// generated deterministically by generate-seed.py (checked in
// alongside; re-run it only when the storyline data changes).
db = db.getSiblingDB('mfg_plant');
db.createUser({
  user: 'sam_ro',
  pwd: 'sam_ro',
  roles: [ { role: 'read', db: 'mfg_plant' } ]
});
