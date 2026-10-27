# Local and private remote deployment

Run the browser service and stdio MCP against the same absolute database path. The SQLite file and its sibling `materials/` directory are your data; the source checkout is the software. Back up the database with SQLite's backup API, and copy managed materials separately. Do not copy a live WAL database as a lone file.

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
