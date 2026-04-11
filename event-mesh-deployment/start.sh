#!/bin/sh
set -e

cp .env.example .env

docker compose up -d

echo "Waiting for solace-1 SEMP to become ready..."
until curl -sf -o /dev/null http://127.0.0.1:8080/SEMP/v2/config/about; do
  sleep 2
done

echo "Waiting for solace-2 SEMP to become ready..."
until curl -sf -o /dev/null http://127.0.0.1:8090/SEMP/v2/config/about; do
  sleep 2
done

cd ./terraform
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform apply -auto-approve

curl --location --request PATCH 'http://127.0.0.1:8080/SEMP/v2/config/dmrClusters/cluster-solace-1/links/solace-2' \
--header 'Content-Type: application/json' \
--header 'Authorization: Basic YWRtaW46YWRtaW4=' \
--data '{
	"enabled": true
} '

curl --location --request PATCH 'http://127.0.0.1:8090/SEMP/v2/config/dmrClusters/cluster-solace-2/links/solace-1' \
--header 'Content-Type: application/json' \
--header 'Authorization: Basic YWRtaW46YWRtaW4=' \
--data '{
	"enabled": true
} '

echo "Event mesh deployment complete."
