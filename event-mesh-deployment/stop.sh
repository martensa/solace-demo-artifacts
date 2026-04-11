#!/bin/sh
docker compose down -v
rm -rf ./terraform/.terraform
rm -f ./terraform/terraform.tfstate
rm -f ./terraform/.terraform.lock.hcl
rm -f ./terraform/terraform.tfvars
rm -f ./.env
