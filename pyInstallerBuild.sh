#!/bin/bash


# PyInstaller Build Script for Prowser
# This script sets up PyInstaller and builds a proper macOS app bundle.
# PySide6 version: 6  (earlier versions are not supported and no support imports should be added

# NOTE TO USERS:
# If you see PyInstaller messages like:
#   - "Failed to collect submodules for 'torch.utils.tensorboard' because importing 'torch.utils.tensorboard' raised: ModuleNotFoundError: No module named 'tensorboard'"
#   - Warnings about deprecations in torch/distributed, or
#   - Warnings that "Redirects are currently not supported in Windows or MacOs" (for torch/distributed/elastic)
#
# These warnings are typically safe to ignore **if** you do not use those specific PyTorch features in your application.
# For most image browser applications using only basic torch/tensor functionality, you do **not** need to take further action.
#
# However, if you use features like torch.utils.tensorboard, distributed elastic training, or the deprecated submodules,
# you may need to:
#   - Install missing packages (e.g., 'tensorboard' via pip)
#   - Update your imports to avoid deprecated APIs (see the latest PyTorch documentation)
#
# PyInstaller will still build your application unless it encounters a critical error. Review the full build output for any "ERROR" messages.

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
RESET='\033[0m' # No Color

# Signal handler for cleanup on interruption
cleanup_on_interrupt() {
    echo
    print_warning "Build interrupted by user (Ctrl-C)"
    print_status "Cleaning up temporary files..."
    cleanup
    exit 130  # Standard exit code for SIGINT
}

# Set up signal handlers
trap cleanup_on_interrupt SIGINT SIGTERM

# Function to print colored output
print_status() {
    echo -e "${CYAN}[INFO]${RESET} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${RESET} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${RESET} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${RESET} $1"
}

# Homebrew LLVM is plain "Clang", not "AppleClang". dlib then enables Linux-style
# NEON flags (-mfpu=), which arm64-apple-darwin rejects. Use the Xcode toolchain.
export CC="$(xcrun --find clang)"
export CXX="$(xcrun --find clang++)"
# Prefer the Xcode macOS SDK: Command Line Tools' libc++ may target a newer Clang than
# AppleClang in Xcode (e.g. __builtin_ctzg), breaking CMake builds like dlib.
export SDKROOT="${SDKROOT:-$(xcrun --sdk macosx --show-sdk-path)}"

# Get the script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
print_status "Script directory: $SCRIPT_DIR"

# Change to script directory to ensure all relative paths work correctly
cd "$SCRIPT_DIR"
export SCRIPT_DIR

# Configuration
APP_NAME="Prowser"
MAIN_SCRIPT="$SCRIPT_DIR/prowser.py"
ICON_FILE="$SCRIPT_DIR/Prowser.icns"
BUILD_DIR="$SCRIPT_DIR/dist"
SPEC_FILE="$SCRIPT_DIR/${APP_NAME}.spec"
VENV_DIR="$SCRIPT_DIR/venv_pyinstaller"
DEPENDENCY_ANALYSIS_FILE="$SCRIPT_DIR/pyinstaller_dependencies.py"
REUSE_FLAG_FILE="$SCRIPT_DIR/.pyinstaller_reuse_flag"
FACE_MODEL_DIR="$SCRIPT_DIR/.pyinstaller_face_models"
FACE_MODEL_BASE="https://github.com/ageitgey/face_recognition_models/raw/master/face_recognition_models/models"
# All 4 models required by face_recognition_models (pose_predictor, pose_predictor_five_point, face_recognition, cnn_face_detector)
FACE_MODEL_FILES="shape_predictor_68_face_landmarks.dat shape_predictor_5_face_landmarks.dat dlib_face_recognition_resnet_model_v1.dat mmod_human_face_detector.dat"
WHISPER_MODEL_SCRIPT="$SCRIPT_DIR/pyinstaller_whisper_models.py"

# Add this near the top with other configuration variables
CONFIRM_BUILD=false  # Set to false to skip confirmations
MIN_BUILD=false     # Set via --min: omit imagegen, LM Studio SDK, and audio packages

# Add this function to handle user preferences
check_build_confirmation() {
    if [ "$CONFIRM_BUILD" = "true" ]; then
        echo
        echo "This script will:"
        echo "1. Create a dynamic dependency analyzer"
        echo "2. Create a virtual environment"
        echo "3. Install PyInstaller and project dependencies"
        echo "4. Analyze your codebase for actual imports (in PyInstaller env)"
        echo "5. Generate PyInstaller spec with accurate dependencies"
        echo "6. Customize the spec file for macOS"
        echo "7. Build a macOS app bundle (onedir mode)"
        echo "8. Clean up temporary files"
        echo
        echo "Build directory: $BUILD_DIR"
        echo "App name: $APP_NAME"
        echo
        read -p "Do you want to proceed with the build? (y/N): " -r
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_status "Build cancelled by user"
            exit 0
        fi
    else
        print_status "Build confirmation skipped (CONFIRM_BUILD=false)"
    fi
}

# Build date will be created just before PyInstaller runs to ensure accuracy

# Check if we're on macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    print_error "This script must be run on macOS"
    exit 1
fi

# Check for required tools
check_requirements() {
    print_status "Checking for required tools..."
    
    # Check for Python 3.14 first (current project Python level)
    if command -v python3.14 &> /dev/null; then
        PYTHON_CMD="python3.14"
        print_status "Using Python 3.14"
    elif command -v python3.13 &> /dev/null; then
        PYTHON_CMD="python3.13"
        print_status "Using Python 3.13"
    elif command -v python3.12 &> /dev/null; then
        PYTHON_CMD="python3.12"
        print_status "Using Python 3.12"
    elif command -v python3 &> /dev/null; then
        PYTHON_CMD="python3"
        print_warning "Using system Python, may have compatibility issues"
    else
        print_error "python3 not found"
        exit 1
    fi
    
    # Check for pip
    if ! command -v pip3 &> /dev/null; then
        print_error "pip3 not found"
        exit 1
    fi
    
    # Check for git (for some PyInstaller dependencies)
    if ! command -v git &> /dev/null; then
        print_warning "git not found. Some PyInstaller features may not work optimally."
    fi
    
    print_success "Required tools found"
}

# Create virtual environment
create_venv() {
    print_status "Creating virtual environment for PyInstaller..."
    
    # Use flag file: "reuse" means skip creation if venv exists
    if [ -f "$REUSE_FLAG_FILE" ] && [ "$(cat "$REUSE_FLAG_FILE" 2>/dev/null)" = "reuse" ] && [ -d "$VENV_DIR" ]; then
        print_status "Reusing existing virtual environment at $VENV_DIR"
        return 0
    fi
    
    if [ -d "$VENV_DIR" ]; then
        print_warning "Virtual environment already exists. Removing..."
        rm -rf "$VENV_DIR"
    fi
    
    $PYTHON_CMD -m venv "$VENV_DIR"
    print_success "Virtual environment created"
}

# Install PyInstaller and dependencies
install_dependencies() {
    print_status "Installing PyInstaller and dependencies..."
    
    source "$VENV_DIR/bin/activate"
    
    # Upgrade pip
    pip install --upgrade pip
    
    # Install PyInstaller
    pip install pyinstaller
    
    # Install additional tools that might be needed
    pip install setuptools wheel
    
    print_success "PyInstaller and dependencies installed"
}

# Install the actual project dependencies in the PyInstaller venv
install_project_dependencies() {
    print_status "Installing project dependencies in PyInstaller environment..."
    
    source "$VENV_DIR/bin/activate"
    
    # Check if simplified requirements file exists and install from it
    if [ "$MIN_BUILD" = "true" ] && [ -f "$SCRIPT_DIR/requirements_min.txt" ]; then
        print_status "Minimal build: installing from requirements_min.txt..."
        pip install -r "$SCRIPT_DIR/requirements_min.txt"
    elif [ -f "$SCRIPT_DIR/requirements_build.txt" ]; then
        print_status "Installing from requirements_build.txt (simplified)..."
        pip install -r "$SCRIPT_DIR/requirements_build.txt"
    elif [ -f "$SCRIPT_DIR/requirements.txt" ]; then
        print_status "Installing from requirements.txt..."
        pip install -r "$SCRIPT_DIR/requirements.txt"
    elif [ -f "$SCRIPT_DIR/requirements_image_browser.txt" ]; then
        print_status "Installing from requirements_image_browser.txt..."
        pip install -r "$SCRIPT_DIR/requirements_image_browser.txt"
    else
        print_warning "No requirements file found. Installing common dependencies manually..."
             # Install the most common dependencies manually
    pip install PySide6 Pillow "numpy<2.0" scikit-image imagehash psutil pyobjc-core pyobjc-framework-Cocoa pyobjc-framework-LaunchServices pyobjc-framework-CoreServices pyobjc-framework-Foundation
    fi

    if [ "$MIN_BUILD" = "true" ]; then
        print_status "Minimal build: skipping Create-menu and voice dictation package installs"
    else
        install_create_menu_dependencies
        install_whisper_voice_dependencies
        verify_create_menu_dependencies
        verify_whisper_voice_dependencies
    fi

    print_success "Project dependencies installed"
}

# Voice dictation (faster-whisper tiny.en + microphone capture).
install_whisper_voice_dependencies() {
    print_status "Installing voice dictation packages (faster-whisper, sounddevice)..."
    source "$VENV_DIR/bin/activate"
    pip install faster-whisper sounddevice
}

verify_whisper_voice_dependencies() {
    print_status "Verifying voice dictation packages in PyInstaller venv..."
    source "$VENV_DIR/bin/activate"
    if ! python -c "
import faster_whisper
import ctranslate2
import sounddevice
import _sounddevice
print('Whisper voice deps OK')
"; then
        print_error "Voice dictation dependencies missing in $VENV_DIR (faster-whisper or sounddevice)."
        print_error "Run: source $VENV_DIR/bin/activate && pip install faster-whisper sounddevice"
        exit 1
    fi
}

# Create-menu backends (must be in the PyInstaller venv before Analysis runs).
install_create_menu_dependencies() {
    print_status "Installing Create-menu image generation packages (mflux, diffusers, accelerate, requests)..."
    source "$VENV_DIR/bin/activate"
    pip install mflux diffusers accelerate requests
}

verify_create_menu_dependencies() {
    print_status "Verifying Create-menu packages in PyInstaller venv..."
    source "$VENV_DIR/bin/activate"
    if ! python -c "
import diffusers
from diffusers import SanaSprintPipeline
import accelerate
import mflux
import requests
import transformers
print('Create-menu deps OK')
"; then
        print_error "Create-menu dependencies missing in $VENV_DIR (diffusers, accelerate, or mflux)."
        print_error "Run: source $VENV_DIR/bin/activate && pip install diffusers accelerate mflux"
        exit 1
    fi
}

# Dependency analyzer is committed (pyinstaller_dependencies.py); do not embed a copy here.
create_dependency_analyzer() {
    if [ ! -f "$DEPENDENCY_ANALYSIS_FILE" ]; then
        print_error "Missing committed dependency analyzer: $DEPENDENCY_ANALYSIS_FILE"
        exit 1
    fi
    print_status "Using dependency analyzer: $DEPENDENCY_ANALYSIS_FILE"
    chmod +x "$DEPENDENCY_ANALYSIS_FILE"
}

# Analyze dependencies dynamically (now in the PyInstaller venv)
analyze_dependencies() {
    print_status "Analyzing dependencies dynamically in PyInstaller environment..."
    
    if [ ! -f "$DEPENDENCY_ANALYSIS_FILE" ]; then
        print_error "Dependency analyzer not found"
        exit 1
    fi
    
    # Activate the PyInstaller venv for analysis
    source "$VENV_DIR/bin/activate"

    if [ "$MIN_BUILD" = "true" ]; then
        export PYINSTALLER_MIN_BUILD=1
        print_status "Minimal build: excluding imagegen, LM Studio SDK, and audio from analysis"
    else
        unset PYINSTALLER_MIN_BUILD 2>/dev/null || true
    fi
    
    # Run the dependency analyzer
    python "$DEPENDENCY_ANALYSIS_FILE" "$SCRIPT_DIR"
    
    if [ ! -f "$SCRIPT_DIR/pyinstaller_directives.json" ]; then
        print_error "Failed to generate PyInstaller directives"
        exit 1
    fi
    
    print_success "Dependencies analyzed in PyInstaller environment"
}

# Add this function after the dependency analysis
install_missing_dependencies() {
    print_status "Installing missing dependencies detected in analysis..."
    
    source "$VENV_DIR/bin/activate"
    
    # Read the analysis results
    if [ ! -f "$SCRIPT_DIR/pyinstaller_directives.json" ]; then
        print_error "Analysis results not found. Run dependency analysis first."
        return 1
    fi
    
    # Extract missing packages and install them
    python -c "
import json
import subprocess
import sys
import os

# Standard library modules - comprehensive list
STDLIB_MODULES = {
    'abc', 'argparse', 'asyncio', 'collections', 'contextlib', 'copy', 'datetime',
    'dataclasses', 'enum', 'functools', 'glob', 'hashlib', 'io', 'json', 'logging',
    'math', 'multiprocessing', 'os', 'pathlib', 'platform', 'random', 're', 'shutil',
    'signal', 'subprocess', 'sys', 'threading', 'time', 'traceback', 'typing', 'weakref',
    'ast', 'atexit', 'concurrent', 'ctypes', 'fnmatch', 'getpass', 'importlib', 'pickle',
    'queue', 'tempfile', 'uuid', 'warnings', 'stat', 'statistics', 'string', 'struct',
    'urllib', 'urllib.parse', 'urllib.request', 'base64', 'binascii', 'csv', 'email',
    'html', 'http', 'xml', 'xmlrpc', 'socket', 'ssl', 'sqlite3', 'zlib', 'gzip',
    'bz2', 'lzma', 'zipfile', 'tarfile', 'hashlib', 'hmac', 'secrets', 'itertools',
    'operator', 'functools', 'collections', 'heapq', 'bisect', 'array', 'copy',
    'pprint', 'reprlib', 'textwrap', 'stringprep', 'readline', 'rlcompleter',
    'difflib', 'textwrap', 'unicodedata', 'stringprep', 'readline', 'rlcompleter',
    'struct', 'codecs', 'types', 'copy', 'pprint', 'reprlib', 'enum', 'numbers',
    'math', 'cmath', 'decimal', 'fractions', 'statistics', 'random', 'secrets',
    'stat', 'filecmp', 'tempfile', 'glob', 'fnmatch', 'linecache', 'shutil',
    'pickle', 'copyreg', 'shelve', 'marshal', 'dbm', 'sqlite3', 'zlib', 'gzip',
    'bz2', 'lzma', 'zipfile', 'tarfile', 'csv', 'configparser', 'netrc', 'xdrlib',
    'plistlib', 'hashlib', 'hmac', 'secrets', 'os', 'io', 'time', 'argparse',
    'getopt', 'logging', 'getpass', 'curses', 'platform', 'errno', 'ctypes',
    'threading', 'multiprocessing', 'concurrent', 'subprocess', 'sched', 'queue',
    'select', 'selectors', 'asyncio', 'socket', 'ssl', 'email', 'json', 'mailbox',
    'mimetypes', 'base64', 'binhex', 'binascii', 'quopri', 'uu', 'html', 'xml',
    'urllib', 'http', 'ftplib', 'poplib', 'imaplib', 'nntplib', 'smtplib',
    'telnetlib', 'socketserver', 'xmlrpc', 'ipaddress', 'audioop', 'aifc',
    'sunau', 'wave', 'chunk', 'colorsys', 'imghdr', 'sndhdr', 'ossaudiodev',
    'gettext', 'locale', 'calendar', 'cmd', 'shlex', 'tkinter', 'turtle',
    'pydoc', 'doctest', 'unittest', 'test', 'lib2to3', 'typing', 'pydoc_data',
    'distutils', 'ensurepip', 'venv', 'zipapp', 'faulthandler', 'pdb', 'profile',
    'pstats', 'timeit', 'trace', 'tracemalloc', 'gc', 'inspect', 'site',
    'fpectl', 'warnings', 'contextlib', 'abc', 'atexit', 'traceback', 'future_builtins',
    'builtins', '__builtin__', '__main__', 'sys', 'warnings', 'contextlib',
    'abc', 'atexit', 'traceback', 'future_builtins', 'builtins', '__builtin__',
    '__main__', 'sys', 'warnings', 'contextlib', 'abc', 'atexit', 'traceback'
}

def is_stdlib_module(module_name):
    \"\"\"Check if a module is part of Python standard library.\"\"\"
    base_module = module_name.split('.')[0]
    if base_module in STDLIB_MODULES:
        return True
    # Check using sys.stdlib_module_names if available (Python 3.10+)
    try:
        if hasattr(sys, 'stdlib_module_names'):
            if base_module in sys.stdlib_module_names:
                return True
    except:
        pass
    # Check common standard library prefixes
    stdlib_prefixes = ('_', '__', 'encodings.', 'email.', 'html.', 'http.',
                       'urllib.', 'xml.', 'xmlrpc.', 'test.', 'lib2to3.', 'wsgiref.')
    for prefix in stdlib_prefixes:
        if module_name.startswith(prefix):
            return True
    return False

# Get script directory from environment or use current directory
script_dir = os.environ.get('SCRIPT_DIR', os.getcwd())
sys.path.insert(0, script_dir)
try:
    from pyinstaller_optional_packages import package_name_is_excluded
except ImportError:
    def package_name_is_excluded(_name, *, min_build=None):
        return False

# Read analysis results
with open(os.path.join(script_dir, 'pyinstaller_directives.json'), 'r') as f:
    data = json.load(f)

# Get all detected external packages (excluding stdlib)
detected_packages = set()
for imp in data.get('hidden_imports', []):
    if '.' in imp:
        base_package = imp.split('.')[0]
    else:
        base_package = imp
    
    # Skip standard library modules
    if not is_stdlib_module(base_package):
        detected_packages.add(base_package)

# Check what's already installed
try:
    result = subprocess.run([sys.executable, '-m', 'pip', 'list', '--format=freeze'], 
                          capture_output=True, text=True)
    installed_packages = set()
    for line in result.stdout.split('\n'):
        if '==' in line:
            package_name = line.split('==')[0].lower()
            installed_packages.add(package_name)
except:
    installed_packages = set()

# Find missing packages (excluding stdlib)
missing_packages = set()
for package in detected_packages:
    # Double-check it's not stdlib
    if is_stdlib_module(package):
        print(f'Skipping standard library module: {package}')
        continue
    if package_name_is_excluded(package):
        print(f'Skipping excluded package: {package}')
        continue
    # Check if installed (case-insensitive)
    package_lower = package.lower()
    if package_lower not in installed_packages:
        missing_packages.add(package)

# Install missing packages
if missing_packages:
    print(f'Installing missing packages: {missing_packages}')
    for package in missing_packages:
        try:
            # Handle special cases
            install_name = package
            if package == 'PIL':
                install_name = 'Pillow'
            elif package == 'skimage':
                install_name = 'scikit-image'
            elif package == 'objc':
                install_name = 'pyobjc-core'
            elif package == 'AppKit':
                install_name = 'pyobjc-framework-Cocoa'
            elif package == 'LaunchServices':
                install_name = 'pyobjc-framework-LaunchServices'
            elif package == 'CoreServices':
                install_name = 'pyobjc-framework-CoreServices'
            elif package == 'Foundation':
                install_name = 'pyobjc-framework-Foundation'
            
            print(f'Installing {install_name}...')
            subprocess.run([sys.executable, '-m', 'pip', 'install', install_name], 
                         check=True, capture_output=True)
            print(f'Successfully installed {install_name}')
        except subprocess.CalledProcessError as e:
            print(f'Failed to install {package}: {e}')
            # Try alternative package names
            if package == 'pyperclip':
                try:
                    subprocess.run([sys.executable, '-m', 'pip', 'install', 'pyperclip'], 
                                 check=True, capture_output=True)
                    print(f'Successfully installed pyperclip')
                except:
                    print(f'Failed to install pyperclip - clipboard functionality may not work')
else:
    print('All detected packages are already installed')
"
    
    if [ $? -eq 0 ]; then
        print_success "Missing dependencies installed"
    else
        print_warning "Some dependencies may not have been installed properly"
    fi
}

# Download face_recognition models for bundling (all 4 required by face_recognition_models).
# Saves to .pyinstaller_face_models/ and reuses on subsequent builds (cache preserved).
download_face_recognition_models() {
    mkdir -p "$FACE_MODEL_DIR"
    local failed=0
    
    for fname in $FACE_MODEL_FILES; do
        local model_path="$FACE_MODEL_DIR/$fname"
        local url="$FACE_MODEL_BASE/$fname"
        
        # Reuse cached download if present and non-trivial size. Smallest model is
        # mmod_human_face_detector.dat (~700KB); others are multi-MB, so >512KB is enough.
        if [ -f "$model_path" ]; then
            local size
            size=$(stat -f%z "$model_path" 2>/dev/null || echo "0")
            if [ "$size" -gt 524288 ]; then
                if [ "$size" -ge 1048576 ]; then
                    print_status "Reusing cached $fname (~$((size/1024/1024))MB)"
                else
                    print_status "Reusing cached $fname (~$((size/1024))KB)"
                fi
                continue
            fi
        fi
        
        print_status "Downloading $fname ..."
        if curl -fL -o "$model_path" "$url"; then
            if [ -f "$model_path" ] && [ -s "$model_path" ]; then
                print_success "Downloaded $fname"
            else
                print_error "Downloaded $fname is empty or missing"
                rm -f "$model_path" 2>/dev/null
                failed=1
            fi
        else
            print_error "Failed to download $fname"
            rm -f "$model_path" 2>/dev/null
            failed=1
        fi
    done
    
    [ "$failed" -eq 0 ] || return 1
}

# Download Systran/faster-whisper-tiny.en weights for bundling (config, model.bin, tokenizer, vocab only).
# Saves to .pyinstaller_whisper_models/ and reuses on subsequent builds.
download_whisper_model() {
    if [ ! -f "$WHISPER_MODEL_SCRIPT" ]; then
        print_error "Missing $WHISPER_MODEL_SCRIPT"
        return 1
    fi
    source "$VENV_DIR/bin/activate"
    print_status "Ensuring bundled whisper model (faster-whisper-tiny.en)..."
    if python "$WHISPER_MODEL_SCRIPT" download; then
        print_success "Whisper model ready for bundling"
    else
        print_error "Failed to download whisper model"
        return 1
    fi
}

# Create PyInstaller spec file with dynamic dependencies
create_spec_file() {
    print_status "Creating PyInstaller spec file with dynamic dependencies..."
    
    
    source "$VENV_DIR/bin/activate"
    
    # Read the generated directives
    if [ ! -f "$SCRIPT_DIR/pyinstaller_directives.json" ]; then
        print_error "PyInstaller directives not found. Run dependency analysis first."
        exit 1
    fi
    
    # Local package paths (imagegen_plugins + post-restructure feature packages)
    IMAGEGEN_PATHS=$(python "$SCRIPT_DIR/pyinstaller_imagegen_paths.py")
    export IMAGEGEN_HIDDEN_JSON=$(echo "$IMAGEGEN_PATHS" | grep '^IMAGEGEN_HIDDEN=' | cut -d= -f2-)
    export LOCAL_PACKAGES_HIDDEN_JSON=$(echo "$IMAGEGEN_PATHS" | grep '^LOCAL_PACKAGES_HIDDEN=' | cut -d= -f2-)

    # Extract directives using pyinstaller_build_directives.py
    if [ "$MIN_BUILD" = "true" ]; then
        export PYINSTALLER_MIN_BUILD=1
    else
        unset PYINSTALLER_MIN_BUILD 2>/dev/null || true
    fi
    DIRECTIVES=$(python "$SCRIPT_DIR/pyinstaller_build_directives.py" shell)
    COLLECT_SUBMODULES_CLI=$(python "$SCRIPT_DIR/pyinstaller_build_directives.py" collect-submodules-cli)
    
    # Parse the output
    HIDDEN_IMPORTS=$(echo "$DIRECTIVES" | grep "HIDDEN_IMPORTS=" | cut -d'=' -f2)
    COLLECT_ALL=$(echo "$DIRECTIVES" | grep "COLLECT_ALL=" | cut -d'=' -f2)
    EXCLUDES=$(echo "$DIRECTIVES" | grep "EXCLUDES=" | cut -d'=' -f2)
    
    # print_status "Using hidden imports: $HIDDEN_IMPORTS"
    # print_status "Using collect all: $COLLECT_ALL"
    # print_status "Using excludes: $EXCLUDES"
    
    # Build PyInstaller command with proper argument handling
    # Use onedir mode instead of onefile for macOS compatibility
    # Add --clean flag to avoid symbolic link conflicts
    # Only include essential files: icon
    # Add --argv-emulation for proper macOS file handling
    PYINSTALLER_CMD="pyinstaller --name \"$APP_NAME\" --onedir --windowed --clean --noconfirm --log-level WARN --icon \"$ICON_FILE\" --add-data \"$ICON_FILE:.\" --argv-emulation --paths \"$SCRIPT_DIR\" --additional-hooks-dir \"$SCRIPT_DIR/pyinstaller_hooks\" $COLLECT_SUBMODULES_CLI"
    
    # Add hidden imports if any
    if [ -n "$HIDDEN_IMPORTS" ]; then
        for import in $HIDDEN_IMPORTS; do
            PYINSTALLER_CMD="$PYINSTALLER_CMD --hidden-import \"$import\""
        done
    fi
    
    # Add collect all if any (but be more selective with PySide6)
    if [ -n "$COLLECT_ALL" ]; then
        for pkg in $COLLECT_ALL; do
            if [ "$pkg" = "PySide6" ]; then
                # For PySide6, only collect essential modules to avoid framework conflicts
                PYINSTALLER_CMD="$PYINSTALLER_CMD --hidden-import PySide6.QtCore --hidden-import PySide6.QtGui --hidden-import PySide6.QtWidgets"
            else
                PYINSTALLER_CMD="$PYINSTALLER_CMD --collect-all \"$pkg\""
            fi
        done
    fi
    
    # Add Windows-specific exclusions for macOS-only builds
    PYINSTALLER_CMD="$PYINSTALLER_CMD --exclude-module win32com --exclude-module win32api --exclude-module win32con --exclude-module win32gui --exclude-module win32print --exclude-module win32process --exclude-module win32security --exclude-module win32service --exclude-module win32serviceutil --exclude-module win32timezone --exclude-module win32traceutil --exclude-module win32ui --exclude-module win32wnet --exclude-module pywintypes --exclude-module pythoncom --exclude-module winreg --exclude-module msilib --exclude-module msvcrt"
    
    # Add excludes if any
    if [ -n "$EXCLUDES" ]; then
        for exclude in $EXCLUDES; do
            PYINSTALLER_CMD="$PYINSTALLER_CMD --exclude-module \"$exclude\""
        done
    fi
    
    # Add the main script
    PYINSTALLER_CMD="$PYINSTALLER_CMD \"$MAIN_SCRIPT\""
    
    # print_status "Running: $PYINSTALLER_CMD"
    
    # Execute the command
    eval $PYINSTALLER_CMD
    
    print_success "Spec file generated with dynamic dependencies"
}

# Create entitlements file for proper permissions
create_entitlements() {
    print_status "Creating entitlements file for proper file system access..."
    
    cat > "$SCRIPT_DIR/Prowser.entitlements" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <!-- Allow file system access for undo operations -->
    <key>com.apple.security.files.user-selected.read-write</key>
    <true/>
    
    <!-- Allow access to user's home directory -->
    <key>com.apple.security.files.home-relative-path.read-write</key>
    <true/>
    
    <!-- Allow access to Trash directory -->
    <key>com.apple.security.files.downloads.read-write</key>
    <true/>
    
    <!-- Allow Apple Events for Finder integration -->
    <key>com.apple.security.automation.apple-events</key>
    <true/>
    
    <!-- Allow network access if needed -->
    <key>com.apple.security.network.client</key>
    <true/>
    
    <!-- Allow temporary file access -->
    <key>com.apple.security.temporary-exception.files.absolute-path.read-write</key>
    <array>
        <string>/tmp/</string>
        <string>/var/tmp/</string>
    </array>
</dict>
</plist>
EOF
    
    print_success "Entitlements file created"
}

# Customize the spec file for better macOS integration
customize_spec_file() {
    print_status "Customizing spec file for macOS..."
    
    if [ ! -f "$SPEC_FILE" ]; then
        print_error "Spec file not found. Run PyInstaller first."
        exit 1
    fi
    
    # Create a backup
    cp "$SPEC_FILE" "${SPEC_FILE}.backup"
    
    # Absolute paths and imagegen hiddenimports for the spec file
    IMAGEGEN_PATHS=$(python "$SCRIPT_DIR/pyinstaller_imagegen_paths.py")
    export IMAGEGEN_HIDDEN_JSON=$(echo "$IMAGEGEN_PATHS" | grep '^IMAGEGEN_HIDDEN=' | cut -d= -f2-)
    export LOCAL_PACKAGES_HIDDEN_JSON=$(echo "$IMAGEGEN_PATHS" | grep '^LOCAL_PACKAGES_HIDDEN=' | cut -d= -f2-)
    PATHEX_JSON=$(echo "$IMAGEGEN_PATHS" | grep '^PATHEX=' | cut -d= -f2-)
    HOOKSPATH_JSON=$(echo "$IMAGEGEN_PATHS" | grep '^HOOKSPATH=' | cut -d= -f2-)

    # Read merged directives for the custom spec
    if [ "$MIN_BUILD" = "true" ]; then
        export PYINSTALLER_MIN_BUILD=1
    else
        unset PYINSTALLER_MIN_BUILD 2>/dev/null || true
    fi
    DIRECTIVES=$(python "$SCRIPT_DIR/pyinstaller_build_directives.py" repr)
    SPEC_COLLECT_PACKAGES=$(python "$SCRIPT_DIR/pyinstaller_build_directives.py" spec-collect-packages)
    SPEC_COPY_METADATA=$(python "$SCRIPT_DIR/pyinstaller_build_directives.py" spec-copy-metadata)
    
    HIDDEN_IMPORTS=$(echo "$DIRECTIVES" | grep "HIDDEN_IMPORTS=" | cut -d'=' -f2)
    COLLECT_ALL=$(echo "$DIRECTIVES" | grep "COLLECT_ALL=" | cut -d'=' -f2)
    EXCLUDES=$(echo "$DIRECTIVES" | grep "EXCLUDES=" | cut -d'=' -f2)
    
    # Customize the spec file for macOS app bundle with simplified structure
    # REMOVED the problematic datas section that was causing symbolic link conflicts
    # Note: We're already in SCRIPT_DIR, so use relative paths
    # Check if runtime hook file exists
    RUNTIME_HOOK_FILE="$SCRIPT_DIR/pyinstaller_runtime_hook.py"
    if [ -f "$RUNTIME_HOOK_FILE" ]; then
        RUNTIME_HOOKS="['pyinstaller_runtime_hook.py']"
        print_status "Including runtime hook for PYTHON_JIT=1"
    else
        RUNTIME_HOOKS="[]"
        print_warning "Runtime hook file not found, PYTHON_JIT will not be set"
    fi

    RUNTIME_ASSET_DATAS=$("$PYTHON_CMD" "$SCRIPT_DIR/list_runtime_assets.py" --format pyinstaller)
    if [ -z "$RUNTIME_ASSET_DATAS" ]; then
        print_error "list_runtime_assets.py produced no asset datas entries"
        exit 1
    fi
    print_status "Bundling $(echo "$RUNTIME_ASSET_DATAS" | wc -l | tr -d ' ') runtime asset(s)"

    WHISPER_MODEL_DATAS=""
    FACE_MODEL_DATAS=""
    if [ "$MIN_BUILD" = "true" ]; then
        print_status "Minimal build: skipping bundled whisper model and face models"
        LS_ENVIRONMENT_BLOCK="'LSEnvironment': {
            'PYTHON_JIT': '1',
            'PROWSER_MIN_BUNDLE': '1',
        },"
    else
        LS_ENVIRONMENT_BLOCK="'LSEnvironment': {
            'PYTHON_JIT': '1',
        },"
        FACE_MODEL_DATAS="        ('.pyinstaller_face_models/dlib_face_recognition_resnet_model_v1.dat', 'face_recognition_models/models'),
        ('.pyinstaller_face_models/mmod_human_face_detector.dat', 'face_recognition_models/models'),
        ('.pyinstaller_face_models/shape_predictor_5_face_landmarks.dat', 'face_recognition_models/models'),
        ('.pyinstaller_face_models/shape_predictor_68_face_landmarks.dat', 'face_recognition_models/models'),"
        WHISPER_MODEL_DATAS=$("$PYTHON_CMD" "$WHISPER_MODEL_SCRIPT" --format pyinstaller)
        if [ -z "$WHISPER_MODEL_DATAS" ]; then
            print_error "pyinstaller_whisper_models.py produced no whisper model datas entries"
            exit 1
        fi
        print_status "Bundling whisper model (faster-whisper-tiny.en only)"
    fi
    
    cat > "$SPEC_FILE" << EOF
# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all as _pyi_collect_all
from PyInstaller.utils.hooks import copy_metadata as _pyi_copy_metadata

# COLLECT_ALL from directives was never merged into Analysis; collect backends here.
_imagegen_collect_datas = []
_imagegen_collect_binaries = []
_imagegen_collect_hidden = []
for _pkg in $SPEC_COLLECT_PACKAGES:
    try:
        _d, _b, _h = _pyi_collect_all(_pkg)
        _imagegen_collect_datas += _d
        _imagegen_collect_binaries += _b
        _imagegen_collect_hidden += _h
    except Exception as _collect_err:
        print(f"Warning: collect_all({_pkg}) failed: {_collect_err}")

for _pkg in $SPEC_COPY_METADATA:
    try:
        _imagegen_collect_datas += _pyi_copy_metadata(_pkg)
    except Exception as _meta_err:
        print(f"Warning: copy_metadata({_pkg}) failed: {_meta_err}")

_hidden_from_directives = $HIDDEN_IMPORTS

a = Analysis(
    ['prowser.py'],
    pathex=$PATHEX_JSON,
    binaries=_imagegen_collect_binaries,
    datas=[
        ('Prowser.icns', '.'),
$FACE_MODEL_DATAS
$RUNTIME_ASSET_DATAS
$WHISPER_MODEL_DATAS
    ] + _imagegen_collect_datas,
    hiddenimports=list(set(_hidden_from_directives + _imagegen_collect_hidden)),
    hookspath=$HOOKSPATH_JSON,
    hooksconfig={},
    runtime_hooks=$RUNTIME_HOOKS,
    excludes=$EXCLUDES,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Prowser',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file='Prowser.entitlements',
    icon='Prowser.icns'
)

# Collect all the files with simplified structure
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[
        'libmlx.dylib',
        'libjaccl.dylib',
        'mlx.metallib',
        'core.cpython-314-darwin.so',
    ],
    name='Prowser'
)

# macOS app bundle with enhanced document handling and proper entitlements
app = BUNDLE(
    coll,
    name='Prowser.app',
    icon='Prowser.icns',
    bundle_identifier='com.prowser.app',
    info_plist={
        'CFBundleName': 'Prowser',
        'CFBundleDisplayName': 'Prowser',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '10.13.0',
        'CFBundleDocumentTypes': [
            {
                'CFBundleTypeName': 'Image',
                'CFBundleTypeExtensions': ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'webp'],
                'CFBundleTypeRole': 'Viewer',
                'CFBundleTypeIconFile': 'document.icns',
                'CFBundleTypeOSTypes': ['JPEG', 'PNGf', 'GIFf', 'BMPf', 'TIFF', 'WebP'],
                'LSHandlerRank': 'Owner',
                'LSItemContentTypes': ['public.jpeg', 'public.png', 'public.gif', 'public.bmp', 'public.tiff', 'public.webp'],
            }
        ],
        'CFBundleURLTypes': [
            {
                'CFBundleURLName': 'File URL',
                'CFBundleURLSchemes': ['file'],
            }
        ],
        'NSAppleEventsUsageDescription': 'Prowser needs to handle image files opened from Finder',
        'LSApplicationCategoryType': 'public.app-category.graphics-design',
        'NSRequiresAquaSystemAppearance': False,
        'LSMultipleInstancesProhibited': True,
        # Add permissions for file operations and undo functionality
        'NSAppleEventsUsageDescription': 'Prowser needs to handle image files opened from Finder and restore files from Trash',
        'NSSystemAdministrationUsageDescription': 'Prowser needs to restore files from Trash to their original locations',
        'NSMicrophoneUsageDescription': 'Prowser uses the microphone for optional voice input in prompt and caption fields',
        # Set PYTHON_JIT=1 before Python interpreter starts
$LS_ENVIRONMENT_BLOCK
    }
)
EOF
    
    print_success "Spec file customized for macOS with simplified structure"
}

# Build the app
build_app() {
    print_status "Building Prowser app with PyInstaller..."
    
    source "$VENV_DIR/bin/activate"

    if [ "$MIN_BUILD" = "true" ]; then
        export PYINSTALLER_MIN_BUILD=1
        print_status "Minimal build: PyInstaller hooks will skip imagegen and audio packages"
    else
        unset PYINSTALLER_MIN_BUILD 2>/dev/null || true
    fi

    if [ ! -f "$SCRIPT_DIR/imagegen_plugins/__init__.py" ]; then
        print_error "imagegen_plugins/ is missing under $SCRIPT_DIR — Create menu cannot be bundled."
        exit 1
    fi
    if [ ! -f "$SCRIPT_DIR/browser_window/__init__.py" ]; then
        print_error "browser_window/ is missing under $SCRIPT_DIR — restructured app code cannot be bundled."
        exit 1
    fi
    
    # Clean previous builds completely
    if [ -d "$BUILD_DIR" ]; then
        print_status "Cleaning previous builds completely..."
        rm -rf "$BUILD_DIR"
    fi
    
    # Clean build directory
    if [ -d "build" ]; then
        print_status "Cleaning build directory..."
        rm -rf "build"
    fi
    
    # Build using the spec file (pathex/hookspath in spec must point at SCRIPT_DIR)
    pyinstaller --clean --log-level WARN "$SPEC_FILE"
    
    # Apply entitlements to the built app
    if [ -f "$SCRIPT_DIR/Prowser.entitlements" ] && [ -d "$BUILD_DIR/${APP_NAME}.app" ]; then
        print_status "Applying entitlements to app bundle..."
        
        # First, copy the entitlements file to the app bundle
        cp "$SCRIPT_DIR/Prowser.entitlements" "$BUILD_DIR/${APP_NAME}.app/Contents/"
        
        # Now properly code-sign the app with entitlements
        print_status "Code-signing app with entitlements..."
        if command -v codesign &> /dev/null; then
            # Remove any existing code signature first
            codesign --remove-signature "$BUILD_DIR/${APP_NAME}.app" 2>/dev/null || true
            
            # Code-sign with entitlements (adhoc signing for development)
            codesign --force --deep --sign - --entitlements "$SCRIPT_DIR/Prowser.entitlements" "$BUILD_DIR/${APP_NAME}.app"
            
            if [ $? -eq 0 ]; then
                print_success "App code-signed with entitlements successfully"
                
                # Verify the entitlements were applied
                print_status "Verifying entitlements..."
                ENTITLEMENTS_OUTPUT=$(codesign -d --entitlements - "$BUILD_DIR/${APP_NAME}.app" 2>/dev/null)
                if [ -n "$ENTITLEMENTS_OUTPUT" ] && echo "$ENTITLEMENTS_OUTPUT" | grep -q "com.apple.security"; then
                    print_success "Entitlements verified in code signature"
                else
                    print_warning "Entitlements may not have been applied properly"
                    print_status "Debug: Entitlements output was:"
                    echo "$ENTITLEMENTS_OUTPUT" | head -5
                fi
            else
                print_error "Failed to code-sign app with entitlements"
            fi
        else
            print_warning "codesign command not found - entitlements file copied but not applied"
            print_warning "You may need to manually code-sign the app with entitlements"
        fi
    fi
    
    print_success "Build completed"
}

# Verify the build
verify_build() {
    print_status "Verifying the build..."
    
    if [ -d "$BUILD_DIR/${APP_NAME}.app" ]; then
        print_success "App bundle created successfully"
        print_status "Location: $BUILD_DIR/${APP_NAME}.app"
        
        # Check file size
        APP_SIZE=$(du -sh "$BUILD_DIR/${APP_NAME}.app" | cut -f1)
        print_status "App bundle size: $APP_SIZE"
        
        # List contents
        print_status "App bundle contents:"
        ls -la "$BUILD_DIR/${APP_NAME}.app/Contents/"
        
        # Check if the executable exists
        if [ -f "$BUILD_DIR/${APP_NAME}.app/Contents/MacOS/Prowser" ]; then
            print_success "Executable found and ready"
        else
            print_error "Executable not found in app bundle"
            exit 1
        fi

        # diffusers must be fully bundled (empty stub dirs break SANA Create menu).
        if [ "$MIN_BUILD" = "true" ]; then
            print_success "Minimal build: skipped Create-menu bundle verification (diffusers/requests)"
        elif find "$BUILD_DIR/${APP_NAME}.app" -path "*/diffusers/pipelines/*" -name "*.py" 2>/dev/null | head -1 | grep -q .; then
            print_success "diffusers pipelines found in app bundle (SANA Create menu)"
        else
            print_error "diffusers is not fully bundled (no diffusers/pipelines in app)."
            print_error "Rebuild without --reuse so venv_pyinstaller installs diffusers, or run verify_create_menu_dependencies."
            exit 1
        fi
        if [ "$MIN_BUILD" = "true" ]; then
            :
        elif find "$BUILD_DIR/${APP_NAME}.app" -path "*/requests/__init__.py" 2>/dev/null | head -1 | grep -q .; then
            print_success "requests package found in app bundle (diffusers/transformers metadata)"
        else
            print_error "requests is not bundled; SANA generation will fail at runtime."
            exit 1
        fi
        
    else
        print_error "App bundle not found in $BUILD_DIR"
        exit 1
    fi
}

# Install to Applications folder
install_to_applications() {
    print_status "\nInstalling Prowser to /Applications..."
    
    # Check if app already exists in Applications
    if [ -d "/Applications/${APP_NAME}.app" ]; then
        # Remove existing app
        print_status "Removing existing Prowser from /Applications..."
        print_status "************************************************************"
        print_status "*            You must enter your password                  *"
        print_status "************************************************************"
        
        sudo rm -rf "/Applications/${APP_NAME}.app"
    fi
    
    # Copy to Applications with sudo
    print_status "Copying Prowser to /Applications (requires sudo)..."
    sudo cp -R "$BUILD_DIR/${APP_NAME}.app" "/Applications/"
    
    # Set proper permissions
    print_status "Setting proper permissions..."
    sudo chown -R root:wheel "/Applications/${APP_NAME}.app"
    sudo chmod -R 755 "/Applications/${APP_NAME}.app"
    
    # Re-apply code signing with entitlements after installation
    print_status "Re-applying code signature with entitlements..."
    if command -v codesign &> /dev/null; then
        # Remove existing signature
        sudo codesign --remove-signature "/Applications/${APP_NAME}.app" 2>/dev/null || true
        
        # Re-sign with entitlements
        sudo codesign --force --deep --sign - --entitlements "Prowser.entitlements" "/Applications/${APP_NAME}.app"
        
        if [ $? -eq 0 ]; then
            print_success "App re-signed with entitlements after installation"
        else
            print_warning "Failed to re-sign app after installation"
        fi
    fi
    
    # Set Prowser as default app for image files
    print_status "Setting Prowser as default app for image files..."
    
    # Check if duti is available (macOS utility for setting default apps)
    if command -v duti &> /dev/null; then
        print_status "Using duti to set default app associations..."
        
        # Set as default for common image formats
        duti -s com.prowser.app public.jpeg 2>/dev/null || print_warning "Could not set default for JPEG files"
        duti -s com.prowser.app public.png 2>/dev/null || print_warning "Could not set default for PNG files"
        duti -s com.prowser.app public.webp 2>/dev/null || print_warning "Could not set default for WebP files"
        duti -s com.prowser.app public.tiff 2>/dev/null || print_warning "Could not set default for TIFF files"
        duti -s com.prowser.app public.gif 2>/dev/null || print_warning "Could not set default for GIF files"
        duti -s com.prowser.app public.bmp 2>/dev/null || print_warning "Could not set default for BMP files"
        
        print_success "Default app associations set for image files"
    else
        print_warning "duti not found. Cannot automatically set default app associations."
        print_status "You can manually set Prowser as default by:"
        print_status "1. Right-click any image file → Get Info"
        print_status "2. Click 'Open with' → Select Prowser → 'Change All'"
    fi
    
    print_success "\nProwser successfully installed to /Applications!"
    print_status "You can now launch Prowser from Applications folder or Spotlight"
    print_status "Prowser is now the default app for opening image files"
}

# Fix entitlements for existing app
fix_existing_app_entitlements() {
    print_status "Fixing entitlements for existing Prowser app..."
    
    # Check if app exists in Applications
    if [ -d "/Applications/${APP_NAME}.app" ]; then
        print_status "Found existing app in /Applications"
        
        # Check if entitlements file exists
        if [ -f "$SCRIPT_DIR/Prowser.entitlements" ]; then
            print_status "Found entitlements file, applying to existing app..."
            
            # Copy entitlements to app bundle
            sudo cp "$SCRIPT_DIR/Prowser.entitlements" "/Applications/${APP_NAME}.app/Contents/"
            
            # Remove existing signature
            sudo codesign --remove-signature "/Applications/${APP_NAME}.app" 2>/dev/null || true
            
            # Re-sign with entitlements
            sudo codesign --force --deep --sign - --entitlements "$SCRIPT_DIR/Prowser.entitlements" "/Applications/${APP_NAME}.app"
            
            if [ $? -eq 0 ]; then
                print_success "Existing app entitlements fixed successfully"
                
                # Verify
                print_status "Verifying entitlements..."
                ENTITLEMENTS_OUTPUT=$(codesign -d --entitlements - "/Applications/${APP_NAME}.app" 2>/dev/null)
                if [ -n "$ENTITLEMENTS_OUTPUT" ] && echo "$ENTITLEMENTS_OUTPUT" | grep -q "com.apple.security"; then
                    print_success "Entitlements verified in existing app"
                else
                    print_warning "Entitlements may not have been applied properly"
                    print_status "Debug: Entitlements output was:"
                    echo "$ENTITLEMENTS_OUTPUT" | head -5
                fi
            else
                print_error "Failed to fix entitlements for existing app"
            fi
        else
            print_error "Entitlements file not found. Run the full build first."
        fi
    else
        print_error "Prowser app not found in /Applications"
    fi
}

# Cleanup function
cleanup() {
    # Prevent multiple cleanup calls
    if [ "${CLEANUP_CALLED:-false}" = "true" ]; then
        return 0
    fi
    CLEANUP_CALLED=true
    
    print_status "Cleaning up build artifacts..."
    
    # Deactivate virtual environment if active
    if [ -n "${VIRTUAL_ENV:-}" ]; then
        deactivate 2>/dev/null || true
    fi
    
    # Remove spec file
    if [ -f "$SPEC_FILE" ]; then
        rm -f "$SPEC_FILE" 2>/dev/null || true
        print_status "Removed $SPEC_FILE"
    fi
    
    # Remove backup spec file
    if [ -f "${SPEC_FILE}.backup" ]; then
        rm -f "${SPEC_FILE}.backup" 2>/dev/null || true
        print_status "Removed ${SPEC_FILE}.backup"
    fi
    
    # Remove generated analysis output (keep committed pyinstaller_dependencies.py)
    if [ -f "$SCRIPT_DIR/pyinstaller_directives.json" ]; then
        rm -f "$SCRIPT_DIR/pyinstaller_directives.json" 2>/dev/null || true
        print_status "Removed pyinstaller_directives.json"
    fi
    
    # Remove virtual environment (skip if --reuse or --keep to preserve venv)
    # Read from flag file so Ctrl-C handler has correct value (trap may not inherit vars)
    _preserve_flag=
    [ -f "$REUSE_FLAG_FILE" ] && _preserve_flag=$(cat "$REUSE_FLAG_FILE" 2>/dev/null)
    if [ -n "$_preserve_flag" ] && { [ "$_preserve_flag" = "reuse" ] || [ "$_preserve_flag" = "keep" ]; } && [ -d "$VENV_DIR" ]; then
        print_status "Preserved virtual environment (--reuse/--keep)"
    elif [ -d "$VENV_DIR" ]; then
        rm -rf "$VENV_DIR" 2>/dev/null || true
        print_status "Removed virtual environment"
    fi

    # Remove entitlements file
    if [ -f "$SCRIPT_DIR/Prowser.entitlements" ]; then
        rm -f "$SCRIPT_DIR/Prowser.entitlements" 2>/dev/null || true
        print_status "Removed Prowser.entitlements"
    fi
    
    # Clean build directory
    if [ -d "build" ]; then
        print_status "Cleaning build directory..."
        rm -rf "build" 2>/dev/null || true
    fi
    # Clean dist directory
    if [ -d "dist" ]; then
        print_status "Cleaning dist directory..."
        rm -rf "dist" 2>/dev/null || true
    fi
    
    # Note: .pyinstaller_face_models/ and .pyinstaller_whisper_models/ are preserved for reuse
    
    print_success "Cleanup completed"
}

# Main execution
main() {
    echo "PyInstaller Build Script for Prowser (with Dynamic Dependencies)"
    if [ "$MIN_BUILD" = "true" ]; then
        echo "Minimal build (--min): browse + similarity/CLIP; no imagegen, faces, or audio"
    fi
    echo "==============================================================="
    echo
    
    # Keep/reuse flags are set by early parsing below (before main)
    # Check for command line arguments
    if [ "$1" = "--fix-entitlements" ] || [ "$1" = "-f" ]; then
        print_status "Running entitlements fix only..."
        create_entitlements
        fix_existing_app_entitlements
        print_success "Entitlements fix completed!"
        exit 0
    elif [ "$1" = "--reuse" ] || [ "$1" = "-r" ]; then
        REUSE_VENV=true
        KEEP_FILES=true
        print_status "Reuse mode enabled - will reuse existing venv if present, keep build artifacts"
    elif [ "$1" = "--keep" ] || [ "$1" = "-k" ]; then
        KEEP_FILES=true
        print_status "Keep files mode enabled - temporary build files will be preserved"
    elif [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
        echo "Usage: $0 [OPTIONS]"
        echo ""
        echo "Options:"
        echo "  --fix-entitlements, -f    Fix entitlements for existing app without rebuilding"
        echo "  --reuse, -r               Reuse existing venv if present (implies --keep)"
        echo "  --keep, -k                Keep temporary build files (default: delete them)"
        echo "  --min, -m                 Minimal bundle: browse + similarity/CLIP only"
        echo "                            (omits imagegen, faces, LM Studio, voice/audio)"
        echo "  --help, -h                Show this help message"
        echo ""
        echo "Examples:"
        echo "  $0                    # Full build and install (deletes temp files)"
        echo "  $0 --reuse            # Reuse venv if present, keep build artifacts (faster rebuilds)"
        echo "  $0 --min              # Minimal app bundle (browse + CLIP; no imagegen/faces/audio)"
        echo "  $0 --keep             # Full build and install (keeps temp files)"
        echo "  $0 --fix-entitlements # Fix entitlements for existing app"
        echo ""
        exit 0
    fi
    
    # Check requirements
    check_requirements
    
    check_build_confirmation
    
    # Execute build steps
    create_dependency_analyzer
    create_venv
    install_dependencies
    install_project_dependencies
    analyze_dependencies
    install_missing_dependencies
    create_entitlements
    if [ "$MIN_BUILD" = "true" ]; then
        print_status "Minimal build: skipping face recognition model download"
    else
        download_face_recognition_models
    fi
    if [ "$MIN_BUILD" = "true" ]; then
        print_status "Minimal build: skipping whisper model download"
    else
        download_whisper_model
    fi
    create_spec_file
    customize_spec_file
    build_app
    verify_build
    install_to_applications
    
    # Export SCRIPT_DIR for Python scripts that need it
    export SCRIPT_DIR
    
    # Automatically fix entitlements after installation
    print_status "Automatically applying entitlements fix..."
    fix_existing_app_entitlements
    
    echo
    print_success "PyInstaller build completed successfully!"
    echo
    echo "Next steps:"
    echo "1. Prowser is now installed in /Applications and ready to use"
    echo "2. Launch Prowser from Applications folder or use Spotlight (Cmd+Space)"
    echo "3. The app bundle is also available locally at '$BUILD_DIR/${APP_NAME}.app'"
    if [ "$MIN_BUILD" = "true" ]; then
        echo "4. To create a minimal installer DMG: ./build_dmg.sh --min"
    else
        echo "4. To create an installer DMG: ./build_dmg.sh"
    fi
    echo
    echo "Note: The app bundle maintains proper macOS identity (name, icons, dock behavior)"
    echo "Note: Dependencies were analyzed dynamically from your actual code imports"
    echo "Note: Using onedir mode for better macOS compatibility"
    echo "Note: App installed to /Applications with proper permissions"
    echo "Note: Enhanced file association handling - double-clicking images should now open them directly"
    echo "Note: File association handling - new images will open in existing Prowser instance"
    echo "Note: App is now properly code-signed with entitlements for file operations"
    echo "Note: Entitlements have been automatically applied for file operations"
    echo "If you experience permission issues with file operations (delete/restore),"
    echo "run: $0 --fix-entitlements"
    
    # Clean up based on keep flag
    if [ "$KEEP_FILES" = "true" ]; then
        print_status "Build artifacts preserved in $VENV_DIR, $SPEC_FILE, and dependency files"
    else
        cleanup
        print_success "Build artifacts cleaned up"
    fi
}

# Parse --reuse and --keep early so they're set before create_venv/cleanup run
# Flag file: "reuse" = create_venv skips creation AND cleanup preserves venv
#            "keep"  = cleanup preserves venv only (create_venv still rebuilds)
REUSE_VENV=false
KEEP_FILES=false
for arg in "$@"; do
    case "$arg" in
        --reuse|-r) REUSE_VENV=true; KEEP_FILES=true ;;
        --keep|-k)  KEEP_FILES=true ;;
        --min|-m)   MIN_BUILD=true ;;
    esac
done
if [ "$MIN_BUILD" = "true" ]; then
    export PYINSTALLER_MIN_BUILD=1
fi
if [ "$REUSE_VENV" = "true" ]; then
    echo "reuse" > "$REUSE_FLAG_FILE"
elif [ "$KEEP_FILES" = "true" ]; then
    echo "keep" > "$REUSE_FLAG_FILE"
else
    rm -f "$REUSE_FLAG_FILE" 2>/dev/null || true
fi

# Run main function
main "$@"