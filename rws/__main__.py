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
    args = parser.parse_args(argv)
    if args.command == "serve":
        if not 0 <= args.port <= 65535:
            parser.error("port must be between 0 and 65535")
        if (args.public_origin is None) != (args.tailscale_user is None):
            parser.error("--public-origin and --tailscale-user must be supplied together")
        from .server import serve
        serve(args.db, args.host, args.port, args.web_root, args.public_origin, args.tailscale_user)
    elif args.command == "mcp":
        from .mcp import run_stdio
        run_stdio(args.db, web_url=args.web_url)
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
