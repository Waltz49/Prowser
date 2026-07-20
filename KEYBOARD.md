# Keyboard Shortcuts

This document lists keyboard shortcuts available in Prowser. On macOS, **Cmd** refers to the Command key (⌘). In Qt source code, `Ctrl+` in `QKeySequence` strings maps to ⌘ on macOS.

Physical **Control** (⌃) appears in shortcuts as `Meta+` in Qt (for example ⌃1–9 for favorites, ⌃W to fit image width).

Press **F1** or **/** in the app for context-sensitive help. Menu items also show their shortcuts.

## Table of Contents

- [Thumbnail View](#thumbnail-view)
- [List View](#list-view)
- [Browse View (Fullscreen)](#browse-view-fullscreen)
- [Slideshow Mode](#slideshow-mode)
- [Slideshow2 Mode (Panning Image)](#slideshow2-mode-panning-image)
- [Slideshow3 Mode (Floating Frames)](#slideshow3-mode-floating-frames)
- [Image Menu (AI Generation)](#image-menu-ai-generation)
- [Global Menu Shortcuts](#global-menu-shortcuts)
- [Notes](#notes)

## Thumbnail View

### Navigation
| Key | Action |
|-----|--------|
| ← → ↑ ↓ | Navigate thumbnails |
| H | Go to first image |
| E | Go to last image |
| Page Up/Down | Page up/down through thumbnails |
| Shift+← → ↑ ↓ | Range selection |
| Cmd+← → ↑ ↓ | Add to multi-selection |
| Shift+H | Select to first image |
| Shift+E | Select to last image |

### Actions
| Key | Action |
|-----|--------|
| Enter/Space | Open in fullscreen (image viewer) |
| F | Enter image viewer (menu) |
| Esc | Navigate backward in directory history |
| Shift+Esc | Navigate forward in directory history |
| F10 | Clear forward and backward history stacks |
| Click | Select image |
| Cmd+Click | Add to multi-selection |
| Shift+Click | Range selection |

### Sorting
| Key | Action |
|-----|--------|
| R | Toggle random order |
| D | Sort by date (newest first) |
| Shift+D | Sort by date (oldest first) |
| N | Sort by name (A–Z) |
| Shift+N | Sort by name (Z–A) |
| Z | Sort by size (largest first) |
| Shift+Z | Sort by size (smallest first) |
| X / Shift+X | Sort by EXIF date |
| Y / Shift+Y | Sort by EXIF year |
| C | Custom sort |
| Cmd+T | Reverse sort order |
| Cmd+K | Sort by similarity |
| Cmd+F / Cmd+Shift+K | Search images by description |

### Thumbnail Size
| Key | Action |
|-----|--------|
| +/- | Resize thumbnails |
| 0 | Reset thumbnail size to dynamic default |
| A | Toggle preview fit mode (thumbnail); Actual Size in browse |

### File Operations
| Key | Action |
|-----|--------|
| Cmd+C | Copy image path to clipboard |
| ⌃C | Copy image pixels to clipboard |
| Cmd+E | Edit in external editor |
| Cmd+Backspace | Delete current file (move to Trash) |
| Cmd+Delete | Delete selected files |
| Cmd+Z | Undo file deletion |
| Cmd+N | Rename with custom prefix |
| Cmd+M | Convert selected images |
| Cmd+Shift+Z | Resize images |
| Cmd+L | Lock files (when locking enabled) |
| Cmd+Shift+L | Unlock files |

### View Options
| Key | Action |
|-----|--------|
| B | Toggle status bar |
| I | Toggle information sidebar |
| O | Toggle organize sidebar (favorites / move lists) |
| Cmd+I | Toggle filename overlay |
| Cmd+Shift+I | Toggle number overlay |
| T | Toggle file tree |
| P | Toggle preview widget |
| J | Toggle jobs pane (when enabled) |
| F4, ., Cmd+. | Toggle chrome (menu bar, etc.) |
| F12 | Toggle list view |
| Cmd+Return | Collapse file tree |
| Cmd+Shift+Return | Expand file tree |

### Desktop & Maps
| Key | Action |
|-----|--------|
| Cmd+Shift+W | Set as desktop background |
| Cmd+G | Open GPS location in maps |

### Slideshow
| Key | Action |
|-----|--------|
| S | Start slideshow |
| Shift+S | Start slideshow 2 (panning) |
| Shift+Cmd+S | Start slideshow 3 (floating frames) |

### Help & Settings
| Key | Action |
|-----|--------|
| F1 or / or ? | Show help |
| Cmd+, | Open settings dialog |
| Cmd+O | Open directory |
| Cmd+Shift+O | Open file |
| Cmd+R | Refresh directory |
| Cmd+Shift+T | View copy of Trash (if available) |
| F3 | Image history (browse mode) |

### Quick File Move
| Key | Action |
|-----|--------|
| Cmd+0 | Move selected files to last drop location |
| Cmd+1–9 | Move selected files to destination 1–9 |
| Option+Cmd+0 | Copy to last drop location |
| Option+Cmd+1–9 | Copy to destinations 1–9 |

### Favorites
| Key | Action |
|-----|--------|
| ⌃1–9 | Open favorite directory or file |

### Other
| Key | Action |
|-----|--------|
| Cmd+A | Select all images |
| Cmd+Q | Quit application |
| Cmd+Shift+D | Toggle debug mode |
| Cmd+D | Debug cache status |
| Cmd+Shift+C | Cache subdirectories' thumbnails |
| Cmd+Shift+H | Show image in directory |
| Shift+F | Find duplicate images (recursive) |
| Cmd+P | Search by person |
| ⌃⌘P | Quick person search |
| Cmd+= | Cache Faces |
| F5 | Show reference graph for active image |

## List View

Toggle with **F12** from thumbnail view. In list view, **+** / **=** and **-** adjust row height; **0** resets row height to the default. Most thumbnail shortcuts (navigation, sorting, file ops) also apply in list view.

## Browse View (Fullscreen)

### Navigation
| Key | Action |
|-----|--------|
| ← → ↑ ↓ | Previous/next image |
| H / E | First/last image |
| Cmd+← → ↑ ↓ | Pan image when zoomed |

### Image Transformations
| Key | Action |
|-----|--------|
| Shift+← | Rotate counterclockwise |
| Shift+→ | Rotate clockwise |
| Shift+↑ | Flip vertical |
| Shift+↓ | Flip horizontal |
| Shift+R | Reset image transformations |

### Zoom & Pan
| Key | Action |
|-----|--------|
| +/- or = | Zoom in/out |
| A | Actual size (1:1 pixels) |
| ⌃W | Fit image to canvas width |
| Mouse wheel | Zoom in/out |

### Actions
| Key | Action |
|-----|--------|
| Space | Next image / return to thumbnails (configurable) |
| Shift+Space | Toggle space bar behavior |
| Enter/Return/Esc/Q/F | Return to thumbnails |
| Click | Exit fullscreen |
| F10 | Clear history stacks |
| Esc / Shift+Esc | Directory history back/forward |
| ⌃⌘F | macOS Space vs windowed display |

### File Operations
| Key | Action |
|-----|--------|
| Cmd+C | Copy image path |
| ⌃C | Copy image pixels |
| Cmd+E | Edit in external editor |
| Cmd+Backspace | Delete current file |
| Cmd+Z | Undo deletion |
| Cmd+L | Last image (swap history) |

### View Options
| Key | Action |
|-----|--------|
| I | Toggle information sidebar |
| O | Toggle organize sidebar |
| B | Toggle status bar |
| Cmd+I | Toggle number overlay |
| F3 | Image history |
| F5 | Show reference graph for active image |
| F4, ., Cmd+. | Toggle chrome |
| Cmd+Return / Cmd+Shift+Return | Collapse/expand file tree |

### Desktop & Maps
| Key | Action |
|-----|--------|
| Cmd+Shift+W | Set as desktop background (letterboxed) |
| Cmd+G | Open GPS location in maps |

### Sorting & Search
| Key | Action |
|-----|--------|
| R, D, N, Z, C, Cmd+T | Same as thumbnail view |
| Cmd+K | Sort by similarity |
| Cmd+F / Cmd+Shift+K | Search by description |

### Slideshow
| Key | Action |
|-----|--------|
| S | Start slideshow |
| Shift+S | Start slideshow 2 |
| Shift+Cmd+S | Start slideshow 3 |

## Slideshow Mode

### Navigation
| Key | Action |
|-----|--------|
| N | Next slide immediately |
| ← → ↑ ↓ | Set slide direction (or advance if already set) |
| Click | Advance to next slide |

### Speed Controls
| Key | Action |
|-----|--------|
| 1 / 2 | Slow down / speed up slideshow |
| 0 / 9 | Slow / fast speed presets |

### Transition Controls
| Key | Action |
|-----|--------|
| 3 / 4 | Slow down / speed up transitions |
| 5 / 6 | Decrease / increase max rotation |
| 7 / 8 | Decrease / increase overlap |

### Direction & Effects
| Key | Action |
|-----|--------|
| ← → ↑ ↓ | Set slide direction |
| Shift+R | Random transitions |
| C | No transitions |

### Actions
| Key | Action |
|-----|--------|
| Space/Enter/F | Pause and enter browse mode |
| Shift+Space | Toggle space bar behavior |
| Esc / S | Exit slideshow |

## Slideshow2 Mode (Panning Image)

### Navigation
| Key | Action |
|-----|--------|
| Shift+← → ↑ ↓ | Previous/next image |

### Speed Controls
| Key | Action |
|-----|--------|
| 1 / Shift+1 | Slow down (normal / large step) |
| 2 / Shift+2 | Speed up (normal / large step) |

### Zoom Controls
| Key | Action |
|-----|--------|
| +/- or = | Zoom in |
| - or _ | Zoom out |
| Q | Toggle high-quality scaling |
| ⌃W | Fit image to canvas width |

### Actions
| Key | Action |
|-----|--------|
| Space/Enter/F | Enter browse mode |
| Esc | Exit slideshow2 |

## Slideshow3 Mode (Floating Frames)

Start with **Shift+Cmd+S** (Tools → Slideshows → Floating Frames).

| Key | Action |
|-----|--------|
| Esc / Space / Return | Exit to thumbnails |
| 1 / 2 | Slower / faster movement |
| 3 / 4 | Fewer / more images on screen |
| 5 / 6 | Smaller / larger average image size |
| 9 / 0 | Presets |
| F1, /, ? | Show help |
| Cmd+Return | Collapse file tree |

## Image Menu (AI Generation)

| Key | Action |
|-----|--------|
| Option+/ (⌥/) | Open last-used image function dialog |
| Cmd+J | Job queue |

Infill paint canvas (when open): **[** / **]** brush size; **Cmd+Z** / **Cmd+Shift+Z** undo/redo strokes.

## Global Menu Shortcuts

These work from most views via the menu bar:

- **Cmd+Shift+M** — Quick mass rename (when enabled)
- **Cmd+Shift+E** — Edit EXIF user comment
- **Cmd+Shift+U** — Create screen-size copy
- **Cmd+Option+H** — Open home directory
- **Shift+W** — Wallpaper → resize window

## Notes

- **Cmd** in this document is ⌘ (Command). Qt `Ctrl+` shortcuts in code map to ⌘ on macOS.
- **⌃** is the physical Control key (`Meta+` in Qt).
- Some shortcuts are context-sensitive (view mode, settings, or feature flags).
- **Cmd+L** means lock files in thumbnail view and last-image swap in browse view.
- The in-app help dialog (F1) is built from runtime bindings and may differ slightly from this file.
