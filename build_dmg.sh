#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

#######################################
# Config
#######################################
APP_NAME="Prowser"
APP_VERSION="0.9.0"
VOLUME_NAME="Prowser Installer"

APP_PATH="/Applications/${APP_NAME}.app"
DMG_PATH="$HOME/Desktop/${APP_NAME}-${APP_VERSION}.dmg"

WORKDIR="/tmp/${APP_NAME}_dmg"
TEMP_DMG="/tmp/${APP_NAME}_rw.dmg"

# Paths to icons and background (same directory as this script / source folder)
VOL_ICON_ICNS="$SCRIPT_DIR/Prowser.icns"
BG_IMAGE="$SCRIPT_DIR/background.png"

# Pre-blessed source folder (custom icon applied once in Finder); override via env if needed
SOURCE_FOLDER="${SOURCE_FOLDER:-$HOME/dev/testchat/source_preblessed}"

#######################################
# Clean previous runs
#######################################
rm -rf "$WORKDIR" "$TEMP_DMG" "$DMG_PATH"

# Force-unmount stale volume
if mount | grep -q "/Volumes/$VOLUME_NAME"; then
  hdiutil detach -force "/Volumes/$VOLUME_NAME" || true
  sleep 1
fi

#######################################
# Staging folder
#######################################
mkdir -p "$WORKDIR/.background"

# Copy app and Applications link
cp -R "$APP_PATH" "$WORKDIR/"
ln -s /Applications "$WORKDIR/Applications"

# Copy pre-blessed source folder into staging (icon preserved)
if [ -d "$SOURCE_FOLDER" ]; then
    cp -R "$SOURCE_FOLDER" "$WORKDIR/source"
    "$SCRIPT_DIR/copy_project_files.sh" "$WORKDIR/source" -f
else
    echo "❌ Error: pre-blessed source folder not found at $SOURCE_FOLDER"
    echo "To create a folder with a custom icon, create $SOURCE_FOLDER and use Finder"
    echo "to assign an icon to it. (show info and drop name on the icon)"
    exit 1
fi

# Copy background and volume icon
cp "$BG_IMAGE" "$WORKDIR/.background/background.png"
cp "$VOL_ICON_ICNS" "$WORKDIR/.VolumeIcon.icns"

# Hide helper files in staging
SetFile -a V "$WORKDIR/.background"
SetFile -a V "$WORKDIR/.VolumeIcon.icns"

#######################################
# Create RW DMG
#######################################
hdiutil create -ov \
  -volname "$VOLUME_NAME" \
  -srcfolder "$WORKDIR" \
  -fs HFS+ \
  -format UDRW \
  "$TEMP_DMG"

#######################################
# Mount RW DMG
#######################################
DEVICE=$(hdiutil attach \
  -readwrite \
  -owners on \
  -noverify \
  -noautoopen \
  "$TEMP_DMG" | awk '/^\/dev\/disk[0-9]+/ {print $1; exit}')

MOUNT="/Volumes/$VOLUME_NAME"
sleep 2

#######################################
# Set Volume Icon
#######################################
cp "$VOL_ICON_ICNS" "$MOUNT/.VolumeIcon.icns"
SetFile -a C "$MOUNT"   # marks volume as having custom icon
SetFile -a V "$MOUNT/.VolumeIcon.icns"  # hide volume icon file

#######################################
# Finder layout + background
#######################################
osascript <<EOF
tell application "Finder"
    tell disk "$VOLUME_NAME"
        open
        delay 1

        set containerWindow to container window
        set current view of containerWindow to icon view

        set toolbar visible of containerWindow to false
        set statusbar visible of containerWindow to false
        set bounds of containerWindow to {100, 100, 740, 580}

        set viewOptions to the icon view options of containerWindow
        set arrangement of viewOptions to not arranged
        set icon size of viewOptions to 120
        set background picture of viewOptions to file ".background:background.png"

        set position of item "$APP_NAME.app" to {200, 150}
        set position of item "Applications" to {400, 150}
        if exists item "source" then
            set position of item "source" to {200, 310}
        end if

        update without registering applications
        delay 2
        close containerWindow
    end tell
end tell
EOF

#######################################
# Finalize DMG
#######################################
sync
sleep 2

# Detach safely
hdiutil detach "$DEVICE"

# Compress final DMG
hdiutil convert "$TEMP_DMG" -format UDZO -imagekey zlib-level=9 -o "$DMG_PATH"
rm -f "$TEMP_DMG"

echo "✅ DMG created: $DMG_PATH"
