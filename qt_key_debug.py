#!/usr/bin/env python3
"""
Qt Key Debug Module
Logs Qt key events with their actual Qt names for debugging purposes.
"""

# Standard library imports
import os
from typing import Dict, Any

# Local imports
from config import get_config

# Third-party imports
try:
    from PySide6.QtCore import Qt
except ImportError:
    Qt = None

# Try importing from QtGui if QtCore.Qt is empty
if Qt is not None and not any(attr.startswith('Key_') for attr in dir(Qt)):
    try:
        from PySide6.QtGui import Qt as QtGuiQt
        Qt = QtGuiQt
        # print("[qt_key_debug] Using Qt from PySide6.QtGui")
    except ImportError:
        pass

# print("[qt_key_debug] Qt attributes:")
# for attr in dir(Qt):
#     print(f"  {attr}")

from PySide6.QtGui import QKeyEvent, QKeySequence

_popup_callback = None

def set_popup_callback(cb):
    global _popup_callback
    _popup_callback = cb

class QtKeyDebugger:
    """Debug utility for logging Qt key events with their actual names."""
    
    def __init__(self, log_file: str = None):
        if log_file is None:
            config = get_config()
            log_file = str(config.keyboard_log)
        self.log_file = log_file
        self._key_names = self._build_key_name_mapping()
        self._modifier_names = self._build_modifier_name_mapping()
    
    def _build_key_name_mapping(self) -> Dict[int, str]:
        """Build a mapping of Qt key codes to their string names."""
        key_mapping = {}
        key_count = 0
        # Try to enumerate Qt.Key enum if available
        if hasattr(Qt, 'Key'):
            try:
                for attr_name in dir(Qt.Key):
                    if attr_name.startswith('Key_'):
                        try:
                            key_code = getattr(Qt.Key, attr_name)
                            if isinstance(key_code, int):
                                key_mapping[int(key_code)] = f"Qt.{attr_name}"
                                key_count += 1
                                # if key_count <= 10:
                                #     print(f"  [enum] Mapped: {attr_name} = {key_code}")
                        except Exception as e:
                            # print(f"  [enum] Error with {attr_name}: {e}")
                            continue
                # print(f"Built mapping from Qt.Key enum with {key_count} keys")
                if key_count > 0:
                    return key_mapping
            except Exception as e:
                # print(f"  [enum] Could not enumerate Qt.Key: {e}")
                pass
        # Fallback: search attributes of Qt
        for attr_name in dir(Qt):
            if attr_name.startswith('Key_'):
                try:
                    key_code = getattr(Qt, attr_name)
                    if isinstance(key_code, int):
                        key_mapping[int(key_code)] = f"Qt.{attr_name}"
                        key_count += 1
                        # if key_count <= 10:
                        #     print(f"  [attr] Mapped: {attr_name} = {key_code}")
                except (TypeError, AttributeError) as e:
                    # print(f"  [attr] Error with {attr_name}: {e}")
                    continue
        # print(f"Built mapping from Qt attributes with {key_count} keys")
        return key_mapping
    
    def _build_modifier_name_mapping(self) -> Dict[int, str]:
        """Build a mapping of Qt modifier codes to their string names."""
        modifier_mapping = {}
        
        # Common modifiers
        modifier_mapping[Qt.NoModifier] = "Qt.NoModifier"
        modifier_mapping[Qt.ShiftModifier] = "Qt.ShiftModifier"
        modifier_mapping[Qt.ControlModifier] = "Qt.ControlModifier"
        modifier_mapping[Qt.AltModifier] = "Qt.AltModifier"
        modifier_mapping[Qt.MetaModifier] = "Qt.MetaModifier"
        modifier_mapping[Qt.KeypadModifier] = "Qt.KeypadModifier"
        modifier_mapping[Qt.GroupSwitchModifier] = "Qt.GroupSwitchModifier"
        
        # Combined modifiers
        modifier_mapping[Qt.ShiftModifier | Qt.ControlModifier] = "Qt.ShiftModifier + Qt.ControlModifier"
        modifier_mapping[Qt.ShiftModifier | Qt.AltModifier] = "Qt.ShiftModifier + Qt.AltModifier"
        modifier_mapping[Qt.ShiftModifier | Qt.MetaModifier] = "Qt.ShiftModifier + Qt.MetaModifier"
        modifier_mapping[Qt.ControlModifier | Qt.AltModifier] = "Qt.ControlModifier + Qt.AltModifier"
        modifier_mapping[Qt.ControlModifier | Qt.MetaModifier] = "Qt.ControlModifier + Qt.MetaModifier"
        modifier_mapping[Qt.AltModifier | Qt.MetaModifier] = "Qt.AltModifier + Qt.MetaModifier"
        
        # Triple combinations
        modifier_mapping[Qt.ShiftModifier | Qt.ControlModifier | Qt.AltModifier] = "Qt.ShiftModifier + Qt.ControlModifier + Qt.AltModifier"
        modifier_mapping[Qt.ShiftModifier | Qt.ControlModifier | Qt.MetaModifier] = "Qt.ShiftModifier + Qt.ControlModifier + Qt.MetaModifier"
        modifier_mapping[Qt.ShiftModifier | Qt.AltModifier | Qt.MetaModifier] = "Qt.ShiftModifier + Qt.AltModifier + Qt.MetaModifier"
        modifier_mapping[Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier] = "Qt.ControlModifier + Qt.AltModifier + Qt.MetaModifier"
        
        # All modifiers
        modifier_mapping[Qt.ShiftModifier | Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier] = "Qt.ShiftModifier + Qt.ControlModifier + Qt.AltModifier + Qt.MetaModifier"
        
        return modifier_mapping
    
    def _get_key_name(self, key: int) -> str:
        """Get the Qt name for a key code."""
        # Debug: print lookup
        lookup_key = int(key)
        name = self._key_names.get(lookup_key)
        if name is None:
            # Try to find by value (sometimes enums are not direct ints)
            for k, v in self._key_names.items():
                if int(k) == lookup_key:
                    name = v
                    break
        if name is None:
            # print(f"[qt_key_debug] Could not resolve key: {lookup_key}. Mapping keys: {sorted(self._key_names.keys())[:20]} ... (total {len(self._key_names)})")
            name = f"Unknown_Key_{lookup_key}"
        return name
    
    def _get_modifier_name(self, modifiers: int) -> str:
        """Get the Qt name for modifier flags."""
        if modifiers == Qt.NoModifier:
            return "Qt.NoModifier"
        
        # Check for exact matches first
        if modifiers in self._modifier_names:
            return self._modifier_names[modifiers]
        
        # Build modifier string manually
        modifier_parts = []
        if modifiers & Qt.ShiftModifier:
            modifier_parts.append("Qt.ShiftModifier")
        if modifiers & Qt.ControlModifier:
            modifier_parts.append("Qt.ControlModifier")
        if modifiers & Qt.AltModifier:
            modifier_parts.append("Qt.AltModifier")
        if modifiers & Qt.MetaModifier:
            modifier_parts.append("Qt.MetaModifier")
        if modifiers & Qt.KeypadModifier:
            modifier_parts.append("Qt.KeypadModifier")
        if modifiers & Qt.GroupSwitchModifier:
            modifier_parts.append("Qt.GroupSwitchModifier")
        
        if modifier_parts:
            return " + ".join(modifier_parts)
        else:
            return f"Unknown_Modifier_{modifiers}"
    
    def _get_qkeysequence_string(self, key: int, modifiers: int) -> str:
        """Get a human-readable string using QKeySequence."""
        try:
            # Create a QKeySequence from the key and modifiers
            key_sequence = QKeySequence(key | modifiers)
            return key_sequence.toString()
        except Exception:
            return "QKeySequence conversion failed"
    
    def log_key_event(self, event: QKeyEvent, additional_info: str = "") -> None:
        """Log a key event with its Qt names to the debug file."""
        key = event.key()
        modifiers = event.modifiers()
        key_name = self._get_key_name(key)
        modifier_name = self._get_modifier_name(modifiers)
        qkeysequence_string = self._get_qkeysequence_string(key, modifiers)
        text = ''
        scan_code = None
        virtual_key = None
        try:
            text = event.text()
        except Exception:
            text = ''
        try:
            scan_code = event.nativeScanCode()
        except Exception:
            scan_code = None
        try:
            virtual_key = event.nativeVirtualKey()
        except Exception:
            virtual_key = None

        # Only print extra info if key or modifier is unknown
        if not key_name.startswith('Unknown_Key') and not modifier_name.startswith('Unknown_Modifier'):
            log_message = f"Pressed {key_name} + {modifier_name}"
        else:
            log_message = f"Pressed {key_name} + {modifier_name} (QKeySequence: {qkeysequence_string})"
            extras = []
            if text:
                extras.append(f"text='{text}'")
            if scan_code is not None:
                extras.append(f"scanCode={scan_code}")
            if virtual_key is not None:
                extras.append(f"virtualKey={virtual_key}")
            if extras:
                log_message += " [" + ", ".join(extras) + "]"
        if additional_info:
            log_message += f" - {additional_info}"
        # Show in popup if callback is set
        if _popup_callback:
            _popup_callback(log_message)
            return
        log_message += "\n"
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(log_message)
        except Exception as e:
            import sys
            print(f"Failed to write to {self.log_file}: {e}", file=sys.stderr)
            print(log_message, file=sys.stderr)
    
    def log_key_info(self, key: int, modifiers: int, additional_info: str = "", text: str = '', scan_code: int = None, virtual_key: int = None) -> None:
        """Log key information without requiring a QKeyEvent object. Optionally include text, scan_code, and virtual_key."""
        key_name = self._get_key_name(key)
        modifier_name = self._get_modifier_name(modifiers)
        qkeysequence_string = self._get_qkeysequence_string(key, modifiers)
        
        if not key_name.startswith('Unknown_Key') and not modifier_name.startswith('Unknown_Modifier'):
            log_message = f"Key: {key_name} + {modifier_name}"
        else:
            log_message = f"Key: {key_name} + {modifier_name} (QKeySequence: {qkeysequence_string})"
            extras = []
            if text:
                extras.append(f"text='{text}'")
            if scan_code is not None:
                extras.append(f"scanCode={scan_code}")
            if virtual_key is not None:
                extras.append(f"virtualKey={virtual_key}")
            if extras:
                log_message += " [" + ", ".join(extras) + "]"
        if additional_info:
            log_message += f" - {additional_info}"
        log_message += "\n"
        
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(log_message)
        except Exception as e:
            import sys
            print(f"Failed to write to {self.log_file}: {e}", file=sys.stderr)
            print(log_message, file=sys.stderr)
    
    def clear_log(self) -> None:
        """Clear the debug log file."""
        try:
            if os.path.exists(self.log_file):
                os.unlink(self.log_file)
        except Exception as e:
            import sys
            print(f"Failed to clear log file {self.log_file}: {e}", file=sys.stderr)


# Global instance for easy access
_global_debugger = None

def get_key_debugger() -> QtKeyDebugger:
    """Get the global key debugger instance."""
    global _global_debugger
    if _global_debugger is None:
        _global_debugger = QtKeyDebugger()
    return _global_debugger

def log_key_event(event: QKeyEvent, additional_info: str = "") -> None:
    """Convenience function to log a key event."""
    get_key_debugger().log_key_event(event, additional_info)

def log_key_info(key: int, modifiers: int, additional_info: str = "") -> None:
    """Convenience function to log key information."""
    get_key_debugger().log_key_info(key, modifiers, additional_info)



# Example usage:
if __name__ == "__main__":
    # Test the debugger
    debugger = QtKeyDebugger()
    debugger.clear_log()
    
    print("Debug: Key mappings:")
    for key_name in ['Key_A', 'Key_Backslash', 'Key_F', 'Key_Escape', 'Key_Return', 'Key_Space']:
        if hasattr(Qt, key_name):
            key_code = getattr(Qt, key_name)
            print(f"  {key_name} = {key_code}")
    
    # Test some common keys
    test_keys = [
        (Qt.Key_A, Qt.NoModifier, "Letter A"),
        (Qt.Key_A, Qt.ControlModifier, "Ctrl+A"),
        (Qt.Key_Backslash, Qt.ControlModifier, "Ctrl+\\"),
        (Qt.Key_F, Qt.ControlModifier, "Ctrl+F"),
        (Qt.Key_Escape, Qt.NoModifier, "Escape key"),
        (Qt.Key_Return, Qt.NoModifier, "Return key"),
        (Qt.Key_Space, Qt.NoModifier, "Space key"),
    ]
    
    for key, modifiers, description in test_keys:
        mapped_name = debugger._get_key_name(key)
        print(f"Test: key={key} mapped_name={mapped_name}")
        debugger.log_key_info(key, modifiers, description)
    
    print(f"Test key events logged to {debugger.log_file}")

    # At module init, print all Qt key codes and their names for reference
    print("All Qt key codes and their names:")
    qt_keys = []
    for attr_name in dir(Qt):
        if attr_name.startswith('Key_'):
            try:
                key_code = getattr(Qt, attr_name)
                if isinstance(key_code, int):
                    qt_keys.append((key_code, attr_name))
            except Exception:
                continue
    for code, name in sorted(qt_keys):
        print(f"  {name}: {code}") 