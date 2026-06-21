# Prowser API

Prowser uses a named pipe to receive messages for opening images or directories. The pipe is located at `/tmp/image_browser_pipe_<username>`, where `<username>` is your system username (`getpass.getuser()`, typically the same as `$USER` on macOS).

The pipe is **per OS user**, not per Prowser profile — `-p` / `--profile` does not change the pipe path.

> **Note:** The pipe API is mainly useful when running from source. For the packaged app, use command-line arguments instead:
>
>     open -a Prowser --args "/path/to/image.jpg"

## Sending Messages

Messages are sent as JSON objects, one per line, terminated with a newline. Example:

```bash
echo '{"files": ["/some/path/nuts.jpg","/some/other/path/bonkers.jpg"]}' > /tmp/image_browser_pipe_$USER
```

No response is ever sent on the pipe (including for `ping`).

## Message Format

The API uses a simplified format analogous to command line arguments:

### Load Files
```json
{
  "files": ["/path/to/image1.jpg", "/path/to/image2.jpg"],
  "filter": "*.jpg"
}
```
- `files` (required): Array (list) of file paths to load.
- `filter` (optional): File pattern filter (e.g., `"*.jpg"`, `"*.png"`). Uses `filter`, not `filter_pattern`. Applies to the **current session only** — it does not persist to `settings.json`.

### Load Directory
```json
{
  "directory": "/path/to/directory",
  "filter": "*.jpg"
}
```
- `directory` (required): Path to the directory to load.
- `filter` (optional): File pattern filter. Session-only (see above).

**Important:**
- A message must have either `files` OR `directory`, but not both (except when `files` is an empty list — then `directory` is used).
- If both are present and `files` is non-empty, `files` takes precedence.
- The `files` field must be a list (array). An empty list clears the view without loading.
- The `directory` field must be a string.

### Ping
```json
{
  "type": "ping",
  "timestamp": 1234567890.123
}
```
- Checks if Prowser is listening (no response sent)
- `timestamp` (optional): Ignored

### Quit
```json
{
  "type": "quit",
  "timestamp": 1234567890.123
}
```
- Closes Prowser
- `timestamp` (optional): Ignored

## Optional fields

These are accepted by `refresh_from_configuration` but not required for basic loads:

| Field | Purpose |
|-------|---------|
| `fullscreen` | Open in browse (fullscreen) view |
| `prevent_browse_view` | Stay in thumbnail grid |
| `force_specific_files_grid` | Show only the listed files in the grid |
| `skip_filter_pattern` | Ignore the current filter |
| `sort_mode` | Override sort for this load |
| `presentation` | Presentation mode hint |
| `focus_path` | Image to highlight after load |
| `restore_view_mode` | Restore a saved view mode |

## Runtime behavior

- **Files:** Paths are absolutized and deduped. Missing files are retried after a short delay. A single file opens in browse view; multiple files open in the grid with the newest highlighted. API file loads use date sort.
- **Directory:** Full directory scan (there is no `limit` parameter in the pipe API).
- **Logs:** `~/.prowser/logs/image_browser_message_debug.log`, `~/.prowser/logs/messages.log`

## Examples

Load a single file:
```bash
echo '{"files": ["/path/to/image.jpg"]}' > /tmp/image_browser_pipe_$USER
```

Load multiple files:
```bash
echo '{"files": ["/path/to/img1.jpg", "/path/to/img2.png"]}' > /tmp/image_browser_pipe_$USER
```

Load a directory with filter:
```bash
echo '{"directory": "/path/to/images", "filter": "*.jpg"}' > /tmp/image_browser_pipe_$USER
```

Ping (check if Prowser is running):
```bash
echo '{"type": "ping"}' > /tmp/image_browser_pipe_$USER
```
