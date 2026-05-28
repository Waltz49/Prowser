#!/usr/bin/env python3
"""
Thumbnail Operations Manager for Image Browser
Handles thumbnail sizing, grid calculations, and layout management
"""

import math
from typing import Tuple
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication, QStyle

# Import constants from thumbnail_constants
from thumbnail_constants import (
    MIN_THUMBNAIL_SIZE, MAX_THUMBNAIL_SIZE, THUMBNAIL_SPACING,
    BORDER_SPACE, CANVAS_TOTAL_TOP_MARGIN,
    OVERLAY_LINE_HEIGHT, OVERLAY_SPACING, OVERLAY_PADDING
)

class ThumbnailOperationsManager:
    """Manages thumbnail sizing, grid calculations, and layout operations"""
    
    def __init__(self, main_window):
        self.main_window = main_window
    
    def _get_overlay_height_for_calculation(self) -> int:
        """Fast overlay height for size calculation. Name or size only: 1 line; both: 2 lines."""
        show_filename = getattr(self.main_window, 'thumbnail_filename_visible', False)
        show_size = getattr(self.main_window, 'show_image_size', False)
        if not show_filename and not show_size:
            return 0
        num_lines = 2 if (show_filename and show_size) else 1
        return OVERLAY_SPACING + (num_lines * OVERLAY_LINE_HEIGHT) + OVERLAY_PADDING
        
    def calculate_grid_for_images(self, num_images: int) -> Tuple[int, int, int]:
        """Calculate optimal grid dimensions for a given number of images"""
        if num_images == 0:
            return MIN_THUMBNAIL_SIZE, 1, 1
        
        # Get effective display size
        display_size = self.main_window.get_effective_display_size()
        available_width = display_size.width()
        available_height = display_size.height()
        
        if available_width <= 0 or available_height <= 0:
            return MIN_THUMBNAIL_SIZE, 1, 1
        elif num_images == 1:
            # For single image, use available space directly - do not cap at MAX_THUMBNAIL_SIZE.
            # MAX_THUMBNAIL_SIZE is for grid layouts; single thumbnail should fill the viewport
            # even when tree/preview sidebar is showing.
            single_size = int(min(available_width, available_height) * 0.8)
            return max(MIN_THUMBNAIL_SIZE, single_size), 1, 1
        
        # Account for scrollbar width
        scrollbar_width = self.main_window.get_scrollbar_width()
        available_width -= scrollbar_width
        
        # Account for canvas margins and centering (same as canvas calculation)
        from thumbnail_constants import BASE_MARGIN, CANVAS_TOTAL_TOP_MARGIN, CANVAS_TOTAL_BOTTOM_MARGIN
        # The canvas uses BASE_MARGIN * 2 for the base calculation
        # But the actual centering offset can be larger: max(BASE_MARGIN, (viewport_width - total_grid_width) // 2)
        # For safety, we'll use a conservative estimate of the minimum margin
        available_width -= (BASE_MARGIN * 2)
        
        # Overlay height for name/size text: 1 line if one shown, 2 if both (fast, no QFontMetrics)
        overlay_height = self._get_overlay_height_for_calculation()
        
        # Start with minimum size and work up
        best_efficiency = 0
        optimal_size = MIN_THUMBNAIL_SIZE
        best_columns = 1
        best_rows = 1
        
        # First, try to find the most natural grid layout for the number of images
        # For 5 images, prefer 2x3 over 3x2, for 6 images prefer 3x2, etc.
        # Find the layout that's closest to square, but prefer wider layouts for small numbers
        best_ratio = float('inf')
        natural_columns = 1
        natural_rows = num_images
        
        for cols in range(1, num_images + 1):
            rows = (num_images + cols - 1) // cols
            ratio = abs(cols - rows) / max(cols, rows)
            
            # For small numbers of images, prefer wider layouts (more columns)
            # Add a small penalty for taller layouts when ratios are equal
            width_preference = 0.0
            if num_images <= 4 and cols < rows:
                width_preference = 0.01  # Small penalty for taller layouts
            
            adjusted_ratio = ratio + width_preference
            
            if adjusted_ratio < best_ratio:
                best_ratio = adjusted_ratio
                natural_columns = cols
                natural_rows = rows
        
        # Try different thumbnail sizes, but prioritize the natural grid layout
        from thumbnail_constants import CANVAS_TOTAL_TOP_MARGIN, CANVAS_TOTAL_BOTTOM_MARGIN
        viewport_height = available_height - CANVAS_TOTAL_TOP_MARGIN - CANVAS_TOTAL_BOTTOM_MARGIN
        start_y = 0  # We already accounted for top margin in viewport_height
        
        for test_size in range(MIN_THUMBNAIL_SIZE, MAX_THUMBNAIL_SIZE + 1, 1):
            spacing = THUMBNAIL_SPACING
            cell_size = test_size + BORDER_SPACE + spacing  # For width
            rect_size = test_size + BORDER_SPACE  # Actual thumbnail rectangle size
            cell_height = rect_size + overlay_height + spacing  # Row height includes overlay
            
            # Columns must fit in available width - canvas uses same constraint
            max_columns_by_width = max(1, available_width // cell_size)
            columns = min(natural_columns, max_columns_by_width)
            if columns > num_images:
                columns = num_images
            rows = (num_images + columns - 1) // columns
            
            # Check if this configuration fits vertically (row = thumb + overlay, spacing between rows)
            last_row = rows - 1
            last_thumbnail_bottom = start_y + (last_row * cell_height) + rect_size + overlay_height
            
            # If doesn't fit vertically, try more columns (fewer rows) if width allows
            if last_thumbnail_bottom > viewport_height and max_columns_by_width > columns:
                # Calculate how many columns fit based on width
                columns = max(1, available_width // cell_size)
                if columns > num_images:
                    columns = num_images
                
                # Calculate rows needed
                rows = (num_images + columns - 1) // columns
                
                # Recalculate bottom position
                last_row = rows - 1
                last_thumbnail_bottom = start_y + (last_row * cell_height) + rect_size + overlay_height
            
            # Check if this size fits within viewport height
            if last_thumbnail_bottom <= viewport_height:
                # Calculate efficiency based on grid area
                total_grid_width = columns * cell_size
                total_grid_height = rows * cell_height - spacing
                efficiency = (total_grid_width * total_grid_height) / (available_width * available_height)
                
                # Prefer layouts that are closer to square grids (more natural for images)
                aspect_ratio_penalty = abs(columns - rows) / max(columns, rows)
                efficiency *= (1.0 - aspect_ratio_penalty * 0.1)  # Small penalty for non-square grids
                
                if efficiency > best_efficiency:
                    best_efficiency = efficiency
                    optimal_size = test_size
                    best_columns = columns
                    best_rows = rows
            # else: Size overflows, skip this size
        
        # Ensure we have reasonable grid dimensions
        if best_columns <= 1:
            # Use natural flow - let it adapt to available space
            spacing = THUMBNAIL_SPACING
            cell_size = MIN_THUMBNAIL_SIZE + BORDER_SPACE + spacing
            best_columns = max(1, available_width // cell_size)
            best_rows = (num_images + best_columns - 1) // best_columns
            optimal_size = MIN_THUMBNAIL_SIZE
        
        # Final validation: ensure the selected configuration doesn't overflow
        # Only apply overflow prevention if we're not at minimum size
        if optimal_size > 0 and optimal_size > MIN_THUMBNAIL_SIZE:
            spacing = THUMBNAIL_SPACING
            cell_size = optimal_size + BORDER_SPACE + spacing
            rect_size = optimal_size + BORDER_SPACE
            cell_height = rect_size + overlay_height + spacing
            last_row = best_rows - 1
            last_thumbnail_bottom = start_y + (last_row * cell_height) + rect_size + overlay_height
            
            # If it overflows and we're not at minimum size, try to reduce the number of rows by increasing columns
            if last_thumbnail_bottom > viewport_height:
                # Try to fit more columns to reduce rows
                max_possible_columns = min(num_images, available_width // cell_size)
                
                if max_possible_columns > best_columns:
                    # Try each possible number of columns from current to maximum
                    for test_columns in range(best_columns + 1, max_possible_columns + 1):
                        test_rows = (num_images + test_columns - 1) // test_columns
                        test_last_row = test_rows - 1
                        test_cell_height = rect_size + overlay_height + spacing
                        test_last_thumbnail_bottom = start_y + (test_last_row * test_cell_height) + rect_size + overlay_height
                        
                        if test_last_thumbnail_bottom <= viewport_height:
                            best_columns = test_columns
                            best_rows = test_rows
                            break  # Use the first configuration that fits
                
                # If still overflowing after trying more columns, reduce thumbnail size
                if last_thumbnail_bottom > viewport_height:
                    # Calculate maximum thumbnail size that fits in the available height
                    max_rows = (viewport_height - start_y) // cell_height
                    if max_rows > 0:
                        # Calculate the maximum thumbnail size that fits (per-row height minus overlay)
                        max_thumbnail_height = (viewport_height - start_y) // max_rows - overlay_height - spacing - BORDER_SPACE
                        if max_thumbnail_height >= MIN_THUMBNAIL_SIZE:
                            optimal_size = max_thumbnail_height
                            # Recalculate columns and rows with the new size
                            cell_size = optimal_size + BORDER_SPACE + spacing
                            best_columns = max(1, available_width // cell_size)
                            if best_columns > num_images:
                                best_columns = num_images
                            best_rows = (num_images + best_columns - 1) // best_columns
        
        return optimal_size, best_columns, best_rows

    def calculate_optimal_thumbnail_size_and_grid(self) -> Tuple[int, int, int]:
        """Calculate optimal thumbnail size and grid dimensions"""
        displayed = self.main_window.get_displayed_images()
        return self.calculate_grid_for_images(len(displayed))

    def calculate_optimal_thumbnail_size(self) -> int:
        """Calculate optimal thumbnail size"""
        size, _, _ = self.calculate_optimal_thumbnail_size_and_grid()
        return size

    def set_thumbnail_size(self, size: int) -> None:
        """Set thumbnail size and recalculate layout"""
        # Only enforce bounds if not manually set by user
        if not getattr(self.main_window, 'manual_thumbnail_size', False):
            size = max(MIN_THUMBNAIL_SIZE, min(MAX_THUMBNAIL_SIZE, size))
        else:
            # For manual sizing, only enforce maximum bound to prevent UI issues
            size = min(MAX_THUMBNAIL_SIZE, size)
        
        if size == self.main_window.current_thumbnail_size:
            return
        
        # Use smart update methods to avoid unnecessary rebuilding
        self.main_window.current_thumbnail_size = size
        
        self.main_window.status_notification.show_message(f"Thumbnail size: {size}px")
 
