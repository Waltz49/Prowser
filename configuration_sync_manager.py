#!/usr/bin/env python3
"""
Configuration Sync Manager
Handles synchronization between FileDataModel and UI state.

DEPRECATED: With MVC refactor, main_window uses property accessors that delegate
to FileDataModel. _sync_to_file_data_model is effectively a no-op (model is source of truth).
Kept for backward compatibility with _set_*_with_sync callers.
"""

import time
from typing import List, Optional
from PySide6.QtCore import QTimer


class ConfigurationSyncManager:
    """Manages configuration and data model synchronization"""
    
    def __init__(self, main_window):
        """
        Initialize the configuration sync manager
        
        Args:
            main_window: Reference to the main ImageBrowserWindow instance
        """
        self.main_window = main_window
    
    def _sync_to_file_data_model(self):
        """No-op: main_window properties delegate to FileDataModel (single source of truth)."""
        pass
    
    def _set_displayed_images_with_sync(self, images: List[str], sync: bool = True):
        """Delegate to window_sync (FileDataModel is source of truth)."""
        from window_sync import set_displayed_images_for_window

        set_displayed_images_for_window(self.main_window, images, sync)

    def _set_current_image_path_with_sync(self, path: Optional[str], sync: bool = True):
        """Delegate to window_sync (FileDataModel is source of truth)."""
        from window_sync import set_current_image_path_for_window

        set_current_image_path_for_window(self.main_window, path, sync)

    def _set_current_directory_with_sync(self, directory: Optional[str], sync: bool = True):
        """Delegate to window_sync (FileDataModel is source of truth)."""
        from window_sync import set_current_directory_for_window

        set_current_directory_for_window(self.main_window, directory, sync)
    
    def _on_displayed_images_changed(self, images: List[str]):
        """Handle displayed_images change from FileDataModel - sync tree view"""
        try:
            # Sync tree view when displayed images change
            if hasattr(self.main_window, 'file_tree_handler') and self.main_window.file_tree_handler:
                # Tree view will be updated when directory changes
                pass
        except Exception:
            pass
    
    def _on_current_image_changed(self, image_path: str):
        """Handle current_image_path change from FileDataModel - tree sync via FileTreeHandler subscription to CURRENT_IMAGE_CHANGED"""
        pass
    
    def _on_directory_changed(self, directory: str):
        """Handle directory change from FileDataModel - tree sync via FileTreeHandler subscription to DIRECTORY_CHANGED"""
        pass
    
    def on_settings_changed(self, new_settings):
        """Handle settings changes and update UI accordingly"""
        # Delegate to main window method
        self.main_window.on_settings_changed(new_settings)
    
    def refresh_from_configuration(self, configuration: dict, from_api: bool = False):
        """Unified method to refresh the browser from a JSON configuration"""
        self.main_window.refresh_from_configuration(configuration, from_api=from_api)

    def poll_message_queue(self):
        """Drain message queue and process each message. Called by QTimer on main thread."""
        mw = self.main_window
        for msg in mw.message_handler.drain_messages():
            self._handle_configuration(msg)
            mw.message_handler.invoke_handlers(msg)

    def _handle_configuration(self, configuration: dict):
        """Handle JSON configuration messages received from the named pipe"""
        mw = self.main_window
        if getattr(mw, '_processing_message', False):
            return
        try:
            mw._processing_message = True
            message_type = configuration.get('type')
            if message_type == 'ping':
                return
            elif message_type == 'quit':
                if getattr(mw, 'idle_detector', None):
                    mw.idle_detector.reset()
                    time.sleep(0.3)
                mw._api_quit_in_progress = True
                try:
                    from imagegen_plugins.image_gen_controller import (
                        get_imagegen_controller,
                    )
                    get_imagegen_controller(mw).prepare_for_shutdown()
                except ImportError:
                    pass
                mw.close()
                return
            if getattr(mw, 'idle_detector', None):
                mw.idle_detector.reset()
            is_load_request = (
                configuration.get('files') or configuration.get('directory') or
                message_type in ('load_directory', 'load_files', 'load_file_with_thumbnails', 'load_file_with_window')
            )
            already_deferred = configuration.pop('_api_load_deferred', False)
            if (is_load_request and not already_deferred and
                getattr(mw, 'thumbnail_worker', None) and mw.thumbnail_worker.isRunning()):
                mw.thumbnail_worker.cancel()
                mw.cleanup_worker_thread('thumbnail_worker', delete_after=False)
                cfg = dict(configuration)
                cfg['_api_load_deferred'] = True
                QTimer.singleShot(50, lambda c=cfg: self._handle_configuration(c))
                return
            converted_config = {}
            if message_type == 'load_directory':
                converted_config['directory'] = configuration.get('directory')
                if 'limit' in configuration:
                    converted_config['limit'] = configuration.get('limit')
                if 'filter_pattern' in configuration:
                    converted_config['filter'] = configuration.get('filter_pattern')
            elif message_type == 'load_files':
                file_paths = configuration.get('file_paths', [])
                converted_config['files'] = file_paths
                if 'filter_pattern' in configuration:
                    converted_config['filter'] = configuration.get('filter_pattern')
                if 'fullscreen' in configuration:
                    converted_config['fullscreen'] = configuration.get('fullscreen')
            elif message_type == 'load_file_with_thumbnails':
                target_file = configuration.get('target_file')
                if target_file:
                    converted_config['files'] = [target_file]
                if 'limit' in configuration:
                    converted_config['limit'] = configuration.get('limit')
                if 'filter_pattern' in configuration:
                    converted_config['filter'] = configuration.get('filter_pattern')
                if 'fullscreen' in configuration:
                    converted_config['fullscreen'] = configuration.get('fullscreen')
            elif message_type == 'load_file_with_window':
                target_file = configuration.get('target_file')
                if target_file:
                    converted_config['files'] = [target_file]
                if 'window_size' in configuration:
                    converted_config['limit'] = configuration.get('window_size')
                if 'filter_pattern' in configuration:
                    converted_config['filter'] = configuration.get('filter_pattern')
            else:
                converted_config = configuration
            files_list = converted_config.get('files', [])
            if files_list and len(files_list) > 0 and not getattr(mw, 'restoring_from_history', False):
                mw.directory_stack_history_handler.save_current_state('image_browser_window._handle_configuration')
            mw.refresh_from_configuration(converted_config, from_api=True)
        except Exception:
            pass
        finally:
            mw._processing_message = False
