#!/usr/bin/env python3
"""
Configuration management for Image Browser
Handles all file paths and user-specific configurations
"""

# Standard library imports
import copy
import json
import os
import shutil
import getpass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BROWSE_TRANSPARENCY_THEME_IDS = ("dark", "light", "user")


def default_browse_transparency_entry() -> Dict[str, Any]:
    return {
        "transparency_color": [98, 98, 98],
        "use_diamonds": True,
        "browse_border_color": [0, 0, 0],
    }


def default_browse_transparency_settings() -> Dict[str, Dict[str, Any]]:
    ent = default_browse_transparency_entry()
    return {k: copy.deepcopy(ent) for k in BROWSE_TRANSPARENCY_THEME_IDS}


def merge_browse_transparency_settings(
    raw: Optional[dict],
    legacy_color: Optional[list] = None,
    legacy_use_diamonds: Optional[bool] = None,
) -> Dict[str, Dict[str, Any]]:
    """Per-ui_theme browse transparency (checkerboard vs solid). Migrates legacy top-level keys."""
    base = default_browse_transparency_settings()
    if isinstance(raw, dict) and raw:
        for tid in BROWSE_TRANSPARENCY_THEME_IDS:
            ent = raw.get(tid)
            if not isinstance(ent, dict):
                continue
            tc = ent.get("transparency_color")
            if isinstance(tc, (list, tuple)) and len(tc) >= 3:
                try:
                    base[tid]["transparency_color"] = [int(tc[0]), int(tc[1]), int(tc[2])]
                except (TypeError, ValueError):
                    pass
            if "use_diamonds" in ent:
                base[tid]["use_diamonds"] = bool(ent["use_diamonds"])
            bbc = ent.get("browse_border_color")
            if isinstance(bbc, (list, tuple)) and len(bbc) >= 3:
                try:
                    base[tid]["browse_border_color"] = [
                        int(bbc[0]),
                        int(bbc[1]),
                        int(bbc[2]),
                    ]
                except (TypeError, ValueError):
                    pass
        return base
    lc = legacy_color if isinstance(legacy_color, (list, tuple)) and len(legacy_color) >= 3 else [98, 98, 98]
    try:
        lc = [int(lc[0]), int(lc[1]), int(lc[2])]
    except (TypeError, ValueError):
        lc = [98, 98, 98]
    ld = bool(legacy_use_diamonds) if legacy_use_diamonds is not None else True
    for tid in BROWSE_TRANSPARENCY_THEME_IDS:
        base[tid] = {
            "transparency_color": list(lc),
            "use_diamonds": ld,
            "browse_border_color": [0, 0, 0],
        }
    return base


def effective_browse_transparency(settings: dict) -> Tuple[List[int], bool]:
    """Transparency color and checkerboard flag for the active ui_theme."""
    from theme_service import resolved_ui_theme_from_settings

    ui = resolved_ui_theme_from_settings(settings)
    if ui not in BROWSE_TRANSPARENCY_THEME_IDS:
        ui = "dark"
    merged = merge_browse_transparency_settings(
        settings.get("browse_transparency_settings"),
        settings.get("transparency_color"),
        settings.get("use_diamonds"),
    )
    ent = merged[ui]
    return list(ent["transparency_color"]), bool(ent["use_diamonds"])


def effective_browse_border_color(settings: dict) -> List[int]:
    """Letterbox / margin fill behind the image in browse mode when it does not fill the viewport."""
    from theme_service import resolved_ui_theme_from_settings

    ui = resolved_ui_theme_from_settings(settings)
    if ui not in BROWSE_TRANSPARENCY_THEME_IDS:
        ui = "dark"
    merged = merge_browse_transparency_settings(
        settings.get("browse_transparency_settings"),
        settings.get("transparency_color"),
        settings.get("use_diamonds"),
    )
    ent = merged[ui]
    bc = ent.get("browse_border_color", [0, 0, 0])
    if isinstance(bc, (list, tuple)) and len(bc) >= 3:
        try:
            return [int(bc[0]), int(bc[1]), int(bc[2])]
        except (TypeError, ValueError):
            pass
    return [0, 0, 0]


from theme_defaults import (
    default_dark_theme_colors,
    default_light_theme_colors,
    default_user_theme_colors,
)

class ImageBrowserConfig:
    """Configuration manager for Image Browser paths and settings"""
    
    def __init__(self, profile_dir: Optional[str] = None):
        self._user_id = getpass.getuser()
        self._uid = os.getuid()
        
        # Base directories
        if profile_dir:
            self._prowser_home = Path(profile_dir).expanduser().resolve()
        else:
            self._prowser_home = Path.home() / ".prowser"
        self._tmp_dir = Path("/tmp")
        
        # Ensure base directory exists
        self._prowser_home.mkdir(exist_ok=True)
        # Settings dialog live browse color preview (merged in load_settings only; never written by itself)
        self._browse_transparency_settings_preview: Optional[dict] = None
    
    def set_browse_transparency_preview(self, bts: Optional[dict]) -> None:
        """When set, load_settings() overlays this browse_transparency_settings (live color picker)."""
        self._browse_transparency_settings_preview = copy.deepcopy(bts) if bts is not None else None

    def _merge_browse_preview_into_loaded_settings(self, settings: dict) -> dict:
        prev = getattr(self, "_browse_transparency_settings_preview", None)
        if prev is None:
            return settings
        out = copy.deepcopy(settings)
        out["browse_transparency_settings"] = merge_browse_transparency_settings(prev)
        tc, ud = effective_browse_transparency(out)
        out["transparency_color"] = list(tc)
        out["use_diamonds"] = ud
        return out

    @property
    def user_id(self) -> str:
        """Get current user ID string"""
        return self._user_id
    
    @property
    def uid(self) -> int:
        """Get current user UID number"""
        return self._uid
    
    @property
    def prowsers_home(self) -> Path:
        """Get the base ~/.prowser directory"""
        return self._prowser_home
    
    @property
    def logs_dir(self) -> Path:
        """Get logs directory: ~/.prowser/logs/"""
        logs_dir = self._prowser_home / "logs"
        logs_dir.mkdir(exist_ok=True)
        return logs_dir
    
    @property
    def cache_dir(self) -> Path:
        """Get cache directory: ~/.prowser/cache/"""
        cache_dir = self._prowser_home / "cache"
        cache_dir.mkdir(exist_ok=True)
        return cache_dir
    
    @property
    def audio_dir(self) -> Path:
        """Get audio cache directory: ~/.prowser/audio/"""
        audio_dir = self._prowser_home / "audio"
        audio_dir.mkdir(exist_ok=True)
        return audio_dir
    
    @property
    def data_dir(self) -> Path:
        """Get data directory: ~/.prowser/data/"""
        data_dir = self._prowser_home / "data"
        data_dir.mkdir(exist_ok=True)
        return data_dir
    
    @property
    def settings_file(self) -> Path:
        """Get settings file path: ~/.prowser/data/settings.json"""
        return self.data_dir / "settings.json"
    
    # Debug log files (in ~/.prowser/logs/)
    
    @property
    def message_debug_log(self) -> Path:
        """Get message debug log path: ~/.prowser/logs/image_browser_message_debug.log"""
        return self.logs_dir / "image_browser_message_debug.log"
    
    @property
    def messages_log(self) -> Path:
        """Get messages log path: ~/.prowser/logs/messages"""
        return self.logs_dir / "messages.log"
    
    @property
    def keyboard_log(self) -> Path:
        """Get exception log path: ~/.prowser/logs/keyboard.log"""
        return self.logs_dir / "keyboard.log"

    @property
    def drag_drop_log(self) -> Path:
        """Get drag and drop log path: ~/.prowser/logs/drag_drop.log"""
        return self.logs_dir / "drag_drop.log"
    
    # Process management files (in ~/.prowser/data/)
    
    @property
    def named_pipe(self) -> Path:
        """Get named pipe path: /tmp/image_browser_pipe_{user_id}"""
        return self._tmp_dir / f"image_browser_pipe_{self._user_id}"
    
    # Cache directories (in ~/.prowser/cache/)
    
    @property
    def image_cache_dir(self) -> Path:
        """Get image cache directory: ~/.prowser/cache/image_browser_cache/"""
        cache_dir = self.cache_dir / "image_browser_cache"
        cache_dir.mkdir(exist_ok=True)
        return cache_dir
    
    @property
    def thumbnail_cache_dir(self) -> Path:
        """Get thumbnail cache directory: ~/.prowser/cache/image_browser_cache/thumbnails/"""
        thumb_dir = self.image_cache_dir / "thumbnails"
        thumb_dir.mkdir(exist_ok=True)
        return thumb_dir
    
    @property
    def metadata_cache_dir(self) -> Path:
        """Get metadata cache directory: ~/.prowser/cache/image_browser_cache/metadata/"""
        meta_dir = self.image_cache_dir / "metadata"
        meta_dir.mkdir(exist_ok=True)
        return meta_dir
    
    @property
    def hash_cache_dir(self) -> Path:
        """Get hash cache directory: ~/.prowser/cache/hashes/"""
        hash_dir = self.cache_dir / "hashes"
        hash_dir.mkdir(exist_ok=True)
        return hash_dir
    
    @property
    def image_recognition_cache_dir(self) -> Path:
        """Get image recognition cache directory: ~/.prowser/cache/image_recognition/"""
        recognition_dir = self.cache_dir / "image_recognition"
        recognition_dir.mkdir(exist_ok=True)
        return recognition_dir
    
    @property
    def kml_dir(self) -> Path:
        """Get KML directory: ~/.prowser/kml/"""
        kml_dir = self._prowser_home / "kml"
        kml_dir.mkdir(exist_ok=True)
        return kml_dir
    
    # Audio cache files (in ~/.prowser/audio/)
    
    def ensure_directories(self):
        """Ensure all required directories exist"""
        directories = [
            self.logs_dir,
            self.cache_dir,
            self.audio_dir,
            self.data_dir,
            self.image_cache_dir,
            self.thumbnail_cache_dir,
            self.metadata_cache_dir,
            self.hash_cache_dir,
            self.image_recognition_cache_dir,
            self.kml_dir,
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
    
    def get_cache_info(self) -> dict:
        """Get information about cache usage"""
        info = {
            'user_id': self.user_id,
            'uid': self.uid,
            'prowser_home': str(self.prowsers_home),
            'cache_dir': str(self.cache_dir),
            'logs_dir': str(self.logs_dir),
            'audio_dir': str(self.audio_dir),
            'data_dir': str(self.data_dir),
            'named_pipe': str(self.named_pipe),
        }
        
        # Add directory sizes
        try:
            info['cache_size'] = shutil.disk_usage(self.cache_dir).used
            info['logs_size'] = shutil.disk_usage(self.logs_dir).used
            info['audio_size'] = shutil.disk_usage(self.audio_dir).used
        except Exception:
            info['cache_size'] = 0
            info['logs_size'] = 0
            info['audio_size'] = 0
        
        return info
    
    def load_settings(self) -> dict:
        """Load user settings from ~/.prowser/data/settings.json"""
        default_settings = {
            'debug_mode': False,
            'confirm_delete': True,
            'browse_view_actual_size': False,
            # ms on same browse image before recording to Image History (0 = immediate; max 5000; 500 ms steps in UI)
            'browse_image_history_save_after_ms': 3000,
            'wrap_around': True,  # Wrap around when navigating past first/last image
            'slideshow_rate': 5000,
            'slideshow_transition_speed': 1300,
            'slideshow_direction': 'right',
            'slideshow_max_rotation': 0,
            'slideshow_overlap_delay': -200,
            'space_key_mode': 'exit',
            'slideshow2_enlargement': 2.0,  # Default to 2.0x for visible panning effect
            'slideshow2_speed': 8,  # pixels per second (slow for landscape viewing)
            'filtered_tree': 'images',  # 'all', 'images', or 'use_filter'
            # Enhanced similarity settings (hidden section defaults)
            'similarity_mode': 'accurate',
            'multimodal_hash': True,
            # hash_size removed - always 16, not configurable
            # CNN similarity metric: 'cosine', 'euclidean', 'manhattan', 'clip'
            'similarity_metric': 'cosine',
            # CLIP-based search settings (backward compatibility)
            'clip_prompt': '',  # Text prompt for CLIP-based search
            'clip_recursive': False,  # Whether to search recursively in subdirectories
            'clip_similarity_threshold': 0.20,  # Minimum similarity score (0.0-1.0) for CLIP search filtering. Default 0.20 for loose filtering.
            'cnn_recursive': False,  # Whether to search recursively in subdirectories for CNN similarity search
            'clip_model_name': 'openai/clip-vit-base-patch32',  # CLIP model to use for similarity search
            'resnet_model': 'resnet18',  # ResNet model to use for CNN similarity: 'resnet18', 'resnet50', 'resnet101'
            'background_clip_enabled': False,  # Enable background CLIP extraction for Favorites and Recently Used directories
            'background_clip_gather_thumbnails': True,  # When background CLIP is enabled, also gather thumbnails for uncached images
            'background_clip_extract_faces': False,  # When background CLIP is enabled, also extract and cache face encodings
            
            # UI settings
            'ui_theme': 'user',  # 'dark', 'light', 'user', or 'system' — global Qt stylesheet and synced palette
            # Custom colors for User preset (hex strings; keys match theme_service.USER_THEME_COLOR_KEYS)
            'user_theme_colors': default_user_theme_colors(),
            # Custom colors when ui_theme == 'dark' (defaults match built-in dark palette)
            'dark_theme_colors': default_dark_theme_colors(),
            # Custom colors when ui_theme == 'light' (defaults match built-in light palette)
            'light_theme_colors': default_light_theme_colors(),
            'file_tree_visible': True,  # Default to showing file tree
            'status_bar_visible': True,  # Default to showing status bar
            'thumbnail_filename_visible': False,  # Default to hiding thumbnail filenames
            'preview_visible': False,  # Default to hiding preview panel
            'sidebar_width': 300,  # Default width for combined sidebar (tree + preview)
            'right_sidebar_width': 300,  # Default width for right sidebar (info panel)
            'right_sidebar_visible': False,  # Default to hiding right sidebar (legacy; derived from information/shortcuts)
            'information_sidebar_visible': False,  # Default to hiding Information widget (I key)
            'shortcuts_sidebar_visible': False,  # Default to hiding Shortcuts within right_sidebar (O key)
            'shortcuts_sidebar_scroll_position': 0,  # Vertical scroll position for Shortcuts widget
            'shortcuts_splitter_sizes': [250, 150],  # [information_height, shortcuts_height] for right sidebar splitter
            'list_view_row_height': 48,  # Default row height for list view (28-64px)
            
            # External editor settings
            'image_editor_app': 'Preview',  # Default image editor application name
            
            # Sorting settings
            'sort_mode': 'date',  # Sort mode: 'date', 'name', 'size', 'random', 'custom', 'duplicates'
            'sort_reversed': False,  # Default to ascending order (newest first for date)

            'rename_custom_prefix': '',
            'rename_increment_length': 5,  # Default to 5 digits
            'rename_starting_number': 1,  # Default starting number
            'rename_prefix_template': 'image-{number:04d}',  # Template for rename status display
            'increment_length': 4,  # Default increment length for rename status (used by sidebar)
            'rename_status_max_depth': 3,  # Maximum depth for rename status checking
            'rename_date_change_mode': 'none',  # Date change mode for rename operations: 'none', 'modify', 'access', 'both'
            
            # Move destinations (9 items, None where empty)
            'move_destinations': [None] * 9,
            # Destination menu action: 'none' (hide menu items), 'copy', 'move' - controls menu/keys behavior
            'destination_menu_action': 'move',
            # Move keys mode: 'not_links' (no clickable links), 'move', 'copy'
            'move_keys_mode': 'not_links',
            
            # Favorite directories (9 items, None where empty) - accessible via Ctrl+1 through Ctrl+9
            'favorite_directories': [None] * 9,
            
            # Exclude directories (list of dicts with 'path' and 'enabled' keys)
            'exclude_directories': [],
            
            # Image creation directory (generated images; disabled => ~/Downloads)
            'image_creation_directory': {'path': None, 'enabled': False},

            # Ignore directories (list of dicts with 'path' and 'enabled' keys to ignore in search, find duplicates, etc.)
            'ignore_directories': [{'path': None, 'enabled': False}] * 3,
            
            # Root directories to show in file tree (macOS)
            'root_directories': ['/Users', '/Volumes', '/tmp'],
            
            # Process hidden directories in searches and file operations (default: False)
            'show_hidden_directories': False,
            
            # Follow symbolic and hard links in tree view (default: False)
            'follow_symlinks': False,
            
            # Use diamond checkerboard pattern for browse view background (default: True)
            'use_diamonds': True,
            
            # Always show directories named 'work' in file tree (default: False)
            'always_show_work': False,
            
            # Drag/Drop auto date change: automatically update image file dates when moving thumbnails while sorted by date (default: False)
            'drag_drop_auto_date_change': False,
            
            # Allow thumbnail locking functions (Experimental): enable cmd-L and shift-cmd-L shortcuts for locking files (default: False)
            'allow_thumbnail_locking': False,
            
            # Allow quick mass rename: enable Quick Mass Rename function (default: False)
            'allow_quick_mass_rename': False,
            
            # Show extensions in thumbnail name overlays (default: False)
            'show_extensions': False,
            
            # Show image size (width x height) in thumbnail overlays (default: False, independent of filename display)
            'show_image_size': False,
            
            # EXIF rotation settings
            'ignore_exif_rotation': False,  # Default: use EXIF rotation (checkbox checked by default, ignore_exif=False means use EXIF)
            
            # Date display settings
            'use_exif_date': True,  # Default: use EXIF date if available, otherwise use file date
            
            # Transparency color for browse view background (RGB tuple, default light gray)
            'transparency_color': [98, 98, 98],  # Light gray RGB values — mirror of active ui_theme entry
            
            # Per-theme browse transparency (solid color vs checkerboard for transparent pixels)
            'browse_transparency_settings': default_browse_transparency_settings(),
            
            # Image file extensions (defaults: jpg, jpeg, png, webp)
            'image_extensions': ['.jpg', '.jpeg', '.png', '.webp'],
            
            # State restoration settings
            'restore_state': {
                'enabled': True,
                'last_file': None,
                'last_directory': None,
                'last_view_mode': 'thumbnail',
                'last_os_fullscreen': None  # None = not set, True/False = saved state
            },
            
            # Saved filter patterns list
            'saved_filters': [],

            # Settings dialog window size [width, height] (restored on open; updated after resize / tab fit)
            'settings_dialog_size': [920, 680],

            # AI Captioning (LMStudio) settings
            **CAPTION_DEFAULTS,

            # Local image generation plugins (per-model persisted params)
            **IMAGEGEN_DEFAULTS,
        }
        
        try:
            if self.settings_file.exists():
                # Check if file is empty or too small (corrupted)
                file_size = self.settings_file.stat().st_size
                if file_size == 0:
                    # File is empty, treat as if it doesn't exist
                    self.save_settings(default_settings)
                    return self._merge_browse_preview_into_loaded_settings(default_settings)
                
                with open(self.settings_file, 'r') as f:
                    content = f.read().strip()
                    if not content:
                        # File is empty or whitespace only
                        self.save_settings(default_settings)
                        return self._merge_browse_preview_into_loaded_settings(default_settings)
                    
                    settings = json.loads(content)
                    # Merge with defaults to handle missing keys
                    needs_save = False
                    # Only check keys missing from settings
                    missing_keys = default_settings.keys() - settings.keys()
                    if missing_keys:
                        for key in missing_keys:
                            # Filled by merge_browse_transparency_settings below (uses legacy keys if present)
                            if key == "browse_transparency_settings":
                                continue
                            settings[key] = default_settings[key]
                        needs_save = True
                    # Validate image_extensions format
                    if 'image_extensions' in settings:
                        extensions = settings['image_extensions']
                        if not isinstance(extensions, list) or len(extensions) == 0:
                            settings['image_extensions'] = default_settings['image_extensions']
                            needs_save = True
                    # Normalize per-theme browse transparency; mirror legacy keys for active theme
                    prev_bts = settings.get("browse_transparency_settings")
                    raw_bts = prev_bts if isinstance(prev_bts, dict) and prev_bts else None
                    settings["browse_transparency_settings"] = merge_browse_transparency_settings(
                        raw_bts,
                        settings.get("transparency_color"),
                        settings.get("use_diamonds"),
                    )
                    tc, ud = effective_browse_transparency(settings)
                    if (
                        settings.get("transparency_color") != tc
                        or settings.get("use_diamonds") != ud
                        or prev_bts != settings["browse_transparency_settings"]
                    ):
                        settings["transparency_color"] = list(tc)
                        settings["use_diamonds"] = ud
                        needs_save = True
                    # Save if defaults were added or validation fixed something
                    if needs_save:
                        self.save_settings(settings)
                    return self._merge_browse_preview_into_loaded_settings(settings)
            else:
                # File doesn't exist, save defaults
                self.save_settings(default_settings)
                return self._merge_browse_preview_into_loaded_settings(default_settings)
        except json.JSONDecodeError as e:
            print(f"Error loading settings (JSON decode error): {e}")
            # File is corrupted, backup and recreate
            try:
                if self.settings_file.exists():
                    # Backup corrupted file
                    backup_path = self.settings_file.with_suffix('.json.bak')
                    shutil.copy2(self.settings_file, backup_path)
            except Exception:
                pass
            # On error, save defaults and return them
            try:
                self.save_settings(default_settings)
            except Exception:
                pass
            return self._merge_browse_preview_into_loaded_settings(default_settings)
        except Exception as e:
            print(f"Error loading settings: {e}")
            # On error, save defaults and return them
            try:
                self.save_settings(default_settings)
            except Exception:
                pass
            return self._merge_browse_preview_into_loaded_settings(default_settings)
    
    def save_settings(self, settings: dict):
        """Save user settings to ~/.prowser/data/settings.json"""
        try:
            # Ensure data directory exists before saving
            self.data_dir.mkdir(parents=True, exist_ok=True)
            # Write to a temporary file first, then rename (atomic write)
            import tempfile
            temp_file = self.settings_file.with_suffix('.json.tmp')
            with open(temp_file, 'w') as f:
                json.dump(settings, f, indent=2)
                f.flush()
                os.fsync(f.fileno())  # Force write to disk
            # Atomic rename
            temp_file.replace(self.settings_file)
        except Exception as e:
            print(f"Error saving settings: {e}")
    
    def update_setting(self, key: str, value):
        """Update a single setting and save to file"""
        if key == "browse_transparency_settings":
            self._browse_transparency_settings_preview = None
        settings = self.load_settings()
        # Normalize filter patterns when saving
        if key == 'filter_pattern':
            value = self.normalize_filter_pattern(value)
        settings[key] = value
        if key == "browse_transparency_settings":
            settings["browse_transparency_settings"] = merge_browse_transparency_settings(
                settings.get("browse_transparency_settings"),
                None,
                None,
            )
            tc, ud = effective_browse_transparency(settings)
            settings["transparency_color"] = list(tc)
            settings["use_diamonds"] = ud
        elif key == "ui_theme":
            tc, ud = effective_browse_transparency(settings)
            settings["transparency_color"] = list(tc)
            settings["use_diamonds"] = ud
        self.save_settings(settings)
    
    @staticmethod
    def normalize_filter_pattern(pattern: Optional[str]) -> Optional[str]:
        """Remove trailing asterisk from filter pattern for storage/display"""
        if not pattern:
            return '*' # DGN testing returning * if no pattern
        return f"{pattern.rstrip('*')}*" # DGN testing adding * to pattern if no pattern
    
    @staticmethod
    def get_filter_pattern_for_matching(pattern: Optional[str]) -> Optional[str]:
        """Add trailing asterisk to filter pattern for fnmatch usage"""
        if not pattern:
            return pattern
        # Only add asterisk if pattern doesn't already contain wildcard characters
        # Check if pattern already has *, ?, or [ character patterns
        if '*' in pattern or '?' in pattern or '[' in pattern:
            return pattern
        return pattern + '*'
    
    def save_restore_state(self, file_path: Optional[str], directory: Optional[str], view_mode: str, os_fullscreen: Optional[bool] = None):
        """Save the current state for restoration on next startup"""
        settings = self.load_settings()
        if 'restore_state' not in settings:
            settings['restore_state'] = {}
        
        settings['restore_state']['last_file'] = file_path
        settings['restore_state']['last_directory'] = directory
        settings['restore_state']['last_view_mode'] = view_mode
        settings['restore_state']['last_os_fullscreen'] = os_fullscreen
        settings['restore_state']['enabled'] = True
        
        self.save_settings(settings)
    
    def get_restore_state(self) -> Optional[dict]:
        """Get the saved state for restoration"""
        settings = self.load_settings()
        restore_state = settings.get('restore_state', {})
        
        if not restore_state.get('enabled', False):
            return None
        
        # Check if the saved file still exists
        last_file = restore_state.get('last_file')
        if last_file and not os.path.exists(last_file):
            # File no longer exists, clear the state
            self.clear_restore_state()
            return None
        
        # Check if the saved directory still exists
        last_directory = restore_state.get('last_directory')
        if last_directory and not os.path.exists(last_directory):
            # Directory no longer exists, clear the state
            self.clear_restore_state()
            return None
        
        return restore_state
    
    def clear_restore_state(self):
        """Clear the saved restoration state"""
        settings = self.load_settings()
        if 'restore_state' in settings:
            settings['restore_state']['enabled'] = False
            settings['restore_state']['last_file'] = None
            settings['restore_state']['last_directory'] = None
            settings['restore_state']['last_view_mode'] = 'thumbnail'
            settings['restore_state']['last_os_fullscreen'] = None
            self.save_settings(settings)
    
    def get_saved_filters(self) -> List[str]:
        """Get the list of saved filter patterns"""
        settings = self.load_settings()
        filters = settings.get('saved_filters', [])
        # Ensure we return a list of strings, filtering out None and empty values
        # Filters are stored without trailing *, so return as-is
        return [f for f in filters if f and isinstance(f, str) and f.strip() and f.strip() != '*']
    
    def save_filters(self, filters: List[str]):
        """Save the list of filter patterns"""
        settings = self.load_settings()
        # Normalize and filter filters
        normalized_filters = []
        seen = set()
        for pattern in filters:
            if pattern and isinstance(pattern, str):
                pattern = pattern.strip()
                if pattern and pattern != '*':
                    # Store pattern without trailing * for cleaner display
                    # Remove trailing * if present
                    if pattern.endswith('*'):
                        pattern = pattern[:-1]
                    # Avoid duplicates and empty patterns
                    if pattern and pattern not in seen:
                        normalized_filters.append(pattern)
                        seen.add(pattern)
        settings['saved_filters'] = normalized_filters
        self.save_settings(settings)
    
# System defaults for optional imagegen plugins (package may be absent in some builds)
IMAGEGEN_DEFAULTS = {
    "imagegen": {
        "active_plugin_by_function": {
            "create": "flux_schnell_mflux",
        },
        "last_function": "create",
        "lora_catalog": {
            "enabled_ids": [
                "mspaint1",
                "super_realism",
                "sldr_nsfw_v2",
                "pola_photo_flux",
                "paper_cutout",
            ],
            "deleted_ids": [],
        },
        "models": {
            "flux_schnell_mflux": {
                "prompt": "",
                "width": 1024,
                "height": 1024,
                "steps": 4,
                "guidance_scale": 3.5,
                "mflux_quantize": 3,
                "seed": 0,
                "random_seed": True,
                "low_ram": False,
                "show_progressive_images": False,
            },
        },
    },
}

# System defaults for AI captioning (used by settings dialog reset and lmstudio_caption fallback)
CAPTION_DEFAULTS = {
    'caption_lms_host': 'localhost:1234',
    'caption_system_prompt': (
        "Analyze the provided image thoroughly and write a highly detailed, visually rich, {CAPTION_WORD_COUNT}-word caption. "
        "Begin with a concise and imaginative title for the scene, followed by an in-depth description capturing every important visual element, including objects, colors, lighting, composition, background, atmosphere, and mood. "
        "Describe the image as if crafting a prompt for a top-tier image generator, using evocative language and providing specific details that best convey the unique qualities and style of the visual content. "
        "Use the following format: "
        "  Title:\n"
        "    [brief title for the scene]\n\n"
        "  Description:\n"
        "    [detailed description of the image]\n\n"
        "  Example:\n"
        "    Title:\n"
        "    A beautiful sunset over a calm ocean\n"
        "    Description:\n"
        "    The image captures blah blah blah....\n"
    ),
    'caption_user_prompt': (
        "Carefully study the attached image and provide a comprehensive, vivid, and nuanced {CAPTION_WORD_COUNT}-word caption. "
        "Start with an evocative title that reflects the core scene, then write a richly detailed description capturing every significant aspect: objects, people, colors, lighting, composition, background, atmosphere, and mood. "
        "Highlight unique and subtle visual features, artistic style, and the emotional tone, describing them as if preparing a prompt for an advanced image generation model. "
        "Focus on ensuring the caption thoroughly conveys the image's distinctive qualities and all notable details."
    ),
    'caption_max_words': 200,
    'caption_temperature': 0.7,
    # Last LM Studio LLM used for captions (reloaded after unload for image generation)
    'caption_last_lm_model_key': '',
}

# Global configuration instance
_config: Optional[ImageBrowserConfig] = None

def get_config(profile_dir: Optional[str] = None) -> ImageBrowserConfig:
    """Get global configuration instance
    
    Args:
        profile_dir: Optional custom profile directory path. If provided and different from
                     current config, will reinitialize with the new profile directory.
                     If None, uses default ~/.prowser
    """
    global _config
    if _config is None:
        _config = ImageBrowserConfig(profile_dir=profile_dir)
        _config.ensure_directories()
    elif profile_dir is not None:
        # If a profile_dir is provided and config already exists, check if it's different
        requested_dir = Path(profile_dir).expanduser().resolve()
        current_dir = _config.prowsers_home
        if requested_dir != current_dir:
            # Reinitialize with the new profile directory
            _config = ImageBrowserConfig(profile_dir=profile_dir)
            _config.ensure_directories()
    return _config