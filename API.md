# Prowser API

Prowser uses a named pipe to receive messages for opening images or directories. The pipe is located at `/tmp/image_browser_pipe_<userid>`.

## Sending Messages

Messages are sent as JSON objects, one per line, terminated with a newline. Example:

```bash
echo '{"files": ["/some/path/nuts.jpg","/some/other/path/bonkers.jpg"]}' > /tmp/image_browser_pipe_$USER
```

## Message Format

The API uses a simplified format analogous to command line arguments:

### Load Files
```json
{
  "files": ["/path/to/image1.jpg", "/path/to/image2.jpg"],
  "limit": 300,
  "filter": "*.jpg"
}
```
- `files` (required): Array (list) of file paths to load. Must be a non-empty list.
- `limit` (optional): Maximum number of images to display
- `filter` (optional): File pattern filter (e.g., "*.jpg", "*.png"). Note: uses `filter` not `filter_pattern`.

### Load Directory
```json
{
  "directory": "/path/to/directory",
  "limit": 300,
  "filter": "*.jpg"
}
```
- `directory` (required): Path to the directory to load. Must be a non-empty string.
- `limit` (optional): Maximum number of images to display
- `filter` (optional): File pattern filter. Note: uses `filter` not `filter_pattern`.

**Important:** 
- A message must have either `files` OR `directory`, but not both.
- If both are present, `files` will take precedence.
- The `files` field must be a list (array) with at least one file path.
- The `directory` field must be a non-empty string.

### Ping
```json
{
  "type": "ping",
  "timestamp": 1234567890.123
}
```
- Checks if Prowser is listening (no response sent)
- `timestamp` (optional): Timestamp for the ping

### Quit
```json
{
  "type": "quit",
  "timestamp": 1234567890.123
}
```
- Closes Prowser
- `timestamp` (optional): Timestamp for the quit request

## Examples

Load a single file:
```bash
echo '{"files": ["/path/to/image.jpg"]}' > /tmp/image_browser_pipe_$USER
```

Load multiple files:
```bash
echo '{"files": ["/path/to/img1.jpg", "/path/to/img2.png"]}' > /tmp/image_browser_pipe_$USER
```

Load a directory with limit:
```bash
echo '{"directory": "/path/to/images", "limit": 100}' > /tmp/image_browser_pipe_$USER
```

Load a directory with filter:
```bash
echo '{"directory": "/path/to/images", "filter": "*.jpg"}' > /tmp/image_browser_pipe_$USER
```
