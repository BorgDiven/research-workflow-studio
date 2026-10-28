# 数据接入格式 · 0.4

这是当前运行时约定。公开示例均为虚构输入，不代表一次已完成的模型实验；示例的引用必须替换成实际已登记对象。以实时 `tools/list` 或工作台附带的 `tools.json` 为完整参数定义。

## 先分清三种记录

| 内容 | 接口 / 字段 | 用途 |
| --- | --- | --- |
| 持续追加的训练或其他过程指标 | 规范 `processMetrics`；`rws_metrics_append/query` | 浏览过程，不在每一步制造产物 |
| 按协议完成的评估 | `rws_protocol_register` + `rws_evaluation_import` | 保存输入、评估规则和实际结果，不代算指标 |
| 已选定的固定证据 | `rws_metrics_snapshot` 或 `rws_artifact_register` | 为比较、分析和报告保留精确输入 |

引用格式为 `{projectId,type,id,version}`。`version` 是整数记录修订，与代码的人类可读版本名分开。过程运行、资源与操作请求使用精确修订。省略、缺失、失败、数值 0 不可混用。

## 过程指标

在编写实现前，在规范中声明：

```json
{
  "processMetrics": [
    {"id":"train_loss","name":"Training loss","unit":"1","axis":"step","scope":"run","direction":"lower","splits":["train"]}
  ]
}
```

- `axis` 是 `step`、`epoch` 或 `time`；`scope` 是 `run` 或 `sample`。
- `unit:"1"` 表示明确无量纲，不能把未登记单位等同于无量纲。
- 如定义 `splits`，点必须属于相应范围；样本级点需提供 `sampleId`。
- 可提供固定 `protocolRef`。没有协议时，比较仍核对同一精确规范版本，不能只因指标名字相同就合并。
- 运行固定代码，代码固定规范；后来编辑规范不改变旧运行的指标含义。

写入 `rws_metrics_append` 时，每批最多 1000 个点：

```json
{
  "projectId":"example-project","expectedRevision":12,"requestId":"example-metrics-1",
  "runRef":{"projectId":"example-project","type":"run","id":"run-example","version":1},
  "points":[
    {"metricId":"train_loss","x":0,"value":0.8,"split":"train"},
    {"metricId":"train_loss","x":1,"value":null,"split":"train","reason":"observation unavailable"}
  ]
}
```

`x` 必须有限且非负；数值必须有限，缺失用 `null` 并附 `reason`，不能提交 NaN/Infinity。`timestamp` 可选，记录真实时间，不用它猜测 epoch。相同运行、指标、split、sample、坐标下的相同点可重试，冲突值拒绝；不会取均值或覆盖原值。

`rws_metrics_query` 每次最多选择 20 个精确运行，返回 `series`、对齐结果、`total/offset/limit/truncated`；单页上限 5000 点；后续分页携带首次查询返回的同一 `throughSequence`。单位、横轴、范围、split、样本、协议或规范不匹配时分开。缺失保留 null，不插值。

`rws_metrics_snapshot` 选择一个固定运行、指标集合、坐标区间及查询返回的必填截止 `throughSequence`，超过 5000 点的快照拒绝保存，需缩小选择，不会截断后冒充完整。保存 `kind:table`、`semantic:metric-history` 的不可变产物。来源为 `source.kind:metric-history-snapshot`，保留原指标定义、查询范围与截止序号；内容表保留实际值和缺失原因。报告读取此固定内容，不再查询实时数据。

## 正式评估与通用产物

正式评估需要固定的 `protocolRef`、计算实现 `codeRef` 和具体 `inputRefs`。图像有参考评估使用显式 `pairs` 按 `sampleId` 指定预测和参考；不能靠目录顺序配对。协议说明指标名称、单位、方向、范围、预处理、聚合和缺失规则。

通用内容支持 `metric`、`series`、`image-set`、`table`、`attachment`。图片、预测 clean、速度场、注意力图、checkpoint 等使用准确语义。不会为单纯分析或可视化凭空创建方法改进假设。产物固定实际 `producerRef` 和配置；复用通过 usage 增加引用，不转移生产者。

只有 PDF/HTML 时可登记附件，但不能据此制造可比较数值。曲线和表格需另提供结构化数据。来源不清楚时使用显式 unresolved 来源和说明，不补造代码或运行。

## 资源与操作请求

服务器记录已有 SSH 别名或本地连接；仓库固定服务器、绝对 checkout 路径和远端；环境固定仓库、服务器、工作目录与 Python 可执行文件。代码可关联 `repositoryRef`，运行固定 `repositoryRef/environmentRef`。

`rws_operation_propose` 按操作类型只接受所需目标引用：Git 使用 `repositoryRef`，启动使用 `runRef + environmentRef`，环境检查使用 `environmentRef`，任务查询/日志/停止使用原 `launchOperationRef`。参数是结构化对象；启动是 argv 字符串数组，不是任意 shell 文本。

修改型请求须由网页人工确认。`rws_operation_approve/dismiss` 虽在工具列表中描述，但模型权限执行会被拒绝。真正运行使用明确的 CLI `operate --version`；内部领取和回执操作不对 MCP/HTTP 开放。未知结果不会自动变成失败或重新运行。

## 可下载示例

- [过程指标调用示例](../examples/process-metrics.json)：规范片段、批量写入、查询、固定快照；只校验参数结构，需先登记前提对象。
- [资源与操作请求示例](../examples/controlled-operations.json)：虚构的服务器、仓库、环境和启动/Git检查请求；没有审批或执行步骤。
- 旧单图、数据集和曲线包属于早期格式提案，不是可以直接提交的当前 MCP 参数。工作台保留历史说明供迁移核对；不要据此宣称已导入。

示例校验通过只说明参数结构符合当前工具定义，不证明引用存在、路径可访问、任务已运行、评估正确或研究有效。


MLflow HTTP 导入只用于 run 范围指标；规范声明 split 时，用 `--mlflow-split train` 等明确指定，不同 split 分别导入。样本级点必须通过 JSONL 提供真实 sampleId。推送要求固定 `repository.remoteUrl` 并匹配唯一实际远端；本地 bare 路径必须在 `workspaceRoot` 内。
