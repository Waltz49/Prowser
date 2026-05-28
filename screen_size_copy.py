#!/usr/bin/env python3
"""
Screen Size Copy Module
Creates a copy of an image resized to the physical screen size with various fit methods
"""

import os
from typing import Optional
from PIL import Image

from exif_utils import get_exif_bytes_from_pil, format_supports_exif
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

# macOS-specific imports
try:
    from AppKit import NSScreen
    MACOS_SCREEN_AVAILABLE = True
except ImportError:
    MACOS_SCREEN_AVAILABLE = False
    NSScreen = None


# Fit method constants
FIT_CONTAIN = "contain"  # Fit within bounds, no overflow (min scale)
FIT_COVER = "cover"  # Fill screen, may overflow (max scale)
FIT_WIDTH = "width"  # Match screen width exactly
FIT_HEIGHT = "height"  # Match screen height exactly


def get_physical_screen_size() -> QSize:
    """Get the screen size in points (logical size for display/wallpaper use).
    Uses NSScreen.frame() or QScreen.geometry() - both return logical pixels.
    Do NOT multiply by backingScaleFactor; that would produce oversized images."""
    try:
        if MACOS_SCREEN_AVAILABLE and NSScreen:
            screen = NSScreen.mainScreen()
            if screen:
                frame_size = screen.frame().size
                return QSize(int(frame_size.width), int(frame_size.height))
    except Exception:
        pass

    try:
        app = QApplication.instance()
        if app and app.primaryScreen():
            geom = app.primaryScreen().geometry()
            return QSize(geom.width(), geom.height())
    except Exception:
        pass

    return QSize(1920, 1080)


def generate_unique_filename(original_path: str) -> str:
    """Generate a unique filename with sequential suffix (e.g., foo-0001.png)
    
    Args:
        original_path: Path to the original file
        
    Returns:
        Path to a new file that doesn't exist yet
    """
    directory = os.path.dirname(original_path)
    filename = os.path.basename(original_path)
    name, ext = os.path.splitext(filename)
    
    # Try sequential numbers starting from 0001
    counter = 1
    while True:
        suffix = f"-{counter:04d}"  # Format as 0001, 0002, etc.
        new_filename = f"{name}{suffix}{ext}"
        new_path = os.path.join(directory, new_filename)
        
        if not os.path.exists(new_path):
            return new_path
        
        counter += 1
        
        # Safety limit to avoid infinite loop
        if counter > 9999:
            raise RuntimeError("Could not generate unique filename after 9999 attempts")


def _expected_output_dimensions(
    img_width: int,
    img_height: int,
    screen_width: int,
    screen_height: int,
    fit_method: str,
    borders_on_copy: bool,
) -> tuple:
    """Pixel size of the saved file for screen copy (after scaling; borders mode always outputs screen size)."""
    scale_x = screen_width / img_width
    scale_y = screen_height / img_height
    if not borders_on_copy:
        scale = min(scale_x, scale_y)
        return (int(img_width * scale), int(img_height * scale))
    return (screen_width, screen_height)


def check_image_needs_resize(
    image_path: str, fit_method: str = FIT_COVER, borders_on_copy: bool = True
) -> bool:
    """Return True if the image still needs processing for the chosen screen-copy mode.

    When borders_on_copy is True, the target is exact screen dimensions (screen_width x screen_height).
    When False, the target is aspect-preserving fit within the screen (no padding), like contain
    without letterboxing.

    Uses get_image_dimensions_fast_metadata (EXIF-corrected) to match status bar/metadata display."""
    if not os.path.exists(image_path):
        return False
    try:
        from exif_image_loader import get_image_dimensions_fast_metadata
        screen_size = get_physical_screen_size()
        screen_width = screen_size.width()
        screen_height = screen_size.height()
        dimensions = get_image_dimensions_fast_metadata(image_path)
        if dimensions and len(dimensions) == 2:
            img_width, img_height = dimensions
        else:
            with Image.open(image_path) as img:
                img_width, img_height = img.size
        tw, th = _expected_output_dimensions(
            img_width, img_height, screen_width, screen_height, fit_method, borders_on_copy
        )
        return (img_width, img_height) != (tw, th)
    except Exception as e:
        print(f"check_image_needs_resize error: {e}")
        return True  # If we can't check, assume resize is needed


def would_downsize(image_path: str, fit_method: str = FIT_COVER, borders_on_copy: bool = True) -> bool:
    """Return True if the given fit method would reduce the image's pixel dimensions.

    When borders_on_copy is False, scaling matches aspect-preserving fit within the screen (min scale).
    
    Args:
        image_path: Path to the image to check
        fit_method: One of 'contain', 'cover', 'width', 'height'
        borders_on_copy: If False, fit method is ignored for scale (same as contain).

    Returns:
        True if the computed scale factor is less than 1.0 (image would shrink)
    """
    if not os.path.exists(image_path):
        return False
    try:
        screen_size = get_physical_screen_size()
        screen_width = screen_size.width()
        screen_height = screen_size.height()
        with Image.open(image_path) as img:
            img_width, img_height = img.size
        scale_x = screen_width / img_width
        scale_y = screen_height / img_height
        if not borders_on_copy:
            scale = min(scale_x, scale_y)
        elif fit_method == FIT_CONTAIN:
            scale = min(scale_x, scale_y)
        elif fit_method == FIT_COVER:
            scale = max(scale_x, scale_y)
        elif fit_method == FIT_WIDTH:
            scale = scale_x
        elif fit_method == FIT_HEIGHT:
            scale = scale_y
        else:
            scale = max(scale_x, scale_y)
        return scale < 1.0
    except Exception as e:
        print(f"would_downsize error: {e}")
        return False  # If we can't check, don't warn


def create_screen_size_copy(
    image_path: str,
    fit_method: str = FIT_COVER,
    preserve_dates: bool = False,
    borders_on_copy: bool = True,
) -> Optional[str]:
    """Create a copy of the image resized to the physical screen size using the specified fit method

    Args:
        image_path: Path to the source image
        fit_method: One of 'contain', 'cover', 'width', 'height'
            - 'contain': Fits within screen bounds, no overflow (min scale)
            - 'cover': Fills screen, may overflow (max scale)
            - 'width': Matches screen width exactly
            - 'height': Matches screen height exactly
        preserve_dates: If True, copy original file's modification date to the new file
        borders_on_copy: If True, output is always screen_width x screen_height (crop or pad).
            If False, scale with aspect ratio preserved to fit within the screen (no padding/crop to screen).

    Returns:
        Path to the created copy, or None if failed
    """
    if not os.path.exists(image_path):
        return None
    
    try:
        # Get physical screen size
        screen_size = get_physical_screen_size()
        screen_width = screen_size.width()
        screen_height = screen_size.height()
        
        # Determine output format from extension (before processing)
        _, ext = os.path.splitext(image_path)
        ext_lower = ext.lower()
        
        # Map extension to PIL format
        format_map = {
            '.jpg': 'JPEG',
            '.jpeg': 'JPEG',
            '.png': 'PNG',
            '.gif': 'GIF',
            '.bmp': 'BMP',
            '.webp': 'WEBP',
            '.tiff': 'TIFF',
            '.tif': 'TIFF',
        }
        
        save_format = format_map.get(ext_lower, 'JPEG')
        
        # Formats that support transparency
        transparency_supported_formats = {'PNG', 'GIF', 'WEBP', 'TIFF'}
        preserve_transparency = save_format in transparency_supported_formats
        
        # Load the image
        with Image.open(image_path) as img:
            # Capture full EXIF from original (before any conversions) - always copy when available
            exif_bytes = get_exif_bytes_from_pil(img)
            # Apply EXIF orientation so dimensions match status bar/metadata (displayed size)
            try:
                from pil_image_io import apply_pil_exif_orientation

                img = apply_pil_exif_orientation(img, ignore_exif=False)
            except Exception:
                pass  # Use raw image if orientation helper fails
            # Handle transparency based on output format support
            if preserve_transparency:
                # Preserve transparency for formats that support it
                if img.mode == 'P':
                    # Check if palette has transparency
                    if 'transparency' in img.info:
                        img = img.convert('RGBA')
                    else:
                        img = img.convert('RGB')
                elif img.mode in ('RGBA', 'LA'):
                    # Keep RGBA/LA modes for transparency
                    pass
                elif img.mode != 'RGB':
                    # Convert other modes to RGB
                    img = img.convert('RGB')
            else:
                # Convert to RGB for formats that don't support transparency
                if img.mode in ('RGBA', 'LA', 'P'):
                    # Create a white background for transparent images
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                    img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
            
            # Get image dimensions
            img_width, img_height = img.size

            # Calculate scale based on fit method
            scale_x = screen_width / img_width
            scale_y = screen_height / img_height

            if not borders_on_copy:
                # Aspect-preserving fit within screen; no crop or pad to full screen
                scale = min(scale_x, scale_y)
            elif fit_method == FIT_CONTAIN:
                # Fit within bounds - use smaller scale (no overflow)
                scale = min(scale_x, scale_y)
            elif fit_method == FIT_COVER:
                # Fill screen - use larger scale (may overflow)
                scale = max(scale_x, scale_y)
            elif fit_method == FIT_WIDTH:
                # Match width exactly
                scale = scale_x
            elif fit_method == FIT_HEIGHT:
                # Match height exactly
                scale = scale_y
            else:
                # Default to cover if unknown method
                scale = max(scale_x, scale_y)

            # Calculate new dimensions
            new_width = int(img_width * scale)
            new_height = int(img_height * scale)

            # Resize the image using high-quality resampling
            resized_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

            # Crop or pad to exact screen dimensions when borders_on_copy (output is screen_width x screen_height)
            if borders_on_copy:
                if new_width > screen_width or new_height > screen_height:
                    # Cover: crop center to screen size
                    left = (new_width - screen_width) // 2
                    top = (new_height - screen_height) // 2
                    resized_img = resized_img.crop((left, top, left + screen_width, top + screen_height))
                elif new_width < screen_width or new_height < screen_height:
                    # Contain: paste centered on screen-sized canvas (letterboxing)
                    canvas = Image.new(resized_img.mode, (screen_width, screen_height), (0, 0, 0))
                    paste_x = (screen_width - new_width) // 2
                    paste_y = (screen_height - new_height) // 2
                    canvas.paste(resized_img, (paste_x, paste_y))
                    resized_img = canvas
            
            # Generate unique output filename
            output_path = generate_unique_filename(image_path)
            
            # Save options
            save_kwargs = {}
            if save_format == 'JPEG':
                save_kwargs['quality'] = 95  # High quality
            elif save_format == 'PNG':
                save_kwargs['compress_level'] = 6  # Good compression without being too slow
            elif save_format == 'WEBP':
                # Preserve transparency and quality
                if resized_img.mode in ('RGBA', 'LA'):
                    save_kwargs['lossless'] = True
                else:
                    save_kwargs['quality'] = 95
            elif save_format == 'TIFF':
                # TIFF supports transparency when saved as RGBA
                pass
            elif save_format == 'GIF':
                # PIL automatically handles transparency when saving RGBA as GIF
                # No special handling needed - PIL will convert RGBA to palette with transparency
                pass

            # Always copy EXIF to new file when available (JPEG, PNG, TIFF, WebP support it; GIF/BMP do not)
            if exif_bytes and format_supports_exif(save_format):
                save_kwargs['exif'] = exif_bytes

            resized_img.save(output_path, format=save_format, **save_kwargs)

            # Copy original modification date to new file when requested
            if preserve_dates:
                try:
                    mtime = os.path.getmtime(image_path)
                    atime = os.path.getatime(image_path)
                    os.utime(output_path, (atime, mtime))
                except OSError:
                    pass  # Ignore if we can't set dates (e.g. permission)

            return output_path
            
    except Exception as e:
        print(f"Error creating screen size copy: {e}")
        return None
    
    return None
