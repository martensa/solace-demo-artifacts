// Read-only user for the SAM MongoDB connector (demo credentials).
// The data itself is imported by 02-import.sh (mongoimport) from
// poslog-data.ndjson: the original blog artifact
// (github.com/martensa/solace-sam-demos, sam-retail) plus the
// meetup story transactions in the same document shape.
db = db.getSiblingDB('retail_pos');
db.createUser({
  user: 'sam_ro',
  pwd: 'sam_ro',
  roles: [ { role: 'read', db: 'retail_pos' } ]
});
