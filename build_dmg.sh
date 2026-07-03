#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

#######################################
# Config
#######################################
APP_NAME="Prowser"
INIT_PY="$SCRIPT_DIR/__init__.py"
APP_VERSION=$(python3 -c "
import importlib.util
import sys
spec = importlib.util.spec_from_file_location('prowser_init', sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(mod.__version__)
" "$INIT_PY")
if [ -z "$APP_VERSION" ]; then
  echo "❌ Error: could not read __version__ from $INIT_PY"
  exit 1
fi
VOLUME_NAME="Prowser Installer"

APP_PATH="/Applications/${APP_NAME}.app"
DMG_PATH="$HOME/Desktop/${APP_NAME}-${APP_VERSION}.dmg"

WORKDIR="/tmp/${APP_NAME}_dmg"
TEMP_DMG="/tmp/${APP_NAME}_rw.dmg"

# Paths to icons and background (same directory as this script / source folder)
VOL_ICON_ICNS="$SCRIPT_DIR/Prowser.icns"
BG_IMAGE="$SCRIPT_DIR/background.png"

# Pre-blessed source folder (custom icon applied once in Finder); override via env if needed
SOURCE_FOLDER="${SOURCE_FOLDER:-$SCRIPT_DIR/source_preblessed}"
mkdir -p "$SOURCE_FOLDER"

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

# Copy pre-blessed source folder into staging (icon preserved), then refresh project files.
SOURCE_STAGING="$WORKDIR/source"
if [ -d "$SOURCE_FOLDER" ]; then
    cp -R "$SOURCE_FOLDER" "$SOURCE_STAGING"
else
    echo "❌ Error: pre-blessed source folder not found at $SOURCE_FOLDER"
    echo "To create a folder with a custom icon, create $SOURCE_FOLDER and use Finder"
    echo "to assign an icon to it. (show info and drop name on the icon)"
    exit 1
fi

echo "Refreshing source tree from repo (copy_project_files.sh)..."
"$SCRIPT_DIR/copy_project_files.sh" -f "$SOURCE_STAGING"

# Ensure DMG source is runnable via setup.sh / run.sh
for sh in setup.sh run.sh pyInstallerBuild.sh build_dmg.sh copy_project_files.sh; do
    if [ -f "$SOURCE_STAGING/$sh" ]; then
        chmod +x "$SOURCE_STAGING/$sh"
    fi
done

if [ ! -f "$SOURCE_STAGING/main.py" ] || [ ! -f "$SOURCE_STAGING/setup.sh" ] || [ ! -d "$SOURCE_STAGING/browser_window" ]; then
    echo "❌ Error: source folder is incomplete after copy (need main.py, setup.sh, browser_window/)"
    exit 1
fi

# PyInstaller --min needs the same helper modules as a full bundle build.
PYINSTALLER_MIN_BUILD_PATHS=(
    pyInstallerBuild.sh
    pyinstaller_dependencies.py
    pyinstaller_build_directives.py
    pyinstaller_optional_packages.py
    pyinstaller_frozen_support.py
    pyinstaller_imagegen_paths.py
    pyinstaller_runtime_hook.py
    bundle_capabilities.py
    list_runtime_assets.py
    requirements_min.txt
    pyinstaller_hooks/hook-imagegen_plugins.py
    pyinstaller_hooks/hook-transformers.py
    pyinstaller_hooks/hook-requests.py
)
for req in "${PYINSTALLER_MIN_BUILD_PATHS[@]}"; do
    if [ ! -e "$SOURCE_STAGING/$req" ]; then
        echo "❌ Error: source folder missing $req (required for ./pyInstallerBuild.sh --min)"
        exit 1
    fi
done

if [ ! -f "$APP_PATH/Contents/MacOS/Prowser" ]; then
    echo "❌ Error: built app not found at $APP_PATH — run ./pyInstallerBuild.sh first"
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

        -- Source folder: icon view sized to background.png (640x480)
        if exists folder "source" then
            tell folder "source"
                open
                delay 1

                set sourceWindow to container window
                set current view of sourceWindow to icon view
                set toolbar visible of sourceWindow to false
                set statusbar visible of sourceWindow to false
                set bounds of sourceWindow to {100, 100, 740, 580}

                set sourceViewOptions to the icon view options of sourceWindow
                set arrangement of sourceViewOptions to not arranged
                set icon size of sourceViewOptions to 64
                set background picture of sourceViewOptions to file "background.png"

                close sourceWindow
            end tell
            update without registering applications
            delay 1
        end if
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
