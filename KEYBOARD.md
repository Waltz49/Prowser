# Keyboard Shortcuts

This document lists all keyboard shortcuts available in Prowser. Note that on macOS, `Cmd` refers to the Command key (⌘), which is mapped to `Ctrl` in Qt.

## Table of Contents

- [Thumbnail View](#thumbnail-view)
    - [Navigation](#navigation)
    - [Actions](#actions)
    - [Sorting](#sorting)
    - [Thumbnail Size](#thumbnail-size)
    - [File Operations](#file-operations)
    - [View Options](#view-options)
    - [Desktop & Maps](#desktop--maps)
    - [Slideshow](#slideshow)
    - [Help & Settings](#help--settings)
    - [Debug & Maintenance](#debug--maintenance)
    - [Quick File Move](#quick-file-move)
    - [Other](#other)
- [Browse View (Fullscreen)](#browse-view-fullscreen)
    - [Navigation](#navigation-1)
    - [Image Transformations](#image-transformations)
    - [Zoom & Pan](#zoom--pan)
    - [Actions](#actions-1)
    - [File Operations](#file-operations-1)
    - [View Options](#view-options-1)
    - [Desktop & Maps](#desktop--maps-1)
    - [Sorting](#sorting-1)
    - [Slideshow](#slideshow-1)
    - [Help & Settings](#help--settings-1)
    - [Debug & Maintenance](#debug--maintenance-1)
- [Slideshow Mode](#slideshow-mode)
    - [Navigation](#navigation-2)
    - [Speed Controls](#speed-controls)
    - [Transition Controls](#transition-controls)
    - [Direction & Effects](#direction--effects)
    - [Actions](#actions-2)
    - [Help & Settings](#help--settings-2)
- [Slideshow2 Mode (Panning Image)](#slideshow2-mode-panning-image)
    - [Navigation](#navigation-3)
    - [Speed Controls](#speed-controls-1)
    - [Zoom Controls](#zoom-controls)
    - [Actions](#actions-3)
    - [Help & Settings](#help--settings-3)


## Thumbnail View

### Navigation
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| ← → ↑ ↓                | Navigate thumbnails                      |
| H                      | Go to first image                        |
| E                      | Go to last image                         |
| Home/End               | Go to first/last image                   |
| Page Up/Down           | Page up/down through thumbnails          |
| Shift+← → ↑ ↓          | Range selection                          |
| Cmd+← → ↑ ↓            | Add to multi-selection                   |
| Cmd+Shift+← →          | Shift window left/right (when limit is set) |
| Shift+H                | Select to first image                     |
| Shift+E                | Select to last image                      |

### Actions
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| Enter/Space            | Open in fullscreen                       |
| F                      | Open in fullscreen (via menu)            |
| Esc                    | Navigate backward in directory history   |
| Shift+Esc              | Navigate forward in directory history    |
| F2                     | Clear forward and backward history stacks |
| Click                  | Select image                              |
| Cmd+Click              | Add to multi-selection                   |
| Shift+Click            | Range selection                          |

### Sorting
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| R                      | Toggle random order                      |
| D                      | Sort by date (oldest first)              |
| Shift+D                | Sort by date (newest first)              |
| N                      | Sort by name (A-Z)                       |
| Shift+N                | Sort by name (Z-A)                       |
| Z                      | Sort by size (largest first)             |
| Shift+Z                | Sort by size (smallest first)            |
| C                      | Custom sort                              |
| Cmd+T                  | Reverse sort order                       |
| Cmd+K                  | Sort by similarity                       |
| Cmd+F                  | Search images by description             |
| Cmd+Shift+K            | Search images by description (alternate) |

### Thumbnail Size
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| +/-                    | Resize thumbnails                        |
| 0                      | Set minimum thumbnail size               |
| A                      | Toggle preview fit mode                  |

### File Operations
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| Cmd+C                  | Copy image path to clipboard             |
| Cmd+E                  | Edit in external editor (Pixelmator Pro) |
| Cmd+Backspace          | Delete current file (move to Trash)      |
| Shift+Cmd+Backspace    | Delete current file without confirmation |
| Cmd+Delete             | Delete selected files                    |
| Cmd+Z                  | Undo file deletion                       |
| Cmd+N                  | Rename with custom prefix                |
| Cmd+M                  | Convert selected images                   |
| Cmd+S                  | Save custom sort order                   |

### View Options
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| B                      | Toggle status bar                        |
| I                      | Toggle Information sidebar                  |
| Cmd+I                  | Toggle filename overlay                  |
| Cmd+Shift+I            | Toggle number overlay                    |
| T                      | Toggle file tree                         |
| P                      | Toggle preview widget                     |
| Cmd+Return             | Collapse file tree                       |
| Cmd+Enter              | Collapse file tree (alternate)           |
| Cmd+Shift+Return       | Expand file tree                         |

### Desktop & Maps
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| Cmd+Shift+W            | Set as desktop background                |
| Cmd+G                  | Open GPS location in maps                |

### Slideshow
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| S                      | Start slideshow                          |
| Shift+S                | Start slideshow 2                        |

### Help & Settings
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| F1 or / or ?           | Show help                                |
| Cmd+,                  | Open settings dialog                     |
| Cmd+O                  | Open directory                           |
| Cmd+Shift+O            | Open directory (new window)              |
| Cmd+R                  | Refresh directory                        |
| Cmd+Shift+T            | View copy of Trash (if available)       |

### Debug & Maintenance
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| Cmd+Shift+D            | Toggle debug mode                        |
| Cmd+D                  | Debug cache status                       |
| Cmd+Shift+C            | Prepopulate thumb cache                  |
| Cmd+X                  | Exclude thumbs from view                 |
| Cmd+Shift+N            | Show rename status in tree               |
| Cmd+Shift+H            | Show image in directory                  |

### Quick File Move
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| Cmd+0                  | Move selected files to last drop location |
| Cmd+1-9                | Move selected files to destination 1-9    |

### Other
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| Cmd+A                  | Select all images                        |
| Cmd+Q                  | Quit application                         |

## Browse View (Fullscreen)

### Navigation
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| ← →                    | Previous/Next image                      |
| ↑ ↓                    | Previous/Next image                      |
| Shift+← →              | Pan image when zoomed                   |
| Shift+↑ ↓              | Pan image when zoomed                    |
| H/E                    | First/Last image                         |
| Home/End               | First/Last image                         |
| Page Up/Down           | Previous/Next image                      |
| Cmd+← → ↑ ↓            | Pan image when zoomed                    |

### Image Transformations
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| Shift+←                | Rotate counterclockwise                  |
| Shift+→                | Rotate clockwise                         |
| Shift+↑                | Flip vertical                            |
| Shift+↓                | Flip horizontal                          |
| Shift+R                | Reset image transformations              |

### Zoom & Pan
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| +/- or =               | Zoom in/out                              |
| I                      | Zoom in                                  |
| O                      | Zoom out                                 |
| 0                      | Reset zoom                               |
| A                      | Toggle actual size (1:1 pixels)          |
| Mouse wheel            | Zoom in/out                              |

### Actions
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| Space                  | Next image / Return to thumbnails        |
| Shift+Space            | Toggle space bar behavior                |
| Enter/Return           | Return to thumbnails                     |
| Esc                    | Return to thumbnails                     |
| Q                      | Return to thumbnails                     |
| F                      | Return to thumbnails                     |
| Click                  | Exit fullscreen                          |
| Cmd+Shift+F            | Native fullscreen (hides dock/menu bar) |
| F12                    | Toggle maximized                         |
| F2                     | Clear forward and backward history stacks |

### File Operations
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| Cmd+C                  | Copy image path to clipboard             |
| Cmd+E                  | Edit in external editor (Pixelmator Pro) |
| Cmd+Backspace          | Delete current file (move to Trash)      |
| Shift+Cmd+Backspace    | Delete current file without confirmation |
| Cmd+Z                  | Undo file deletion                       |

### View Options
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| I                      | Toggle detailed image information        |
| B                      | Toggle status bar                        |
| Cmd+I                  | Toggle filename overlay                  |
| Cmd+Return             | Collapse file tree                       |
| Cmd+Enter              | Collapse file tree (alternate)           |
| Cmd+Shift+Return       | Expand file tree                         |

### Desktop & Maps
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| Cmd+Shift+W            | Set as desktop background (letterboxed)  |
| Cmd+G                  | Open GPS location in maps                |

### Sorting
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| R                      | Toggle random order                      |
| D                      | Sort by date                             |
| N                      | Sort by name                             |
| Cmd+K                  | Sort by similarity (CNN/CLIP)            |
| Cmd+Shift+K            | Reset similarity processing               |

### Slideshow
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| S                      | Start slideshow                          |
| Shift+S                | Start slideshow 2                        |

### Help & Settings
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| F1 or / or ?           | Show help                                |
| Cmd+,                  | Open settings dialog                     |
| Cmd+Return             | Collapse file tree                       |

### Debug & Maintenance
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| Cmd+Shift+D            | Toggle debug mode                        |
| Cmd+Shift+C            | Clear all cache                          |

## Slideshow Mode

### Navigation
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| N                      | Next slide immediately                   |
| ← → ↑ ↓                | Set slide direction (or advance if already set) |
| Click                  | Advance to next slide                    |

### Speed Controls
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| 1                      | Slow down slideshow                      |
| 2                      | Speed up slideshow                       |
| 0                      | Slow speed preset                        |
| 9                      | Fast speed preset                        |

### Transition Controls
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| 3                      | Slow down transitions                    |
| 4                      | Speed up transitions                     |
| 5                      | Decrease max rotation                    |
| 6                      | Increase max rotation                    |
| 7                      | Decrease overlap                         |
| 8                      | Increase overlap                         |

### Direction & Effects
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| ← → ↑ ↓                | Set slide direction                      |
| Shift+R                | Random transitions                       |
| C                      | No transitions                           |
| R                      | Toggle random order                      |

### Actions
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| Space/Enter/F          | Pause and enter browse mode             |
| Shift+Space            | Toggle space bar behavior                |
| Esc                    | Exit slideshow                           |
| S                      | Exit slideshow                           |

### Help & Settings
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| F1 or / or ?           | Show help                                |
| Cmd+Return             | Collapse file tree                       |

## Slideshow2 Mode (Panning Image)

### Navigation
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| Shift+←                | Previous image                           |
| Shift+→                | Next image                               |
| Shift+↑                | Previous image                           |
| Shift+↓                | Next image                               |

### Speed Controls
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| 1                      | Slow down slideshow2                     |
| Shift+1                | Slow down slideshow2 (large step)        |
| 2                      | Speed up slideshow2                      |
| Shift+2                | Speed up slideshow2 (large step)         |

### Zoom Controls
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| +/- or =               | Zoom in                                  |
| - or _                 | Zoom out                                 |
| Q                      | Toggle high-quality scaling              |

### Actions
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| Space/Enter/F          | Enter browse mode                        |
| Esc                    | Exit slideshow2                          |

### Help & Settings
| Key                    | Action                                   |
|------------------------|------------------------------------------|
| F1 or / or ?           | Show help                                |
| Cmd+Return             | Collapse file tree                       |

## Notes

- **Cmd** refers to the Command key (⌘) on macOS, which is mapped to `Ctrl` in Qt
- Some shortcuts may vary depending on your keyboard layout
- Shortcuts can be viewed in the Help dialog (F1 or /)
- Menu items show their keyboard shortcuts in the menu bar
- Some shortcuts are context-sensitive and only work in specific view modes
