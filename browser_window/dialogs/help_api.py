#!/usr/bin/env python3
"""
API Documentation Dialog
Displays markdown-formatted text explaining the Prowser API
"""

from markdown_dialog import MarkdownDialog


class APIDocumentationDialog(MarkdownDialog):
    """Dialog showing markdown-formatted text explaining the Prowser API"""

    def __init__(self, parent=None):
        markdown_content = self._get_markdown_content()
        super().__init__("Prowser API Documentation", markdown_content, parent)

    def _get_markdown_content(self):
        """Get the markdown content for this dialog"""
        return """
# Prowser API

> **Note:** Prowser has an API that allows other programs to control open files or directories via a named pipe.
> 
> **This is really only useful when running the browser from source**
> 
> When opening the packaged app, you can use command line arguments instead:
> 
>     open -a Prowser --args "/path/to/image.jpg" "/path/to/image2.jpg"
---


Prowser uses a named pipe to receive messages for opening images or directories. The pipe is located at `/tmp/image_browser_pipe_<username>`, where `<username>` is your system username (e.g., `/tmp/image_browser_pipe_john`). In shell scripts, you can use `$USER` to get your username.

## Sending Messages

Messages are sent as JSON objects, one per line, terminated with a newline. Example:

```sh
    echo '{"files": ["/some/path/nuts.jpg","/some/other/path/bonkers.jpg"]}' > /tmp/image_browser_pipe_$USER
```

The filter parameter causes user settings to be changed within Prowser, so be aware that using the API with filter might change the expected behavior when Prowser is restarted by any means.

## Message Format

The API uses a simplified format analogous to command line arguments:

---
### Load Files
```json
        {
          "files": ["/path/to/image1.jpg", "/path/to/image2.jpg"],
          "filter": "*.jpg"
        }
```

- **files** (required): Array (list) of file paths to load. Must be a non-empty list.
- **filter** (optional): File pattern filter (e.g., "*.jpg", "*.png"). Note: uses `filter` not `filter_pattern`.
---
### Load Directory
```json
        {
          "directory": "/path/to/directory",
          "filter": "*.jpg"
        }
```
- **directory** (required): Path to the directory to load. Must be a non-empty string.
- **filter** (optional): File pattern filter. Note: uses `filter` not `filter_pattern`.

**Important:**

- A message must have either `files` OR `directory`, but not both.
- If both are present, `files` will take precedence.
- The `files` field must be a list (array) with at least one file path.
- The `directory` field must be a non-empty string.

---
### Ping

```json
        {
          "type": "ping",
          "timestamp": 1234567890.123
        }
```

- Checks if Prowser is listening (no response sent)
- `timestamp` (optional): Timestamp for the ping
---
### Quit

```json
        {
          "type": "quit",
          "timestamp": 1234567890.123
        }
```

- Closes Prowser
- `timestamp` (optional): Timestamp for the quit request
---
## Examples

**Load a single file:**

```sh
    echo '{"files": ["/path/to/image.jpg"]}' > /tmp/image_browser_pipe_$USER
```

**Load multiple files:**

```sh
    echo '{"files": ["/path/to/img1.jpg", "/path/to/img2.png"]}' > /tmp/image_browser_pipe_$USER
```

**Load a directory with filter:**

```sh
    echo '{"directory": "/path/to/images", "filter": "*.jpg"}' > /tmp/image_browser_pipe_$USER
```

**Example verifying that the pipe exists before sending a message:**

```sh
    if [ -p "/tmp/image_browser_pipe_$USER" ]; then
        echo '{"files": ["/path/to/image.jpg"]}' > /tmp/image_browser_pipe_$USER
    else
        echo "Error: Prowser pipe not found. Please check that Prowser is running."
    fi
```
"""


def main():
    """Test function to run the dialog independently"""
    import sys
    from PySide6.QtWidgets import QApplication

    # Create QApplication instance
    app = QApplication(sys.argv)

    # Create and show the dialog
    dialog = APIDocumentationDialog()
    dialog.show()

    # Run the application event loop
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
