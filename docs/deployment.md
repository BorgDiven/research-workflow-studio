# Local and private remote deployment

Run the browser service and stdio MCP against the same absolute database path. The SQLite file and managed originals (by default its sibling `materials/` directory) are your data; the source checkout is the software. Back up the database with SQLite's backup API, and copy managed materials separately. Do not copy a live WAL database as a lone file.

## Tailscale Serve

Use an existing private tailnet. Choose an unused HTTPS port and your actual Tailscale login:

```sh
python3 launch.py serve --db /absolute/path/studio.sqlite3 --port 8831 \
  --public-origin https://your-device.your-tailnet.ts.net:8443 \
  --tailscale-user your-login@example.com
tailscale serve --bg --https=8443 http://127.0.0.1:8831
```

The backend remains loopback-only. Both proxy arguments are required together. Requests must match the configured host, origin and identity supplied by the trusted local proxy. Browser writes retain session and CSRF checks. Existing Serve routes should be inspected before adding a port. Do not enable public Funnel for this single-user deployment.

Set MCP's `--web-url` to the same private HTTPS origin so review links work on another device. MCP remains stdio; it does not need a public port. Both devices must have Tailscale connectivity and the server must remain awake and online.

## Scope

This is a single-user service, not a security boundary against programs running as the same OS user. A model with separate shell/browser permissions must still follow user authorization. Studio's MCP itself does not offer those capabilities.

Use your operating system's service manager if persistent startup is needed. No installer in this repository changes network routes or starts background services automatically.

## Independent storage locations

`serve --materials-root /absolute/originals --preview-cache-root /absolute/local-cache --preview-cache-mb 512` changes physical storage only. Existing `/materials/...` links and report references remain valid. No external drive is required. Install the optional `previews` extra for image conversion and `pdf-readings` for reading PDFs; the record service and MCP remain usable without them.

Migration is explicit: copy originals, verify the copy, stop import writers, update the server configuration and restart, then verify old links before retiring the old copy. Back up the database separately. Do not point a cache directory at original data or a project folder. No service command automatically migrates or deletes originals. See [storage and reading](storage-and-reading.md).

On macOS, a login background service may lack removable-volume access even when a foreground terminal can read the same files. Verify an original download through the running service before removing a local migration copy. If the OS blocks access, keep local originals and the external backup until the user approves an appropriate system permission; do not silently grant a shared Python runtime Full Disk Access.
