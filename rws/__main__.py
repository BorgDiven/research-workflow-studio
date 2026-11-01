"""Run the isolated web service or MCP process using an explicit database."""

import argparse
import json


def main(argv=None):
    parser = argparse.ArgumentParser(prog="research-workflow-studio")
    commands = parser.add_subparsers(dest="command", required=True)
    server = commands.add_parser("serve", help="Start the local browser workbench")
    server.add_argument("--db", required=True, help="Explicit isolated SQLite database path")
    server.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1", "localhost"))
    server.add_argument("--port", type=int, default=8831)
    server.add_argument("--web-root", default=None, help="Optional packaged frontend directory")
    server.add_argument("--public-origin", help="Explicit HTTPS Tailscale origin served by the loopback proxy")
    server.add_argument("--tailscale-user", help="Tailscale login permitted through that proxy; required with --public-origin")
    mcp = commands.add_parser("mcp", help="Serve MCP over stdin/stdout")
    mcp.add_argument("--db", required=True, help="Same isolated SQLite database as the web service")
    mcp.add_argument("--web-url", default="http://127.0.0.1:8831", help="Loopback or HTTPS Tailscale Studio address used for human-review links")
    operate = commands.add_parser("operate", help="Execute one exact reviewed operation; read-only requests need no separate approval")
    operate.add_argument("--db", required=True, help="Studio database used to review the operation")
    operate.add_argument("--project-id", required=True)
    operate.add_argument("--operation-id", required=True)
    operate.add_argument("--version", type=int, required=True, help="Exact reviewed operation revision")
    cache = commands.add_parser("preview-cache", help="Manage regenerable reading renditions; never remove original materials")
    cache.add_argument("--db", required=True, help="Database path used only to locate default storage directories")
    cache.add_argument("action", choices=("status", "prune", "warm"))
    cache.add_argument("--uri", action="append", default=[], help="Exact /materials/... URI; repeat for selected images/PDFs")
    for storage_parser in (server, cache):
        storage_parser.add_argument("--materials-root", help="Original material directory (default: database sibling materials)")
        storage_parser.add_argument("--preview-cache-root", help="Reading cache directory (default: database sibling cache/previews)")
        storage_parser.add_argument("--preview-cache-mb", type=int, default=512, help="Reading image/PDF cache limit in MiB (default: 512)")
    args = parser.parse_args(argv)
    if args.command in ("serve", "preview-cache") and not 1 <= args.preview_cache_mb <= 65536:
        parser.error("--preview-cache-mb must be between 1 and 65536")
    if args.command == "serve":
        if not 0 <= args.port <= 65535:
            parser.error("port must be between 0 and 65535")
        if (args.public_origin is None) != (args.tailscale_user is None):
            parser.error("--public-origin and --tailscale-user must be supplied together")
        from .server import serve
        serve(args.db, args.host, args.port, args.web_root, args.public_origin, args.tailscale_user,
              args.materials_root, args.preview_cache_root, args.preview_cache_mb)
    elif args.command == "mcp":
        from .mcp import run_stdio
        run_stdio(args.db, web_url=args.web_url)
    elif args.command == "preview-cache":
        if (args.action == "warm") != bool(args.uri):
            parser.error("warm requires at least one --uri; status and prune do not accept --uri")
        if len(args.uri) > 10000:
            parser.error("at most 10000 selected material URIs may be warmed per invocation")
        from .storage import MaterialStorage, PreviewError
        try:
            storage = MaterialStorage(args.db, args.materials_root, args.preview_cache_root, args.preview_cache_mb)
            failures = []
            warmed = 0
            if args.action == "warm":
                for uri in dict.fromkeys(args.uri):
                    try:
                        stream, info = storage.preview(uri)
                        stream.close()
                        warmed += 1
                    except PreviewError as exc:
                        failures.append({"uri": uri, "code": exc.code, "message": exc.message})
            print(json.dumps({"ok": not failures, "warmed": warmed, "failures": failures,
                              **storage.status(prune=args.action == "prune")}, ensure_ascii=False))
            if failures:
                raise SystemExit(1)
        except (PreviewError, OSError, ValueError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            raise SystemExit(1)
    else:
        if args.version < 1:
            parser.error("version must be positive")
        from .core import RwsError, Store
        from .operations import OperationsRunner
        store = Store(args.db)
        try:
            result = OperationsRunner(store).execute({"projectId": args.project_id,
                "type": "operation", "id": args.operation_id, "version": args.version})
            print(json.dumps(result, ensure_ascii=False, allow_nan=False))
            if result.get("result", {}).get("record", {}).get("status") in ("failed", "unknown"):
                raise SystemExit(1)
        except RwsError as exc:
            print(json.dumps({"ok": False, "error": exc.as_dict()}, ensure_ascii=False))
            raise SystemExit(1)
        except (OSError, ValueError) as exc:
            print(json.dumps({"ok": False, "error": {"code": "executor_error", "message": str(exc)}}, ensure_ascii=False))
            raise SystemExit(1)
        finally:
            store.close()


if __name__ == "__main__":
    main()
