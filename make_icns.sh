#!/bin/bash

# Converts a PNG to an icns file containing only 128x128 and 64x64 icons.
# The PNG must have transparency preserved.
# Usage: ./make_icns.sh [-s source_png] [-i app_name]

APP_NAME="Prowser"
# APP_NAME="ShowHideIcons.sh"
DEFAULT_SRC="/Users/douglasnadel/dev/testchat/image_browser/imagegen-1687.png"
SRC="$DEFAULT_SRC"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -i)
            if [ -z "$2" ]; then
                echo "Error: -i (image) requires a source PNG path"
                echo "Usage: ./make_icns.sh [-i source_png] [-a app_name]"
                exit 1
            fi
            SRC="$2"
            shift 2
            ;;
        -a)     
            if [ -z "$2" ]; then
                echo "Error: -a (app) requires an app name"
                echo "Usage: ./make_icns.sh [-i source_png] [-a app_name]"
                exit 1
            fi
            APP_NAME="$2"
            shift 2
            ;;
        -h)
            echo "Usage: ./make_icns.sh [-i source_png] [-a app_name]"
            echo "app name is without .app extension"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: ./make_icns.sh [-i source_png] [-a app_name]"
            exit 1
            ;;
    esac
done

ICONSET="${APP_NAME}icon.iconset"
ICNS="${APP_NAME}.icns"

# Dynamically find the app bundle location (check ~/Applications first, then /Applications)
APP_PATH=""
if [ -d "$HOME/Applications/${APP_NAME}.app" ]; then
    APP_PATH="$HOME/Applications/${APP_NAME}.app"
elif [ -d "/Applications/${APP_NAME}.app" ]; then
    APP_PATH="/Applications/${APP_NAME}.app"
fi

# Dynamically determine the icon path within the bundle
APP_ICON_PATH=""
if [ -n "$APP_PATH" ]; then
    # Check for APP_NAME.icns first, then icon.icns
    if [ -f "$APP_PATH/Contents/Resources/${APP_NAME}.icns" ]; then
        APP_ICON_PATH="$APP_PATH/Contents/Resources/${APP_NAME}.icns"
    elif [ -f "$APP_PATH/Contents/Resources/icon.icns" ]; then
        APP_ICON_PATH="$APP_PATH/Contents/Resources/icon.icns"
    else
        # Default to APP_NAME.icns if neither exists (for new installations)
        APP_ICON_PATH="$APP_PATH/Contents/Resources/${APP_NAME}.icns"
    fi
fi


# Verify source PNG exists
if [ ! -f "$SRC" ]; then
    echo "Error: Source PNG '$SRC' does not exist."
    exit 1
fi

# Clean up any existing iconset folder or icns file
rm -rf "$ICONSET" "$ICNS"

mkdir "$ICONSET"

# Create 128x128 and 64x64 PNGs for the iconset
sips -z 128 128 "$SRC" --out "$ICONSET/icon_128x128.png"
sips -z 64 64 "$SRC" --out "$ICONSET/icon_64x64.png"

# Generate the .icns file from the iconset
iconutil -c icns "$ICONSET" -o "$ICNS"

# Clean up the iconset folder
rm -rf "$ICONSET"

echo "Created $ICNS with 128x128 and 64x64 icon images."

# Replace the default app icon in the app bundle (if it exists)

echo "looking for app at $APP_PATH"
if [ -n "$APP_PATH" ] && [ -d "$APP_PATH" ]; then
    echo "$APP_NAME found at: $APP_PATH"
    # Backup the existing icon if it exists
    if [ -f "$APP_ICON_PATH" ]; then
        sudo cp "$APP_ICON_PATH" "$APP_ICON_PATH.bak"
        echo "Existing app icon backed up to $APP_ICON_PATH.bak"
    fi
    # Copy the new icon into place
    sudo cp "$ICNS" "$APP_ICON_PATH"
    echo "Updated icon in $APP_ICON_PATH"

    # Resign the app (if codesign is available and needed)
    if sudo codesign --verify --deep --strict "$APP_PATH" 2>/dev/null; then
        echo "Resigning app bundle after icon update..."
        sudo codesign --force --deep --sign - "$APP_PATH"
        echo "App re-signed with ad-hoc identity."
    else
        echo "App was not previously signed, or verification not possible. Skipping re-sign."
    fi

    # Touch the app so Finder refreshes the icon
    sudo touch "$APP_PATH"
    echo "App bundle updated. If the icon does not immediately update in Finder, log out and back in, or run 'killall Finder' to refresh icons."
else
    echo "$APP_NAME not found in ~/Applications or /Applications. Skipping app icon update."
fi

# Open the app bundle location in Finder if found
if [ -n "$APP_PATH" ] && [ -d "$APP_PATH" ]; then
    open -R "$APP_PATH"
fi
