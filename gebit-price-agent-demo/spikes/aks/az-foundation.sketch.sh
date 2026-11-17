#!/bin/bash
# SKETCH ONLY -- never executed in this research. Azure foundation for
# the EuroCIS demo on AKS (Germany West Central). Fill .env.aks first.
set -euo pipefail
LOC=germanywestcentral
RG=rg-gpos-eurocis
CL=aks-gpos
ACR=acrgposeurocis            # globally unique, alnum only
PG=pg-gpos-eurocis
SA=stgposeurocis              # storage account for SAM artifacts
ZONE=DEMO_DOMAIN              # delegated public zone, e.g. a subdomain
ADMIN_IPS="x.x.x.x/32"        # office/home + WireGuard VM public IP

az group create -n $RG -l $LOC
az network vnet create -g $RG -n vnet-gpos --address-prefixes 10.20.0.0/16 \
  --subnet-name snet-aks --subnet-prefixes 10.20.0.0/22
az network vnet subnet create -g $RG --vnet-name vnet-gpos -n snet-pg \
  --address-prefixes 10.20.8.0/27 \
  --delegations Microsoft.DBforPostgreSQL/flexibleServers
az network vnet subnet create -g $RG --vnet-name vnet-gpos -n snet-wg \
  --address-prefixes 10.20.9.0/28
AKS_SUBNET=$(az network vnet subnet show -g $RG --vnet-name vnet-gpos \
  -n snet-aks --query id -o tsv)

az acr create -g $RG -n $ACR --sku Basic

# AKS Standard tier, 1.36 (GA Jun 2026, EOL Jun 2027), one zone so
# Azure Disk PVs can re-attach to the other node, no auto-upgrades.
az aks create -g $RG -n $CL -l $LOC --tier standard \
  --kubernetes-version 1.36 \
  --network-plugin azure --network-plugin-mode overlay \
  --network-dataplane cilium --vnet-subnet-id "$AKS_SUBNET" \
  --pod-cidr 10.244.0.0/16 --service-cidr 10.0.0.0/16 \
  --dns-service-ip 10.0.0.10 \
  --nodepool-name main --node-vm-size Standard_D8as_v6 --node-count 2 \
  --zones 1 --max-pods 110 --node-osdisk-size 128 \
  --enable-oidc-issuer --enable-workload-identity --attach-acr $ACR \
  --auto-upgrade-channel none --node-os-upgrade-channel None \
  --api-server-authorized-ip-ranges "$ADMIN_IPS"

az postgres flexible-server create -g $RG -n $PG -l $LOC --version 18 \
  --tier Burstable --sku-name Standard_B2ms --storage-size 32 \
  --vnet vnet-gpos --subnet snet-pg \
  --private-dns-zone $PG.private.postgres.database.azure.com \
  --admin-user pgadmin --admin-password "$PG_ADMIN_PASSWORD"
# DBs: gpos, keycloak (+ SAM creates its three via db-init)

az storage account create -g $RG -n $SA -l $LOC --sku Standard_LRS \
  --allow-blob-public-access false --min-tls-version TLS1_2
az storage container create --account-name $SA -n sam-artifacts --auth-mode login

ISSUER=$(az aks show -g $RG -n $CL --query oidcIssuerProfile.issuerUrl -o tsv)
# SAM -> Blob
az identity create -g $RG -n id-sam
az identity federated-credential create -g $RG --identity-name id-sam \
  -n sam --issuer "$ISSUER" \
  --subject system:serviceaccount:sam-solace-lab:agent-mesh-solace-agent-mesh-sa
az role assignment create --role "Storage Blob Data Contributor" \
  --assignee "$(az identity show -g $RG -n id-sam --query principalId -o tsv)" \
  --scope "$(az storage account show -g $RG -n $SA --query id -o tsv)"
# cert-manager -> Azure DNS (DNS-01)
az network dns zone create -g $RG -n $ZONE
az identity create -g $RG -n id-cert-manager
az identity federated-credential create -g $RG --identity-name id-cert-manager \
  -n cert-manager --issuer "$ISSUER" \
  --subject system:serviceaccount:cert-manager:cert-manager
az role assignment create --role "DNS Zone Contributor" \
  --assignee "$(az identity show -g $RG -n id-cert-manager --query principalId -o tsv)" \
  --scope "$(az network dns zone show -g $RG -n $ZONE --query id -o tsv)"

# A records -> internal LB IPs (private, reachable only via the tunnel)
for h in sam auth gpos pos-grpc loyalty-grpc grafana; do
  az network dns record-set a add-record -g $RG -z $ZONE -n $h -a 10.20.0.250
done
az network dns record-set a add-record -g $RG -z $ZONE -n mqtt -a 10.20.0.251

# WireGuard gateway VM (booth router + developer peers), see report 6.3
# az vm create ... --size Standard_B2ats_v2 --subnet snet-wg --public-ip-sku Standard
# az network nic update ... --ip-forwarding true ; NSG: allow UDP 51820 only

# Planned maintenance: no node-OS / cluster maintenance around the fair
# az aks maintenanceconfiguration add ... (window outside 2027-02-12..20)
# Budget alert on the resource group
# az consumption budget create ...
