#!/bin/bash

# Copy all files needed to run Prowser from source (setup.sh + run.sh).
# Usage: ./copy_project_files.sh [-f] <target_directory>
#        ./copy_project_files.sh -h | --help

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_error() { echo -e "${RED}[ERROR]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }

print_help() {
    cat <<EOF
Usage: $0 [-f] <target_directory>
Copies all necessary Prowser project files to <target_directory>.

Options:
  -h, --help    Show this help message and exit.
  -f            Force reuse of target directory if it exists; do not prompt.

Example:
  $0 ../image_browser_clean
  $0 -f /path/to/dmg/source
EOF
    exit 0
}

# Feature packages (post-restructure layout; see docs/restructure-plan.md).
FEATURE_PACKAGES=(
    browser_window
    slideshow
    theme
    exif
    search
    cache
    faces
    workers
    files
    thumbnails
    settings
    imagegen_plugins
    pyinstaller_hooks
)

# Root-level Python files that are dev-only — not shipped in source copies.
ROOT_PY_EXCLUDE=(
    block_test.py
    defsize.py
    fast_test.py
    gemma4_voice_vision_demo.py
    generate_minimal_requirements.py
    generate_minimal_requirements_questionable.py
    hfmodels.py
    jit_test.py
    random_images_launcher.py
    send_one_file.py
)

# Required after copy (paths relative to target).
REQUIRED_PATHS=(
    main.py
    image_browser_window.py
    event_bus.py
    sorting_manager.py
    minimal_requirements.txt
    setup.sh
    run.sh
    browser_window/__init__.py
)

# Required for ./pyInstallerBuild.sh (including --min minimal bundles).
PYINSTALLER_BUILD_PATHS=(
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
    Prowser.icns
)

COPIED_COUNT=0
SKIPPED_COUNT=0

bump_copied() { COPIED_COUNT=$((COPIED_COUNT + 1)); }
bump_skipped() { SKIPPED_COUNT=$((SKIPPED_COUNT + 1)); }

empty_target_dir() {
    local dir="$1"
    # Preserve local venv trees (setup.sh creates venv_image_browser here).
    find "$dir" \
        \( -path "$dir/venv_image_browser" -o -path "$dir/venv_image_browser/*" \
           -o -path "$dir/venv_pyinstaller" -o -path "$dir/venv_pyinstaller/*" \
           -o -path "$dir/venv" -o -path "$dir/venv/*" \) -prune \
        -o -type f \( -name "*.png" -o -name "*.py" -o -name "*.md" -o -name "*.icns" \
           -o -name "*.txt" -o -name "*.plist" -o -name "*.sh" -o -name "*.svg" \
           -o -name "*.php" -o -name "LICENSE" -o -name ".gitignore" \) -exec rm -f {} +
    find "$dir" -mindepth 1 -maxdepth 1 -type d \
        ! -name venv_image_browser ! -name venv_pyinstaller ! -name venv \
        -exec rm -rf {} +
    print_success "Target directory emptied (venvs preserved)"
}

copy_file() {
    local source_file="$1"
    local target_file="$2"

    if [ ! -f "$source_file" ]; then
        print_warning "Source file not found: $source_file (skipping)"
        bump_skipped
        return 0
    fi

    mkdir -p "$(dirname "$target_file")"
    cp "$source_file" "$target_file"
    bump_copied
    return 0
}

copy_and_count() {
    local relative_source="$1"
    local relative_target="${2:-$1}"
    copy_file "$SCRIPT_DIR/$relative_source" "$TARGET_DIR/$relative_target"
    print_info "Copied: $relative_source -> $relative_target"
}

copy_package_tree() {
    local pkg="$1"
    local src="$SCRIPT_DIR/$pkg"
    local dst="$TARGET_DIR/$pkg"

    if [ ! -d "$src" ]; then
        print_warning "$pkg/ not found (skipping)"
        bump_skipped
        return 0
    fi

    mkdir -p "$dst"
    if command -v rsync &>/dev/null; then
        rsync -a --exclude '__pycache__' --exclude '*.pyc' --exclude '.DS_Store' "$src/" "$dst/"
    else
        cp -R "$src/." "$dst/"
        find "$dst" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
        find "$dst" -name '*.pyc' -delete 2>/dev/null || true
    fi
    bump_copied
    print_info "Copied: $pkg/ (package tree)"
}

copy_root_python_modules() {
    print_info "Copying root Python modules..."
    local exclude
    for py in "$SCRIPT_DIR"/*.py; do
        [ -f "$py" ] || continue
        local base
        base=$(basename "$py")
        for exclude in "${ROOT_PY_EXCLUDE[@]}"; do
            if [ "$base" = "$exclude" ]; then
                continue 2
            fi
        done
        copy_file "$py" "$TARGET_DIR/$base"
        print_info "Copied: $base"
    done
}

make_scripts_executable() {
    print_info "Making shell scripts executable..."
    local sh
    for sh in setup.sh run.sh pyInstallerBuild.sh build_dmg.sh copy_project_files.sh make_icns.sh; do
        if [ -f "$TARGET_DIR/$sh" ]; then
            chmod +x "$TARGET_DIR/$sh"
        fi
    done
}

verify_copy() {
    print_info "Verifying copied project..."
    local missing=0
    local req
    for req in "${REQUIRED_PATHS[@]}" "${PYINSTALLER_BUILD_PATHS[@]}"; do
        if [ ! -e "$TARGET_DIR/$req" ]; then
            print_error "Missing required path: $req"
            missing=1
        fi
    done
    if [ "$missing" -ne 0 ]; then
        return 1
    fi

    local python_cmd="python3"
    if command -v python3.14 &>/dev/null; then
        python_cmd="python3.14"
    elif command -v python3.13 &>/dev/null; then
        python_cmd="python3.13"
    fi

    if ! "$python_cmd" -m compileall -q "$TARGET_DIR" 2>/dev/null; then
        print_warning "compileall reported errors (check Python version / syntax)"
    fi

    if ! "$python_cmd" -c "
import sys
sys.path.insert(0, '$TARGET_DIR')
import bundle_capabilities
import pyinstaller_optional_packages
import pyinstaller_build_directives
import pyinstaller_dependencies
" 2>/dev/null; then
        print_error "PyInstaller --min helper modules failed to import"
        return 1
    fi

    print_success "Copy verification passed (run from source and PyInstaller --min build)"
    return 0
}

FORCE_REUSE=0
POSITIONAL=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) print_help ;;
        -f) FORCE_REUSE=1; shift ;;
        -*) print_error "Unknown option: $1"; exit 1 ;;
        *) POSITIONAL+=("$1"); shift ;;
    esac
done

if [ ${#POSITIONAL[@]} -eq 0 ]; then
    print_error "Target directory is required!"
    echo "Usage: $0 [-f] <target_directory>"
    exit 1
fi

TARGET_DIR="${POSITIONAL[0]}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! "$TARGET_DIR" = /* ]]; then
    TARGET_DIR="$(cd "$(dirname "$TARGET_DIR")" && pwd)/$(basename "$TARGET_DIR")"
fi

print_info "Source directory: $SCRIPT_DIR"
print_info "Target directory: $TARGET_DIR"

if [ ! -f "$SCRIPT_DIR/main.py" ]; then
    print_error "Source directory does not appear to be the image_browser project (main.py not found)"
    exit 1
fi

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
        fi
        empty_target_dir "$TARGET_DIR"
    fi
fi

print_info "Starting file copy operation..."
echo

print_info "Copying feature packages..."
for pkg in "${FEATURE_PACKAGES[@]}"; do
    copy_package_tree "$pkg"
done

copy_root_python_modules

print_info "Copying shell scripts..."
for sh in setup.sh run.sh pyInstallerBuild.sh build_dmg.sh copy_project_files.sh make_icns.sh; do
    copy_and_count "$sh"
done

print_info "Copying build / PyInstaller helpers..."
copy_and_count ".gitignore"
for py in \
    bundle_capabilities.py \
    pyinstaller_dependencies.py \
    pyinstaller_build_directives.py \
    pyinstaller_optional_packages.py \
    pyinstaller_frozen_support.py \
    pyinstaller_imagegen_paths.py \
    pyinstaller_runtime_hook.py \
    pyinstaller_whisper_models.py \
    list_runtime_assets.py
do
    copy_and_count "$py"
done

print_info "Copying runtime asset files..."
while IFS= read -r asset_rel; do
    [ -n "$asset_rel" ] || continue
    copy_and_count "$asset_rel"
done < <(python3 "$SCRIPT_DIR/list_runtime_assets.py")

print_info "Copying resource files..."
for res in Prowser.icns document.icns background.png Info.plist; do
    copy_and_count "$res"
done

print_info "Copying configuration and documentation..."
copy_and_count "minimal_requirements.txt"
copy_and_count "minimal_requirements.txt" "requirements.txt"
copy_and_count "requirements_min.txt"
for doc in LICENSE README.md KEYBOARD.md API.md IMAGE_CREATE_PLUGINS.md; do
    copy_and_count "$doc"
done

make_scripts_executable

if ! verify_copy; then
    print_error "Copy verification failed — target may not run with setup.sh / run.sh"
    exit 1
fi

echo
print_success "File copy operation completed!"
echo
echo "Summary:"
echo "  Items copied: $COPIED_COUNT"
echo "  Items skipped: $SKIPPED_COUNT"
echo "  Target directory: $TARGET_DIR"
echo
print_info "Next steps:"
echo "  1. cd $TARGET_DIR"
echo "  2. ./setup.sh   (create venv_image_browser and install dependencies)"
echo "  3. ./run.sh     (launch the application)"
echo "  4. ./pyInstallerBuild.sh       (full macOS app bundle)"
echo "  5. ./pyInstallerBuild.sh --min   (minimal bundle: browse + CLIP; no imagegen/faces/audio)"
echo
