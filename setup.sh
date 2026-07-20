#!/bin/bash
# Setup script for Native Image Browser

PYTHON_CMD="python3.14"

echo "Setting up Native Image Browser..."
echo "================================================"

# Check if Python 3 is available
if ! command -v $PYTHON_CMD &> /dev/null; then
    echo "Python 3 is required but not found. Please install Python 3.8 or higher."
    exit 1
fi

# Check Python version
python_version=$($PYTHON_CMD -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo "Found Python $python_version"

# Create virtual environment
echo "Creating virtual environment..."
$PYTHON_CMD -m venv venv_image_browser

# Activate virtual environment
echo "Activating virtual environment..."
source venv_image_browser/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip --quiet

# Install requirements
echo "Installing dependencies..."
echo "   - PySide6 (Qt for Python)"
echo "   - Pillow (Image processing)"
echo "   - mflux (Create menu image generation; large download)"
pip install -r minimal_requirements.txt

# Create sample images directory
echo "Creating sample images directory..."
mkdir -p sample_images

# Check if we can create sample images (use venv's Python to ensure Pillow is available)
if [ -f "venv_image_browser/bin/python" ]; then
    echo "Creating sample test images..."
    venv_image_browser/bin/python create_sample_images.py || echo "   (Sample image creation skipped - Pillow may need additional setup)"
fi

echo ""
echo "Setup complete!"
echo ""
echo "To run the application:"
echo "   1. Activate the environment: source venv_image_browser/bin/activate"
echo "   2. Run the app: python prowser.py [optional_directory_path]"
echo ""
echo "Or use the convenience script: python run.sh"
echo ""
echo "Press '/' or F1 in the app to see all keyboard shortcuts for the current view mode."
echo "================================================" 