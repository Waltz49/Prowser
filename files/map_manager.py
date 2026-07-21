#!/usr/bin/env python3
"""
Map Manager for Image Browser
Handles GPS location extraction from EXIF data and opening map applications
"""

import os
import subprocess
import time
import shutil
from typing import Optional, Tuple, List
from PySide6.QtWidgets import QMessageBox
from thumbnails.thumbnail_constants import YELLOW, GREEN, RESET
from config import get_config


def extract_exif_orientation(image_path: str) -> Optional[int]:
    """Extract EXIF orientation tag from image. Delegates to exif_utils."""
    from exif.exif_utils import get_exif_orientation_from_path
    return get_exif_orientation_from_path(image_path)


def extract_gps_from_exif(image_path: str) -> Optional[Tuple[float, float]]:
    """Extract GPS coordinates from EXIF data. Delegates to exif_utils."""
    from exif.exif_utils import get_gps_coords_from_path
    return get_gps_coords_from_path(image_path)


def check_app_available(app_name: str) -> bool:
    """
    Check if a macOS application is available
    
    Args:
        app_name: Name of the application (e.g., 'Maps', 'Google Earth', 'Google Chrome')
        
    Returns:
        True if app is available, False otherwise
    """
    try:
        # Use mdfind to check if app exists in Applications folder
        result = subprocess.run(
            ['mdfind', f'kMDItemFSName == "{app_name}.app"'],
            capture_output=True,
            text=True,
            timeout=2
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


def find_google_earth_app() -> Optional[str]:
    """
    Find available Google Earth application (tries Pro first, then regular)
    
    Returns:
        App name ('Google Earth Pro' or 'Google Earth') if found, None otherwise
    """
    if check_app_available('Google Earth Pro'):
        return 'Google Earth Pro'
    elif check_app_available('Google Earth'):
        return 'Google Earth'
    return None


def cleanup_kml_directory():
    """
    Clean up the KML directory by removing all files
    Called on app closure to ensure temporary rotated images are removed
    """
    try:
        config = get_config()
        kml_dir = config.kml_dir
        
        if kml_dir.exists():
            # Remove all files in the KML directory
            for file_path in kml_dir.iterdir():
                try:
                    if file_path.is_file():
                        file_path.unlink()
                    elif file_path.is_dir():
                        shutil.rmtree(file_path)
                except Exception:
                    pass  # Ignore errors during cleanup
    except Exception:
        pass  # Ignore errors during cleanup


def create_rotated_image_for_kml(image_path: str, orientation: int) -> Optional[str]:
    """
    Create a rotated image file for KML (Google Earth doesn't respect EXIF orientation)
    
    Args:
        image_path: Path to the original image file
        orientation: EXIF orientation value (1-8)
        
    Returns:
        Path to the rotated image file in KML directory, or None if creation failed
    """
    try:
        from pil_image_io import open_pil_with_exif_correction

        if not os.path.exists(image_path):
            return None

        # Get config to access KML directory
        config = get_config()
        kml_dir = config.kml_dir

        # Get the filename and create path in KML directory
        filename = os.path.basename(image_path)
        rotated_path = kml_dir / filename

        corrected_img = open_pil_with_exif_correction(
            image_path, ignore_exif=False, cr2_half_size=False
        )
        if corrected_img is None:
            return None

        # Convert to RGB if needed (for JPEG compatibility)
        if corrected_img.mode in ("RGBA", "LA", "P"):
            corrected_img = corrected_img.convert("RGB")

        # Save the corrected image (overwrite if exists - OK per requirements)
        corrected_img.save(rotated_path, quality=95)

        return str(rotated_path)
        
    except ImportError:
        # PIL not available
        return None
    except Exception:
        # Any error creating rotated image
        return None


def create_kml_file(image_data_list: List[Tuple[str, float, float, Optional[int]]]) -> str:
    """
    Create a temporary KML file with GPS coordinates for multiple images
    For images with EXIF orientation != 0, creates rotated versions in KML directory

    Args:
        image_data_list: List of tuples (image_path, latitude, longitude, orientation)
                        where orientation is EXIF orientation value (1-8) or None

    Returns:
        Path to the created KML file
    """
    from prowser_temp_files import prowser_mkstemp_path

    kml_path = prowser_mkstemp_path(prefix="image_browser_", suffix=".kml")
    try:
        if not image_data_list:
            raise ValueError("No image data provided")

        # Build placemarks for all images
        placemarks = []
        for idx, image_data in enumerate(image_data_list):
            # Format: (image_path, latitude, longitude, orientation)
            image_path, latitude, longitude, orientation = image_data

            fname = os.path.basename(image_path) if image_path else f"Image {idx + 1}"

            # Convert image path to file:// URL if provided
            image_href = None
            if image_path and os.path.exists(image_path):
                # Extract orientation if not provided
                if orientation is None:
                    orientation = extract_exif_orientation(image_path)
                
                # Only create rotated copy if orientation is not normal (orientation 1 = normal, 0 = undefined)
                # For performance and space reasons, use original path for normal orientation
                if orientation and orientation != 0 and orientation != 1:
                    rotated_path = create_rotated_image_for_kml(image_path, orientation)
                    if rotated_path and os.path.exists(rotated_path):
                        # Use the rotated image
                        image_href = f"file://{os.path.abspath(rotated_path)}"
                    else:
                        # Fallback to original if rotation failed
                        image_href = f"file://{os.path.abspath(image_path)}"
                else:
                    # Use original image for normal orientation (0, 1, or None)
                    image_href = f"file://{os.path.abspath(image_path)}"

            # Create image HTML (no CSS transform needed since image is pre-rotated)
            if image_href:
                image_html = f'<br/><img src="{image_href}" width="400"/>'
            else:
                image_html = ''

            placemark = f'''    <Placemark>
      <name>{fname}</name>
      <description><![CDATA[GPS location from<b> {fname}</b>{image_html}]]></description>
      <Point>
        <coordinates>{longitude},{latitude},0</coordinates>
      </Point>
      <styleUrl>#defaultStyle</styleUrl>
    </Placemark>'''
            placemarks.append(placemark)

        # No initial LookAt/center
        kml_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2">
  <Document>
{chr(10).join(placemarks)}
    <Style id="defaultStyle">
      <IconStyle>
        <scale>1.2</scale>
        <Icon>
          <href>http://maps.google.com/mapfiles/kml/pushpin/red-pushpin.png</href>
        </Icon>
      </IconStyle>
    </Style>
  </Document>
</kml>'''

        # Write KML content to file
        with open(kml_path, 'w', encoding='utf-8') as f:
            f.write(kml_content)

        return kml_path
    except Exception:
        try:
            os.remove(kml_path)
        except Exception:
            pass
        raise


def open_map_with_location(latitude: float, longitude: float, preferred_app: str = 'apple_maps', image_path: Optional[str] = None) -> bool:
    """
    Open a map application with the specified location
    
    Args:
        latitude: Latitude coordinate
        longitude: Longitude coordinate
        preferred_app: Preferred app ('apple_maps', 'google_maps', 'google_earth')
        image_path: Optional path to the image file (used for KML file creation)
        
    Returns:
        True if successfully opened, False otherwise
    """
    # Define app preferences with fallback order
    app_preferences = {
        'apple_maps': ['Maps', 'Google Earth', 'Google Chrome', 'Safari'],
        'google_maps': ['Google Chrome', 'Safari', 'Google Earth', 'Maps'],
        'google_earth': ['Google Earth', 'Maps', 'Google Chrome', 'Safari']
    }
    
    # Get preference order based on preferred app
    if preferred_app not in app_preferences:
        preferred_app = 'apple_maps'  # Default
    
    apps_to_try = app_preferences[preferred_app]
    
    # Try each app in order
    for idx, app_name in enumerate(apps_to_try):
        app_available = True
        app_failed = False
        
        if app_name == 'Maps':
            # Apple Maps - use open command with maps:// URL
            try:
                url = f"maps://?q={latitude},{longitude}"
                subprocess.run(['open', url], check=True, timeout=5)
                return True
            except Exception:
                app_failed = True
        
        elif app_name == 'Google Earth':
            # Google Earth - try Pro first, then regular
            google_earth_app = find_google_earth_app()
            if google_earth_app:
                try:
                    # Create temporary KML file with coordinates and image reference
                    # For backward compatibility, create single-image list
                    orientation = extract_exif_orientation(image_path) if image_path else None
                    image_data_list = [(image_path, latitude, longitude, orientation)] if image_path else [(None, latitude, longitude, None)]
                    kml_path = create_kml_file(image_data_list)
                    try:
                        # Open KML file with Google Earth Pro
                        subprocess.run(['open', '-a', google_earth_app, kml_path], check=True, timeout=5)
                        # Give Google Earth time to open the file, then delete it
                        # Use a background thread or delayed deletion to avoid blocking
                        def delete_kml_after_delay():
                            time.sleep(8)  # Wait 8 seconds for Google Earth to read the file
                            try:
                                if os.path.exists(kml_path):
                                    os.remove(kml_path)
                            except Exception:
                                pass
                        
                        import threading
                        cleanup_thread = threading.Thread(target=delete_kml_after_delay, daemon=True)
                        cleanup_thread.start()
                        return True
                    except Exception as e:
                        # Clean up KML file if opening failed
                        try:
                            if os.path.exists(kml_path):
                                os.remove(kml_path)
                        except Exception:
                            pass
                        raise
                except Exception:
                    app_failed = True
            else:
                app_available = False
        
        elif app_name == 'Google Chrome':
            # Google Maps in Chrome
            if check_app_available('Google Chrome'):
                try:
                    url = f"https://www.google.com/maps?q={latitude},{longitude}"
                    subprocess.run(['open', '-a', 'Google Chrome', url], check=True, timeout=5)
                    return True
                except Exception:
                    app_failed = True
            else:
                app_available = False
        
        elif app_name == 'Safari':
            # Google Maps in Safari (fallback)
            try:
                url = f"https://www.google.com/maps?q={latitude},{longitude}"
                subprocess.run(['open', '-a', 'Safari', url], check=True, timeout=5)
                return True
            except Exception:
                app_failed = True
        
        # Print fallback message if app failed or not available, and there's a next app to try
        if (not app_available or app_failed) and idx < len(apps_to_try) - 1:
            next_app = apps_to_try[idx + 1]
            print(f"{YELLOW}Error:{RESET} {app_name} not available. Trying {GREEN}{next_app}{RESET}")
    
    # None of the apps worked
    return False


def open_map_for_image(image_path: str, preferred_app: str = 'apple_maps') -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Extract GPS coordinates from image and open map application
    
    Args:
        image_path: Path to the image file
        preferred_app: Preferred map application
        
    Returns:
        Tuple of (success: bool, error_code: Optional[str], error_message: Optional[str])
        error_code is "NO_GPS_DATA" when no GPS data is found, None otherwise
    """
    # Check if file exists
    if not os.path.exists(image_path):
        return (False, None, "Image file not found or no longer exists.")
    
    # Extract GPS coordinates
    gps_coords = extract_gps_from_exif(image_path)
    
    if gps_coords is None:
        return (False, "NO_GPS_DATA", "No GPS location data found in EXIF metadata.")
    
    latitude, longitude = gps_coords
    
    # Try to open map application (pass image path for KML file)
    success = open_map_with_location(latitude, longitude, preferred_app, image_path)
    
    if not success:
        return (False, None, "No map applications are available. Please install Apple Maps, Google Maps, or Google Earth.")
    
    return (True, None, None)


def open_map_for_images(image_paths: List[str], preferred_app: str = 'apple_maps') -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Extract GPS coordinates from multiple images and open map application with KML file
    
    Args:
        image_paths: List of paths to image files
        preferred_app: Preferred map application (should be 'google_earth' for KML)
        
    Returns:
        Tuple of (success: bool, error_code: Optional[str], error_message: Optional[str])
        error_code is "NO_GPS_DATA" when no GPS data is found in any images, None otherwise
    """
    if not image_paths:
        return (False, None, "No images provided.")
    
    # Extract GPS coordinates and orientation for all images
    image_data_list = []
    images_without_gps = []
    
    for image_path in image_paths:
        # Check if file exists
        if not os.path.exists(image_path):
            continue
        
        # Extract GPS coordinates
        gps_coords = extract_gps_from_exif(image_path)
        
        if gps_coords is None:
            images_without_gps.append(os.path.basename(image_path))
            continue
        
        latitude, longitude = gps_coords
        
        # Extract EXIF orientation for rotation
        orientation = extract_exif_orientation(image_path)
        
        image_data_list.append((image_path, latitude, longitude, orientation))
    
    # Check if any images have GPS data
    if not image_data_list:
        # None of the images have GPS data
        total_checked = len(image_paths)
        if total_checked == 1:
            return (False, "NO_GPS_DATA", "No GPS location data found in the image.")
        else:
            return (False, "NO_GPS_DATA", f"No GPS location data found in any of the {total_checked} selected images.")
    
    # For Google Earth, create KML file with all images
    if preferred_app == 'google_earth':
        google_earth_app = find_google_earth_app()
        if google_earth_app:
            try:
                kml_path = create_kml_file(image_data_list)
                try:
                    # Open KML file with Google Earth
                    subprocess.run(['open', '-a', google_earth_app, kml_path], check=True, timeout=5)
                    # Give Google Earth time to open the file, then delete it
                    def delete_kml_after_delay():
                        time.sleep(8)  # Wait 8 seconds for Google Earth to read the file
                        try:
                            if os.path.exists(kml_path):
                                os.remove(kml_path)
                        except Exception:
                            pass
                    
                    import threading
                    cleanup_thread = threading.Thread(target=delete_kml_after_delay, daemon=True)
                    cleanup_thread.start()
                    return (True, None, None)
                except Exception as e:
                    # Clean up KML file if opening failed
                    try:
                        if os.path.exists(kml_path):
                            os.remove(kml_path)
                    except Exception:
                        pass
                    return (False, None, f"Failed to open Google Earth: {str(e)}")
            except Exception as e:
                return (False, None, f"Failed to create KML file: {str(e)}")
        else:
            return (False, None, "Google Earth is not available. Please install Google Earth or Google Earth Pro.")
    
    # For other apps, use the first image's location
    first_image_path, first_lat, first_lon = image_data_list[0]
    success = open_map_with_location(first_lat, first_lon, preferred_app, first_image_path)
    
    if not success:
        return (False, None, "No map applications are available. Please install Apple Maps, Google Maps, or Google Earth.")
    
    return (True, None, None)

