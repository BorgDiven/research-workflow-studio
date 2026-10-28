"""MCP tools over newline-delimited stdio; never grants human authority.

Protocol references (2025-11-25): modelcontextprotocol.io/specification/
2025-11-25/basic/{transports,lifecycle} and server/tools.
"""

import json
import sys
from urllib.parse import urlencode

from . import __version__
from .core import RwsError, Store, tool_definitions
from .origin import normalize_web_origin


SUPPORTED_VERSIONS = ("2025-11-25", "2025-06-18", "2024-11-05")
MAX_MESSAGE_BYTES = 4 * 1024 * 1024


def rpc_error(request_id, code, message, data=None):
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


class MCPConnection:
    def __init__(self, store, web_url='http://127.0.0.1:8831'):
        self.store = store
        self.web_url = normalize_web_origin(web_url)
        self.initialized = False
        self.ready = False

    def handle(self, message):
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return rpc_error(None, -32600, "Invalid Request")
        request_id = message.get("id")
        has_id = "id" in message
        method = message.get("method")
        # Client responses are ignored; this server never sends requests.
        if not method and ("result" in message or "error" in message):
            return None
        if not isinstance(method, str) or (has_id and (isinstance(request_id, bool)
                or not isinstance(request_id, (str, int)))):
            return rpc_error(None, -32600, "Invalid Request")
        params = message.get("params", {})
        if not isinstance(params, dict):
            return rpc_error(request_id, -32602, "Parameters must be an object") if has_id else None
        if not has_id:
            if method == "notifications/initialized" and self.initialized:
                self.ready = True
            return None
        if method == "ping":
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        if method == "initialize":
            if self.initialized:
                return rpc_error(request_id, -32600, "Connection already initialized")
            if not isinstance(params.get("protocolVersion"), str) or not isinstance(params.get("capabilities"), dict) or not isinstance(params.get("clientInfo"), dict):
                return rpc_error(request_id, -32602, "Invalid initialization parameters")
            requested = params["protocolVersion"]
            version = requested if requested in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
            self.initialized = True
            return {"jsonrpc": "2.0", "id": request_id, "result": {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "research-workflow-studio", "version": __version__},
                "instructions": "先用 rws_get_context 定位项目与当前步骤，再登记用户授权的研究记录。编写代码前先用 rws_code_find 查找复用，再用 rws_spec_save 定义方法级输入、输出、配置和验收；用 rws_research_save 的 implementationLinks 关联精确版本的 spec 或已有 code，标明 implementation（研究实现）、control（对照）或 diagnostic（诊断）用途。用途关联不是已执行或完成证据，省略保留原关联，[] 清空。随后实现并登记：实现必须绑定 ready spec 的精确版本、固定 Git commit 与 checkEvidence。case 和参数属于 run.sampleSelection/config，不能为每张图片复制方法代码。训练使用 kind=training；过程指标先在 spec.processMetrics 声明名称、单位、坐标、范围和评估协议，再由脚本或导入器批量调用 rws_metrics_append。rws_metrics_query 分页保持同一 throughSequence，rws_metrics_snapshot 固定所选历史成为报告可引用的产物，不为每个 step 建产物。产物区分 semantic、observation 和实际 producerRef；比较与报告固定引用已有结果，不移动其来源。服务器、仓库和环境用 rws_server_save/rws_repository_save/rws_environment_save 登记精确版本，只保存 SSH 别名和无凭据路径。rws_operation_propose 仅登记 Git 或任务操作计划；有副作用的操作必须由人在工作台批准该精确计划，再显式运行 CLI runner。只读检查也由 runner 采集，MCP 查询仅返回已采集记录及其时间。task.inspect/logs/stop 引用原 task.start，断线标记 unknown 并查询原任务，不能盲目重启；已有 checkout 的 commit 不一致必须先人工同步。checkEvidence 是客户端提交的检查记录，不代表 MCP 已执行验证。所有写入提供 requestId，修改现有项目需 expectedRevision。MCP 从不执行或批准程序；项目基础、阶段、科学判断与来源修正批准均由人完成。工作台地址：" + self.web_url}}
        if not self.initialized or not self.ready:
            return rpc_error(request_id, -32002, "Initialize and send notifications/initialized first")
        if method == "tools/list":
            if params.get("cursor"):
                return rpc_error(request_id, -32602, "This tool list has no additional page")
            return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": tool_definitions()}}
        if method != "tools/call":
            return rpc_error(request_id, -32601, "Method not found")
        if set(params) - {"name", "arguments", "_meta"} or not isinstance(params.get("name"), str) or not isinstance(params.get("arguments", {}), dict):
            return rpc_error(request_id, -32602, "Invalid tool call parameters")
        name = params["name"]
        if name not in {tool["name"] for tool in tool_definitions()}:
            return rpc_error(request_id, -32602, "Unknown tool")
        try:
            payload = self.store.call(name, params.get("arguments", {}), actor="model")
            is_error = False
        except RwsError as exc:
            error = {"code": exc.code, "message": exc.message}
            if exc.details:
                error["details"] = exc.details
            if exc.code == "approval_required":
                error["reviewPath"] = "/?" + urlencode({
                    "projectId": str(params.get("arguments", {}).get("projectId", "")),
                    "stages" if name == 'rws_project_stages_set' else "amendments" if name.startswith('rws_amendment_') else "operations" if name.startswith('rws_operation_') else "review": "1"})
                error['reviewUrl'] = self.web_url + error['reviewPath']
            payload = {"ok": False, "error": error}
            is_error = True
        except Exception:
            payload = {"ok": False, "error": {"code": "internal_error", "message": "操作未确认成功；请按原请求 ID 重试。"}}
            is_error = True
        for card in (payload.get('guidance'), payload.get('result')):
            if not isinstance(card, dict):
                continue
            for action in card.get('suggestedActions', []):
                path = action.get('reviewUrl')
                if isinstance(path, str) and path.startswith('/?'):
                    action['reviewUrl'] = self.web_url + path
        text = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        return {"jsonrpc": "2.0", "id": request_id, "result": {
            "content": [{"type": "text", "text": text}],
            "structuredContent": payload, "isError": is_error}}


def run_stdio(db_path, input_stream=None, output_stream=None, web_url='http://127.0.0.1:8831'):
    source = input_stream or sys.stdin.buffer
    sink = output_stream or sys.stdout.buffer
    connection = MCPConnection(Store(db_path), web_url=web_url)

    def write(value):
        if value is not None:
            sink.write((json.dumps(value, ensure_ascii=False, allow_nan=False,
                                   separators=(",", ":")) + "\n").encode("utf-8"))
            sink.flush()

    while True:
        line = source.readline(MAX_MESSAGE_BYTES + 1)
        if not line:
            break
        if len(line) > MAX_MESSAGE_BYTES:
            write(rpc_error(None, -32700, "Message exceeds the local size limit"))
            # Oversized streams are closed rather than parsed as multiple requests.
            break
        try:
            def reject_constant(value):
                raise ValueError("non-finite JSON")
            message = json.loads(line.decode("utf-8"), parse_constant=reject_constant)
        except (ValueError, UnicodeError):
            write(rpc_error(None, -32700, "Parse error"))
            continue
        write(connection.handle(message))
