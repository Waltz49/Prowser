#!/usr/bin/env python3
"""
Sort Mode Enum
Defines sorting modes for the image browser
"""

from enum import Enum


class SortMode(Enum):
    """Enum for sorting modes to replace multiple boolean flags"""
    DATE = "date"
    EXIF_DATE = "exif_date"
    EXIF_YEAR = "exif_year"
    NAME = "name" 
    SIZE = "size"
    FILESIZE = "filesize"  # File size in bytes (used by list view Size column)
    DIMENSIONS = "dimensions"
    PERMISSIONS = "permissions"  # File permissions (rwxrwxrwx format)
    CUSTOM = "custom"
    RANDOM = "random"
    DUPLICATES = "duplicates"
