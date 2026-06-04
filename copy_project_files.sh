#!/bin/bash

# Script to copy all necessary files for Image Browser project to a new directory
# Usage: ./copy_project_files.sh [-f] <target_directory>
#        ./copy_project_files.sh -h | --help

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Function to print help and exit
print_help() {
    cat <<EOF
Usage: $0 [-f] <target_directory>
Copies all necessary Image Browser project files to <target_directory>.

Options:
  -h, --help    Show this help message and exit.
  -f            Force reuse of target directory if it exists; do not prompt.

Example:
  $0 ../image_browser_clean
  $0 -f ../image_browser_clean
EOF
    exit 0
}

# Function to empty the target directory
empty_target_dir() {
    local dir="$1"
    # Remove *.png, *.py, *.md, *.icns, *.txt, *.plist, *.sh, *.svg (recursively), and all subdirs (leave $dir itself)
    find "$dir" -type f \( -name "*.png" -o -name "*.py" -o -name "*.md" -o -name "*.icns" -o -name "*.txt" -o -name "*.plist" -o -name "*.sh" -o -name "*.svg" -o -name "*.php" -o -name "LICENSE" \) -exec rm -f {} +
    find "$dir" -mindepth 1 -type d -exec rm -rf {} +
    print_success "Target directory emptied"
}

# Default values
FORCE_REUSE=0

# Parse parameters (simple approach for one optional flag and one positional param)
POSITIONAL=()
while [[ $# -gt 0 ]]; do
    key="$1"
    case $key in
        -h|--help)
            print_help
            ;;
        -f)
            FORCE_REUSE=1
            shift
            ;;
        -*)
            print_error "Unknown option: $1"
            exit 1
            ;;
        *)
            POSITIONAL+=("$1") # Save positional argument
            shift
            ;;
    esac
done

# Handle positional parameters
if [ ${#POSITIONAL[@]} -eq 0 ]; then
    print_error "Target directory is required!"
    echo "Usage: $0 [-f] <target_directory>"
    echo "Example: $0 ../image_browser_clean"
    exit 1
fi

TARGET_DIR="${POSITIONAL[0]}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Convert to absolute path
if [[ ! "$TARGET_DIR" = /* ]]; then
    TARGET_DIR="$(cd "$(dirname "$TARGET_DIR")" && pwd)/$(basename "$TARGET_DIR")"
fi

print_info "Source directory: $SCRIPT_DIR"
print_info "Target directory: $TARGET_DIR"

# Check if source directory contains main.py
if [ ! -f "$SCRIPT_DIR/main.py" ]; then
    print_error "Source directory does not appear to be the image_browser project (main.py not found)"
    exit 1
fi

# Create or empty target directory as needed
if [ ! -d "$TARGET_DIR" ]; then
    print_info "Creating target directory: $TARGET_DIR"
    mkdir -p "$TARGET_DIR"
else
    print_warning "Target directory already exists: $TARGET_DIR"
    if [ "$FORCE_REUSE" -eq 1 ]; then
        print_info "Force flag set. Emptying target directory: $TARGET_DIR"
        empty_target_dir "$TARGET_DIR"
    else
        read -p "Empty the target directory and reuse it? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_info "Operation cancelled. Exiting..."
            exit 0
        else
            print_info "Emptying target directory: $TARGET_DIR"
            empty_target_dir "$TARGET_DIR"
        fi
    fi
fi

# Function to copy file with error handling
copy_file() {
    local source_file="$1"
    local target_file="$2"
    
    if [ ! -f "$source_file" ]; then
        print_warning "Source file not found: $source_file (skipping)"
        return 1
    fi
    
    # Create target directory if needed
    local target_dir=$(dirname "$target_file")
    if [ ! -d "$target_dir" ]; then
        mkdir -p "$target_dir"
    fi
    
    cp "$source_file" "$target_file"
    return 0
}

# Counter for copied files
COPIED_COUNT=0
SKIPPED_COUNT=0

# Function to copy and count (optionally, second arg is target filename)
copy_and_count() {
    local relative_source="$1"
    local relative_target="${2:-$1}"

    local source="$SCRIPT_DIR/$relative_source"
    local target="$TARGET_DIR/$relative_target"
    
    if copy_file "$source" "$target"; then
        ((COPIED_COUNT++))
        print_info "Copied: $relative_source -> $relative_target"
    else
        ((SKIPPED_COUNT++))
    fi
}

print_info "Starting file copy operation..."
echo

# Core Source Files - Entry Points
print_info "Copying entry point files..."
copy_and_count "main.py"
copy_and_count "print_log_redirect.py"
copy_and_count "run.sh"
copy_and_count "__init__.py"

# Core Application
print_info "Copying core application files..."
copy_and_count "image_browser_window.py"
copy_and_count "config.py"
copy_and_count "utils.py"
copy_and_count "thumbnail_constants.py"
copy_and_count "file_data_model.py"
copy_and_count "sort_mode.py"
copy_and_count "path_exclusions.py"
copy_and_count "photos_library_paths.py"
copy_and_count "idle_and_cache_constants.py"
copy_and_count "image_extensions_helpers.py"
copy_and_count "pil_image_io.py"
copy_and_count "macos_process.py"
copy_and_count "thumbnail_cache_key.py"
copy_and_count "background_thumbnail_cache.py"
copy_and_count "worker_image_loader.py"
copy_and_count "window_background_workers.py"
copy_and_count "window_event_filters.py"

# UI Components
print_info "Copying UI component files..."
copy_and_count "preview_widget.py"
copy_and_count "combined_sidebar_widget.py"
copy_and_count "sidebar_jobs_widget.py"
copy_and_count "thumbnail_context_menu.py"
copy_and_count "about_dialog.py"
copy_and_count "settings_dialog.py"
copy_and_count "status_notification.py"
copy_and_count "status_bar_config.py"
copy_and_count "screen_size_copy.py"

# Theming
print_info "Copying theme files..."
copy_and_count "theme.py"
copy_and_count "theme_base.py"
copy_and_count "theme_defaults.py"
copy_and_count "theme_service.py"
copy_and_count "dark_theme_definitions.py"
copy_and_count "light_theme_definitions.py"

# Managers
print_info "Copying manager files..."
copy_and_count "navigation_manager.py"
copy_and_count "thumbnail_operations_manager.py"
copy_and_count "thumbnail_canvas.py"
copy_and_count "file_operations_manager.py"
copy_and_count "menu_manager.py"
copy_and_count "view_manager.py"
copy_and_count "canvas_manager.py"
copy_and_count "cursor_manager.py"
copy_and_count "keyboard_handler.py"
copy_and_count "event_handler.py"
copy_and_count "selection_manager.py"
copy_and_count "sorting_manager.py"
copy_and_count "sidebar_manager.py"
copy_and_count "view_mode_manager.py"
copy_and_count "ui_layout_manager.py"
copy_and_count "thumbnail_display_manager.py"
copy_and_count "image_display_manager.py"
copy_and_count "refresh_manager.py"
copy_and_count "similarity_search_manager.py"
copy_and_count "similarity_bootstrap.py"
copy_and_count "similarity_reorder.py"
copy_and_count "configuration_sync_manager.py"
copy_and_count "mvc_controller.py"
copy_and_count "event_bus.py"
copy_and_count "reset_date_dialog.py"
copy_and_count "background_clip_controller.py"
# Features
print_info "Copying feature files..."
copy_and_count "slideshow_manager.py"
copy_and_count "slideshow2_manager.py"
copy_and_count "slideshow3_manager.py"
copy_and_count "slideshow_image_loader.py"
copy_and_count "wallpaper_manager.py"
copy_and_count "external_editor.py"
copy_and_count "file_tree_handler.py"
copy_and_count "directory_history_handler.py"
copy_and_count "directory_loader.py"
copy_and_count "drag_drop_manager.py"
copy_and_count "file_move_handler.py"
copy_and_count "browse_view_handler.py"
copy_and_count "convert_format.py"
copy_and_count "resize_images.py"
copy_and_count "help_dialog.py"
copy_and_count "markdown_dialog.py"
copy_and_count "filter_dialog.py"
copy_and_count "lock_manager.py"
copy_and_count "information_sidebar.py"
copy_and_count "help_api.py"
copy_and_count "help_command_line.py"
copy_and_count "help_pf.py"
copy_and_count "help_why.py"
copy_and_count "help_downloading_models.py"
copy_and_count "find_references_dialog.py"
copy_and_count "reference_graph.py"
copy_and_count "reference_graph_layout.py"
copy_and_count "background_clip_worker.py"
copy_and_count "background_cache_importer.py"

# Face recognition
print_info "Copying face recognition files..."
copy_and_count "face_engine.py"
copy_and_count "face_cache.py"
copy_and_count "face_sample_cache.py"
copy_and_count "face_sample_thumbnail.py"
copy_and_count "face_scan_runner.py"
copy_and_count "face_gathering_coordinator.py"
copy_and_count "known_faces_manager.py"
copy_and_count "face_assign_dialog.py"
copy_and_count "quick_person_search.py"
copy_and_count "quick_person_face_pick_dialog.py"

# Image Processing
print_info "Copying image processing files..."
copy_and_count "image_cache.py"
copy_and_count "exif_image_loader.py"
copy_and_count "cr2_raw_loader.py"

# Local image generation plugins (Create menu; mflux in minimal_requirements.txt)
print_info "Copying imagegen_plugins package..."
if [ -d "$SCRIPT_DIR/imagegen_plugins" ]; then
    mkdir -p "$TARGET_DIR/imagegen_plugins"
    if cp -R "$SCRIPT_DIR/imagegen_plugins/." "$TARGET_DIR/imagegen_plugins/"; then
        ((COPIED_COUNT++))
        print_info "Copied: imagegen_plugins/ (package tree)"
    else
        ((SKIPPED_COUNT++))
        print_warning "Failed to copy imagegen_plugins/"
    fi
else
    print_warning "imagegen_plugins/ not found (skipping)"
    ((SKIPPED_COUNT++))
fi

if [ -d "$SCRIPT_DIR/pyinstaller_hooks" ]; then
    mkdir -p "$TARGET_DIR/pyinstaller_hooks"
    if cp -R "$SCRIPT_DIR/pyinstaller_hooks/." "$TARGET_DIR/pyinstaller_hooks/"; then
        ((COPIED_COUNT++))
        print_info "Copied: pyinstaller_hooks/"
    fi
fi
if [ -f "$SCRIPT_DIR/pyinstaller_imagegen_paths.py" ]; then
    copy_and_count "pyinstaller_imagegen_paths.py"
fi
copy_and_count "pyinstaller_frozen_support.py"

# Model tasks worker (image generation + LM Studio captions)
print_info "Copying model tasks files..."
copy_and_count "model_tasks_controller.py"
copy_and_count "model_tasks_launch.py"
copy_and_count "model_tasks_worker.py"

# macOS Integration
print_info "Copying macOS integration files..."
copy_and_count "apple_events_handler.py"
copy_and_count "undo_applescript_fix.py"

# Utilities & Fixes
print_info "Copying utility files..."
copy_and_count "beachball_fix.py"
copy_and_count "debug_log.py"
copy_and_count "tooltip_popup_utils.py"
copy_and_count "qt_key_debug.py"
copy_and_count "message_handler.py"
copy_and_count "idle_detector.py"
copy_and_count "map_manager.py"
copy_and_count "cnn_image_similarity_sorter.py"
copy_and_count "feature_cache_manager.py"
copy_and_count "cache_prepopulator.py"
copy_and_count "rename_status_manager.py"
copy_and_count "reset_exif_dialog.py"
copy_and_count "delete_exif_dialog.py"
copy_and_count "list_canvas_manager.py"
copy_and_count "list_canvas.py"
copy_and_count "right_sidebar_combined.py"
copy_and_count "shortcuts_sidebar.py"
copy_and_count "exif_utils.py"
copy_and_count "speech_utils.py"
copy_and_count "edit_exif_usercomment_dialog.py"
copy_and_count "lmstudio_caption.py"
copy_and_count "lmstudio_flux_prompt.py"
copy_and_count "lmstudio_launcher.py"
copy_and_count "random_images_from_recents.py"

# Build Scripts
print_info "Copying build scripts..."
copy_and_count "pyInstallerBuild.sh"
copy_and_count "build_dmg.sh"
copy_and_count "make_icns.sh"
copy_and_count "copy_project_files.sh"
copy_and_count "setup.sh"
copy_and_count "create_sample_images.py"
copy_and_count ".gitignore"
copy_and_count "pyinstaller_runtime_hook.py"

# Assets referenced at runtime (theme stylesheets, sidebars, Create menu, placeholders)
print_info "Copying asset files..."
copy_and_count "assets/checkbox_x.svg"
copy_and_count "assets/radio_dot.svg"
copy_and_count "assets/combo_arrow.svg"
copy_and_count "assets/gear.svg"
copy_and_count "assets/gear_hover.svg"
copy_and_count "assets/trash_icon.svg"
copy_and_count "assets/trash_icon_hover.svg"
copy_and_count "assets/trash_icon.png"
copy_and_count "assets/trash_icon_info.png"
copy_and_count "assets/beachball.png"
copy_and_count "assets/noimage.svg"
copy_and_count "assets/padlock.png"
copy_and_count "assets/qmark.png"
copy_and_count "assets/skip_cooldown_icon.png"
copy_and_count "assets/edit_icon.png"
copy_and_count "assets/edit_icon_hover.png"
copy_and_count "assets/expansion_template.webp"
copy_and_count "assets/series_plus_icon.png"
copy_and_count "assets/series_plus_icon_hover.png"
copy_and_count "assets/series_minus_icon.png"
copy_and_count "assets/series_minus_icon_hover.png"
copy_and_count "assets/series_refinement_icon.png"
copy_and_count "assets/series_refinement_icon_hover.png"
copy_and_count "assets/series_refinement_icon_active.png"
copy_and_count "assets/series_refinement_icon_active_hover.png"

# Resource Files
print_info "Copying resource files..."
copy_and_count "Prowser.icns"
copy_and_count "document.icns"
copy_and_count "background.png"
copy_and_count "Info.plist"

# Configuration Files
print_info "Copying configuration files..."
copy_and_count "minimal_requirements.txt"
copy_and_count "minimal_requirements.txt" "requirements.txt"
copy_and_count "LICENSE"
copy_and_count "README.md"
copy_and_count "KEYBOARD.md"
copy_and_count "API.md"
copy_and_count "IMAGE_CREATE_PLUGINS.md"

echo
print_success "File copy operation completed!"
echo
echo "Summary:"
echo "  Files copied: $COPIED_COUNT"
echo "  Files skipped: $SKIPPED_COUNT"
echo "  Target directory: $TARGET_DIR"
echo
print_info "Next steps:"
echo "  1. cd $TARGET_DIR"
echo "  2. chmod +x setup.sh pyInstallerBuild.sh build_dmg.sh run.sh"
echo "  3. ./setup.sh  (to create virtual environment and install dependencies)"
echo "  4. ./run.sh  (to run the application)"
echo "  5. ./pyInstallerBuild.sh  (to build macOS app bundle)"
echo

