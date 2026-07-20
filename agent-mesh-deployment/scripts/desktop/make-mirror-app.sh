#!/bin/bash
set -euo pipefail

# =============================================================
# make-mirror-app.sh -- build "SAM K8s.app", a 1:1 mirror of the
# local Kubernetes SAM WebUI as a macOS app.
# =============================================================
# The app opens https://sam.solace.lab in a Chrome app-mode
# window (frameless, own Dock icon). It shares the regular
# Chrome profile, so the Keycloak session carries over -- the
# window is always a live view of the K8s deployment, with zero
# local runtime and zero mesh side effects.
#
# Rationale: the Solace desktop app has no remote/server mode in
# 2.225.14 (it always boots its embedded environment), so the
# clean "mirror" is a browser app window -- analogous to the
# browser, packaged for the Dock.
# =============================================================

APP_NAME="SAM K8s"
SAM_URL="${SAM_URL:-https://sam.solace.lab}"
APP="$HOME/Applications/$APP_NAME.app"
SOLACE_APP_ICON="/Applications/Solace Agent Mesh.app/Contents/Resources/appicon.icns"

mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key><string>sam-k8s</string>
  <key>CFBundleName</key><string>SAM K8s</string>
  <key>CFBundleDisplayName</key><string>SAM K8s</string>
  <key>CFBundleIdentifier</key><string>lab.solace.sam-k8s-mirror</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleIconFile</key><string>appicon</string>
  <key>LSUIElement</key><false/>
</dict>
</plist>
PLIST

cat > "$APP/Contents/MacOS/sam-k8s" <<SCRIPT
#!/bin/bash
# SAM K8s mirror: live view of the local Kubernetes SAM WebUI.
exec open -na "Google Chrome" --args --app=$SAM_URL
SCRIPT
chmod +x "$APP/Contents/MacOS/sam-k8s"

if [ -f "$SOLACE_APP_ICON" ]; then
  cp "$SOLACE_APP_ICON" "$APP/Contents/Resources/appicon.icns"
fi
touch "$APP"

echo "Built: $APP  (opens $SAM_URL as a Chrome app window)"
echo "Launch with:  open \"$APP\"   -- drag it to the Dock to pin it."
