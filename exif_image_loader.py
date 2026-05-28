#!/usr/bin/env python3
"""
EXIF Image Loader Utility
Provides EXIF-corrected image loading for both thumbnails and full images
"""

import os
from typing import Optional, Tuple
from PySide6.QtGui import QPixmap, QImage, QPainter, QColor
from PySide6.QtCore import Qt

# Module-level cache for noimage.svg conversion
_noimage_svg_cache = None
_noimage_composited_cache = None
_noimage_cache_settings = None  # (use_diamonds, transparency_color_rgb) tuple


def load_noimage_thumbnail(size: int) -> QPixmap:
    """
    Load the noimage.svg file and scale it to the requested thumbnail size.
    Applies transparency background (checkerboard or solid color) based on settings.
    Uses caching to convert the SVG only once per settings combination.
    
    Args:
        size: Thumbnail size (width and height)
        
    Returns:
        QPixmap of the noimage.svg scaled to the requested size with appropriate background,
        or a blank pixmap if loading fails
    """
    global _noimage_svg_cache, _noimage_composited_cache, _noimage_cache_settings
    
    noimage_path = os.path.join(os.path.dirname(__file__), "assets", "noimage.svg")
    if not os.path.exists(noimage_path):
        # Fallback: return a blank pixmap if noimage.svg doesn't exist
        return QPixmap(size, size)
    
    # Get settings for transparency background
    try:
        from config import get_config, effective_browse_transparency
        config = get_config()
        settings = config.load_settings()
        tc, use_diamonds = effective_browse_transparency(settings)
        transparency_color_rgb = tuple(tc)
    except Exception:
        # Fallback to defaults if config fails
        use_diamonds = True
        transparency_color_rgb = (98, 98, 98)
    
    # Check if settings have changed (invalidate cache if so)
    current_settings = (use_diamonds, transparency_color_rgb)
    if _noimage_cache_settings != current_settings:
        _noimage_svg_cache = None
        _noimage_composited_cache = None
        _noimage_cache_settings = current_settings
    
    # Load and cache the raw SVG pixmap (only once)
    if _noimage_svg_cache is None:
        pixmap = QPixmap(noimage_path)
        if pixmap.isNull():
            return QPixmap(size, size)
        _noimage_svg_cache = pixmap
    
    # Check if the cached SVG has transparency
    has_alpha = _noimage_svg_cache.toImage().hasAlphaChannel()
    
    # If no transparency, just scale and return
    if not has_alpha:
        scaled_pixmap = _noimage_svg_cache.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if scaled_pixmap.isNull():
            return QPixmap(size, size)
        return scaled_pixmap
    
    # For transparent SVGs, we need to composite with background
    # Use a reasonable base size for compositing (we'll scale the result)
    # This avoids recompositing for every size request
    base_size = 512  # Reasonable base size for compositing
    
    # Check if we need to recomposite (cache miss or settings changed)
    if _noimage_composited_cache is None:
        # Scale SVG to base size for compositing
        scaled_svg = _noimage_svg_cache.scaled(base_size, base_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if scaled_svg.isNull():
            return QPixmap(size, size)
        
        # Create background pixmap at base size
        background_pixmap = QPixmap(base_size, base_size)
        background_pixmap.fill(QColor(0, 0, 0))  # Initialize with black
        
        # Fill with checkerboard pattern or transparency color
        transparency_color = QColor(transparency_color_rgb[0], transparency_color_rgb[1], transparency_color_rgb[2])
        if use_diamonds:
            from browse_view_handler import _draw_diamond_pattern
            _draw_diamond_pattern(background_pixmap)
        else:
            background_pixmap.fill(transparency_color)
        
        # Composite the scaled SVG on top of the background
        painter = QPainter(background_pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.drawPixmap(0, 0, scaled_svg)
        painter.end()
        
        # Cache the composited result
        _noimage_composited_cache = background_pixmap
    
    # Scale the cached composited pixmap to the requested size
    final_pixmap = _noimage_composited_cache.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    if final_pixmap.isNull():
        return QPixmap(size, size)
    return final_pixmap


def _qt_fallback_load_image(image_path: str, ignore_exif: bool) -> Optional[QPixmap]:
    """Qt fallback for image loading. Wrapped in try/except to prevent crashes (fix 5)."""
    try:
        if ignore_exif:
            image = QImage(image_path)
            if image.isNull():
                return None
            return QPixmap.fromImage(image)
        return QPixmap(image_path)
    except Exception:
        return None


def _qt_fallback_load_thumbnail(image_path: str, size: int, ignore_exif: bool) -> QPixmap:
    """Qt fallback for thumbnail loading. Wrapped in try/except to prevent crashes (fix 5)."""
    try:
        if ignore_exif:
            image = QImage(image_path)
            if image.isNull():
                return load_noimage_thumbnail(size)
            pixmap = QPixmap.fromImage(image)
        else:
            pixmap = QPixmap(image_path)
        if not pixmap.isNull():
            return pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return load_noimage_thumbnail(size)
    except Exception:
        return load_noimage_thumbnail(size)


def load_image_with_exif_correction(image_path: str, ignore_exif: bool = False) -> Optional[QPixmap]:
    """
    Load an image with EXIF orientation correction applied (optimized)
    
    Args:
        image_path: Path to the image file
        ignore_exif: If True, skip EXIF orientation correction and load raw image data
        
    Returns:
        QPixmap with EXIF orientation corrected (unless ignore_exif=True), or None if loading failed
    """
    # Check if file is SVG - PIL doesn't support SVG, so use Qt directly
    file_ext = os.path.splitext(image_path)[1].lower()
    if file_ext == '.svg':
        # Qt can handle SVG files on macOS
        pixmap = QPixmap(image_path)
        if not pixmap.isNull():
            return pixmap
        return None
    
    try:
        from pil_image_io import open_pil_with_exif_correction

        pil_img = open_pil_with_exif_correction(
            image_path, ignore_exif=ignore_exif, cr2_half_size=False
        )
        if pil_img is None:
            return _qt_fallback_load_image(image_path, ignore_exif)
        pixmap = pil_to_qpixmap(pil_img, preserve_alpha=True)
        if pixmap is None or pixmap.isNull():
            return _qt_fallback_load_image(image_path, ignore_exif)
        return pixmap

    except ImportError:
        # Fallback to Qt if PIL not available
        return _qt_fallback_load_image(image_path, ignore_exif)
    except Exception:
        # If PIL fails (e.g., unsupported format, corrupted file), fallback to Qt (fix 5)
        return _qt_fallback_load_image(image_path, ignore_exif)

def load_thumbnail_with_exif_correction(image_path: str, size: int, ignore_exif: bool = False) -> Optional[QPixmap]:
    """
    Load and create a thumbnail with EXIF orientation correction applied (optimized)
    
    Args:
        image_path: Path to the image file
        size: Thumbnail size (width and height)
        ignore_exif: If True, skip EXIF orientation correction and load raw image data
        
    Returns:
        QPixmap thumbnail with EXIF orientation corrected (unless ignore_exif=True), or None if loading failed
    """
    # Check if file is SVG - PIL doesn't support SVG, so use Qt directly
    file_ext = os.path.splitext(image_path)[1].lower()
    if file_ext == '.svg':
        # Qt can handle SVG files on macOS
        pixmap = QPixmap(image_path)
        if not pixmap.isNull():
            return pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return load_noimage_thumbnail(size)
    
    try:
        from pil_image_io import open_pil_with_exif_correction
        from PIL import Image

        pil_img = open_pil_with_exif_correction(
            image_path, ignore_exif=ignore_exif, cr2_half_size=True
        )
        if pil_img is None:
            return _qt_fallback_load_thumbnail(image_path, size, ignore_exif)
        pil_img.thumbnail((size, size), Image.Resampling.LANCZOS)
        pixmap = pil_to_qpixmap(pil_img)
        if pixmap is None or pixmap.isNull():
            return load_noimage_thumbnail(size)
        return pixmap

    except ImportError:
        return _qt_fallback_load_thumbnail(image_path, size, ignore_exif)
    except Exception:
        # If PIL fails (e.g., unsupported format, corrupted file), fallback to Qt (fix 5)
        return _qt_fallback_load_thumbnail(image_path, size, ignore_exif)

def _png_fallback_qpixmap(pil_image) -> Optional[QPixmap]:
    """Fallback: save PIL to PNG bytes and load via QPixmap. Avoids buffer lifetime issues."""
    try:
        import io
        buffer = io.BytesIO()
        pil_image.save(buffer, format='PNG')
        buffer.seek(0)
        pixmap = QPixmap()
        if not pixmap.loadFromData(buffer.getvalue()):
            return None
        if pixmap.isNull():
            return None
        return pixmap
    except Exception:
        return None


def pil_to_qpixmap(pil_image, preserve_alpha: bool = False) -> Optional[QPixmap]:
    """
    Convert PIL Image to QPixmap
    
    Args:
        pil_image: PIL Image object
        preserve_alpha: If True, preserve alpha channel for RGBA images (for browse view with diamond pattern).
                       If False, composite onto checkerboard pattern background (for thumbnails).
        
    Returns:
        QPixmap representation of the PIL image, or None if conversion failed
    """
    try:
        from PIL import Image
        from browse_view_handler import _draw_diamond_pattern

        # Fix 2: Validate dimensions before creating QImage
        if pil_image.width <= 0 or pil_image.height <= 0:
            return _png_fallback_qpixmap(pil_image)

        # Fix 3: Use PNG fallback for HEIF/AVIF - these can produce problematic buffers
        img_format = getattr(pil_image, 'format', None)
        if img_format and str(img_format).upper() in ('HEIF', 'AVIF', 'HEIC'):
            return _png_fallback_qpixmap(pil_image)
        
        # Handle RGBA images
        if pil_image.mode == 'RGBA':
            if preserve_alpha:
                # Preserve alpha channel - convert to ARGB format for QPixmap
                img_data = pil_image.tobytes('raw', 'RGBA')
                expected_size = pil_image.width * pil_image.height * 4
                if len(img_data) < expected_size:
                    return _png_fallback_qpixmap(pil_image)
                qimage = QImage(img_data, pil_image.width, pil_image.height,
                               pil_image.width * 4, QImage.Format_RGBA8888)
                qimage = qimage.copy()  # Fix 1: Force Qt to own buffer (avoids use-after-free)
                qimage = qimage.convertToFormat(QImage.Format_ARGB32)
                if qimage.isNull():
                    return None
                pixmap = QPixmap.fromImage(qimage)
                return pixmap if not pixmap.isNull() else None
            else:
                # Composite onto checkerboard pattern background (for thumbnails)
                checkerboard_pixmap = QPixmap(pil_image.width, pil_image.height)
                checkerboard_pixmap.fill(QColor(0, 0, 0))  # Initialize with black background
                _draw_diamond_pattern(checkerboard_pixmap)
                
                img_data = pil_image.tobytes('raw', 'RGBA')
                expected_size = pil_image.width * pil_image.height * 4
                if len(img_data) < expected_size:
                    return _png_fallback_qpixmap(pil_image)
                image_qimage = QImage(img_data, pil_image.width, pil_image.height,
                                      pil_image.width * 4, QImage.Format_RGBA8888)
                image_qimage = image_qimage.copy()  # Fix 1: Force Qt to own buffer
                image_qimage = image_qimage.convertToFormat(QImage.Format_ARGB32)
                if image_qimage.isNull():
                    return None
                image_pixmap = QPixmap.fromImage(image_qimage)
                if image_pixmap.isNull():
                    return None
                
                # Composite image onto checkerboard pattern
                painter = QPainter(checkerboard_pixmap)
                painter.setRenderHint(QPainter.Antialiasing, True)
                painter.drawPixmap(0, 0, image_pixmap)
                painter.end()
                
                pixmap = checkerboard_pixmap
                return pixmap
        elif pil_image.mode == 'LA':
            # LA mode is grayscale with alpha
            pil_image = pil_image.convert('RGBA')
            img_data = pil_image.tobytes('raw', 'RGBA')
            expected_size = pil_image.width * pil_image.height * 4
            if len(img_data) < expected_size:
                return _png_fallback_qpixmap(pil_image)
            if preserve_alpha:
                qimage = QImage(img_data, pil_image.width, pil_image.height,
                               pil_image.width * 4, QImage.Format_RGBA8888)
                qimage = qimage.copy()  # Fix 1: Force Qt to own buffer
                qimage = qimage.convertToFormat(QImage.Format_ARGB32)
                if qimage.isNull():
                    return None
                pixmap = QPixmap.fromImage(qimage)
                return pixmap if not pixmap.isNull() else None
            else:
                checkerboard_pixmap = QPixmap(pil_image.width, pil_image.height)
                checkerboard_pixmap.fill(QColor(0, 0, 0))
                _draw_diamond_pattern(checkerboard_pixmap)
                
                image_qimage = QImage(img_data, pil_image.width, pil_image.height,
                                      pil_image.width * 4, QImage.Format_RGBA8888)
                image_qimage = image_qimage.copy()  # Fix 1: Force Qt to own buffer
                image_qimage = image_qimage.convertToFormat(QImage.Format_ARGB32)
                if image_qimage.isNull():
                    return None
                image_pixmap = QPixmap.fromImage(image_qimage)
                if image_pixmap.isNull():
                    return None
                
                # Composite image onto checkerboard pattern
                painter = QPainter(checkerboard_pixmap)
                painter.setRenderHint(QPainter.Antialiasing, True)
                painter.drawPixmap(0, 0, image_pixmap)
                painter.end()
                
                pixmap = checkerboard_pixmap
                return pixmap
        elif pil_image.mode == 'P':
            # P mode is palette
            pil_image = pil_image.convert('RGBA')
            img_data = pil_image.tobytes('raw', 'RGBA')
            expected_size = pil_image.width * pil_image.height * 4
            if len(img_data) < expected_size:
                return _png_fallback_qpixmap(pil_image)
            if preserve_alpha:
                qimage = QImage(img_data, pil_image.width, pil_image.height,
                               pil_image.width * 4, QImage.Format_RGBA8888)
                qimage = qimage.copy()  # Fix 1: Force Qt to own buffer
                qimage = qimage.convertToFormat(QImage.Format_ARGB32)
                if qimage.isNull():
                    return None
                pixmap = QPixmap.fromImage(qimage)
                return pixmap if not pixmap.isNull() else None
            else:
                checkerboard_pixmap = QPixmap(pil_image.width, pil_image.height)
                checkerboard_pixmap.fill(QColor(0, 0, 0))
                _draw_diamond_pattern(checkerboard_pixmap)
                
                image_qimage = QImage(img_data, pil_image.width, pil_image.height,
                                      pil_image.width * 4, QImage.Format_RGBA8888)
                image_qimage = image_qimage.copy()  # Fix 1: Force Qt to own buffer
                image_qimage = image_qimage.convertToFormat(QImage.Format_ARGB32)
                if image_qimage.isNull():
                    return None
                image_pixmap = QPixmap.fromImage(image_qimage)
                if image_pixmap.isNull():
                    return None
                
                # Composite image onto checkerboard pattern
                painter = QPainter(checkerboard_pixmap)
                painter.setRenderHint(QPainter.Antialiasing, True)
                painter.drawPixmap(0, 0, image_pixmap)
                painter.end()
                
                pixmap = checkerboard_pixmap
                return pixmap
        elif pil_image.mode != 'RGB':
            # Convert other modes to RGB
            pil_image = pil_image.convert('RGB')
            img_data = pil_image.tobytes('raw', 'RGB')
            expected_size = pil_image.width * pil_image.height * 3
            if len(img_data) < expected_size:
                return _png_fallback_qpixmap(pil_image)
            qimage = QImage(img_data, pil_image.width, pil_image.height,
                           pil_image.width * 3, QImage.Format_RGB888)
            qimage = qimage.copy()  # Fix 1: Force Qt to own buffer
        else:
            # Already RGB
            img_data = pil_image.tobytes('raw', 'RGB')
            expected_size = pil_image.width * pil_image.height * 3
            if len(img_data) < expected_size:
                return _png_fallback_qpixmap(pil_image)
            qimage = QImage(img_data, pil_image.width, pil_image.height,
                           pil_image.width * 3, QImage.Format_RGB888)
            qimage = qimage.copy()  # Fix 1: Force Qt to own buffer
        
        # Check if QImage creation was successful
        if qimage.isNull():
            return None
        
        pixmap = QPixmap.fromImage(qimage)
        # Check if QPixmap conversion was successful
        if pixmap.isNull():
            return None
        
        return pixmap
        
    except Exception:
        # Fallback: save to PNG and load (fix 5 - catches any crash in above path)
        return _png_fallback_qpixmap(pil_image)


def get_image_dimensions_fast_metadata(image_path: str) -> Optional[Tuple[int, int]]:
    """
    Get image dimensions quickly for metadata purposes (no expensive transformations)
    
    This function is optimized for metadata loading where we only need dimensions,
    not the actual corrected image. It calculates what the dimensions would be
    after EXIF orientation correction without doing the expensive image transformation.
    
    Performance: ~0.001-0.005s vs 0.100-0.200s for full transformation
    
    Args:
        image_path: Path to the image file
        
    Returns:
        Tuple of (width, height) with EXIF orientation correction applied to dimensions only
    """
    result = get_image_dimensions_and_exif_date(image_path)
    if result:
        dimensions, _ = result
        return dimensions
    return None


def get_image_dimensions_and_exif_date(image_path: str) -> Optional[Tuple[Tuple[int, int], Optional[float]]]:
    """
    Get image dimensions and EXIF date/time quickly for metadata purposes (no expensive transformations)
    
    This function is optimized for metadata loading where we need dimensions and date/time,
    not the actual corrected image. It calculates what the dimensions would be
    after EXIF orientation correction without doing the expensive image transformation.
    Also extracts EXIF DateTimeOriginal/DateTimeDigitized if available.
    
    Performance: ~0.001-0.005s vs 0.100-0.200s for full transformation
    
    Args:
        image_path: Path to the image file
        
    Returns:
        Tuple of ((width, height), exif_timestamp) where:
        - (width, height): Dimensions with EXIF orientation correction applied
        - exif_timestamp: Unix timestamp from EXIF DateTimeOriginal/DateTimeDigitized, or None if not available
    """
    try:
        from cr2_raw_loader import is_cr2_path, get_cr2_dimensions_from_raw
        if is_cr2_path(image_path):
            from exif_utils import get_exif_orientation_from_path, get_exif_timestamp_from_image_path
            original_size = get_cr2_dimensions_from_raw(image_path)
            if original_size is None:
                return None
            orientation = get_exif_orientation_from_path(image_path)
            exif_timestamp = get_exif_timestamp_from_image_path(image_path)
            if orientation and orientation != 1:
                if orientation in [3, 4]:
                    corrected_size = original_size
                elif orientation in [5, 6, 7, 8]:
                    corrected_size = (original_size[1], original_size[0])
                else:
                    corrected_size = original_size
            else:
                corrected_size = original_size
            return (corrected_size, exif_timestamp)

        from PIL import Image
        from exif_utils import get_exif_orientation_from_pil, get_exif_timestamp_from_pil

        with Image.open(image_path) as pil_img:
            # Get original dimensions (very fast - just header reading)
            original_size = pil_img.size
            orientation = get_exif_orientation_from_pil(pil_img)
            exif_timestamp = get_exif_timestamp_from_pil(pil_img)

            # Calculate corrected dimensions based on orientation
            if orientation and orientation != 1:
                if orientation in [3, 4]:  # 180 degree rotation
                    # Dimensions stay the same
                    corrected_size = original_size
                elif orientation in [5, 6, 7, 8]:  # 90/270 degree rotation
                    # Dimensions swap
                    corrected_size = (original_size[1], original_size[0])
                else:
                    corrected_size = original_size
            else:
                corrected_size = original_size
            
            return (corrected_size, exif_timestamp)
            
    except ImportError:
        # PIL not available for fast metadata
        return None
    except Exception as e:
        # Any error, fall back to slower method
        return None
