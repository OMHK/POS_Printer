#!/bin/bash
# Redeploy thermal-print-webapp on HomeServer from the git repo.
# Run this ON HomeServer, from inside the repo checkout:
#   cd ~/thermal-print-webapp && ./deploy.sh
#
# Templates and usb_devices.json are NOT baked into the image - they're
# bind-mounted from ~/thermal-print-data/ so edits made live via the web
# app's "Manage Templates" tab survive rebuilds/restarts. See the
# "data persistence" note in Printing_Closet_Setup.md before changing this.
set -euo pipefail

DATA_DIR="$HOME/thermal-print-data"
CONTAINER_NAME="thermal-print-webapp"
IMAGE_NAME="thermal-print-webapp"

echo "==> Pulling latest code"
git pull

echo "==> Building image"
docker build -t "$IMAGE_NAME" .

echo "==> Restarting container"
docker stop "$CONTAINER_NAME" 2>/dev/null || true
docker rm "$CONTAINER_NAME" 2>/dev/null || true
docker run -d \
  --name "$CONTAINER_NAME" \
  --network host \
  --restart unless-stopped \
  -v "$DATA_DIR/templates:/app/templates" \
  -v "$DATA_DIR/usb_devices.json:/app/usb_devices.json" \
  "$IMAGE_NAME"

echo "==> Health check"
sleep 2
CODE=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:5051/)
if [ "$CODE" = "200" ]; then
  echo "OK - serving HTTP $CODE"
else
  echo "WARNING - got HTTP $CODE, check 'docker logs $CONTAINER_NAME'"
  exit 1
fi
