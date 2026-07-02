#!/bin/bash

# ===============================
# Connector Designer Deployment Script
# ===============================

LOG_DIR="./deploy-logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/run-$(date +"%Y-%m-%d_%H-%M").log"

log() {
  echo "$1" | tee -a "$LOG_FILE"
}

log "==============================="
log "   Connector Deployment Start  "
log "   Timestamp: $(date)         "
log "==============================="


echo "Select runtime:"
echo "1) Docker"
echo "2) Podman"
read -p "Enter choice (1/2): " CHOICE

if [ "$CHOICE" = "1" ]; then
  RUNTIME="docker"
  VOLUME_SUFFIX=""
  SERVICE_IMAGE="connector_designer_services"

elif [ "$CHOICE" = "2" ]; then
  RUNTIME="podman"
  VOLUME_SUFFIX=":z"
  SERVICE_IMAGE="connector_designer_services:latest"

else
  log "❌ Invalid choice, exiting."
  exit 1
fi

log "🛠 Using runtime: $RUNTIME"


# ===============================
# Step 1: Load Service Image If Missing
# ===============================

SERVICE_TAR="connector_designer_services.tar"

log "🔍 Checking image file: $SERVICE_TAR"

if [ -f "$SERVICE_TAR" ]; then

  if [ "$RUNTIME" = "docker" ]; then

    if $RUNTIME images | grep -q "connector_designer_services"; then
      log "✔ Image already exists (Docker)."
    else
      log "📦 Loading service image..."
      $RUNTIME load -i "$SERVICE_TAR" 2>&1 | tee -a "$LOG_FILE"
    fi

  else # PODMAN
    if $RUNTIME images | grep -q "$SERVICE_IMAGE"; then
      log "✔ Image already exists (Podman)."
    else
      log "📦 Loading service image (Podman)..."
      LOAD_OUTPUT=$($RUNTIME load -i "$SERVICE_TAR")
      log "$LOAD_OUTPUT"

      # Assign tag properly
      LOADED_NAME=$(echo "$LOAD_OUTPUT" | sed -n 's/Loaded image(s): //p')
      $RUNTIME tag "$LOADED_NAME" "$SERVICE_IMAGE"
      log "🔖 Tagged: $LOADED_NAME → $SERVICE_IMAGE"
    fi
  fi

else
  log "⚠ Image file '$SERVICE_TAR' missing — skipping load."
fi


# ===============================
# Step 2: Create Network if missing
# ===============================
if ! $RUNTIME network inspect cd-network >/dev/null 2>&1; then
  log "🌐 Creating network cd-network..."
  $RUNTIME network create cd-network 2>&1 | tee -a "$LOG_FILE"
else
  log "✔ Network cd-network already exists."
fi


# ===============================
# Step 3: Run Backend App Container Only
# ===============================
log "🚀 Starting Connector Designer Service..."

$RUNTIME rm -f connector_designer_services >/dev/null 2>&1

CMD_SERVICE="$RUNTIME run -d \
  --name connector_designer_services \
  --network cd-network \
  -p 6002:6002 \
  -v $(pwd)/artifacts:/app/dist/bin/artifacts$VOLUME_SUFFIX \
  -v $(pwd)/logs/cd:/app/dist/bin/logs/cd$VOLUME_SUFFIX \
  -v $(pwd)/env/cd-services.env:/app/dist/bin/.env$VOLUME_SUFFIX \
  -v $(pwd)/../cli:/app/cli$VOLUME_SUFFIX \
  --restart=always \
  $SERVICE_IMAGE"

log "📌 Executing: $CMD_SERVICE"
eval $CMD_SERVICE 2>&1 | tee -a "$LOG_FILE"


# ===============================
# Final Summary
# ===============================
log ""
log "🎉 Deployment Complete!"
log "📍 Logs saved to: $LOG_FILE"
log ""

$RUNTIME ps | tee -a "$LOG_FILE"

log "==============================="
log "           DONE               "
log "==============================="
