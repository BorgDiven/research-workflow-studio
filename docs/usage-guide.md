# 使用 Research Workflow Studio 0.4

工作台负责把研究问题、实现、实际运行和证据连接起来。模型通过 MCP 读写记录；你选择研究方向、解释证据并确认具体执行请求。网页和 MCP 必须使用同一数据库。

## 1. 进入项目，确定当前问题

项目基础保存目标、模型与数据基础、研究路线、实验约定和已确认认识。研究节点可以是探索、假设验证或复现。提出依据是前序研究关系；代码关联说明用哪份实现来研究、作对照或诊断。

模型先调用 `rws_get_context`，读取当前位置、已完成事实、缺口和建议；不能只根据节点名字猜测状态。编辑研究的 `implementationLinks` 可先关联固定规范版本，再编写实现。没有运行时也可以声明用途，声明本身不构成证据。

### 查看研究关联的代码

点击研究中的“关联代码”进入代码画布；顶部保留来源研究的类型与标题，关联代码以底色和用途标签标记。单击代码只切换右侧详情，其他关联高亮保留；再点同一块或点画布空白，只取消单块选择。

“取消高亮”恢复正常画布显示，但不切换研究、不关闭正在阅读的代码，也不删除关联；“显示关联”重新启用。选择另一项研究才更换关联来源。只有规范、尚无实现的关联显示为待实现规范；固定版本未载入时明确提示缺失，不替换成其他版本。

代码概览、源码与来源、产物与执行在右侧详情区阅读，不用底部弹层遮住代码。计划用途、实际执行和复用证据仍分别标记；继承连线仍只表示代码继承。

## 2. 写代码前定义规则

在“代码与执行”选择定义代码块，声明目的、输入、输出、配置与验收条件。角色包括训练、推理、评估、分析、报告。实际实现绑定 ready 规范的精确版本、仓库身份、固定 Git commit、模块入口和检查证据。

案例和普通参数放到运行的 `sampleSelection`、`config` 与 `inputRefs`，不会因为换一张图就另造实现。过程指标放入规范的 `processMetrics`，已有运行仍使用它原来绑定的规范版本。

可从源代码目录创建训练模板：

```sh
python3 tools/scaffold.py --kind training --destination .local/example-training --title "Synthetic training"
python3 tools/check_block.py .local/example-training --output .local/training-static.json
```

检查默认不执行代码。只有明确要运行已审核的本地块时，才加 `--execute`。模板使用合成数值，不下载模型、不启动 GPU。

## 3. 登记仓库与环境

项目基础和代码页都提供“仓库与运行环境”入口。

| 对象 | 保存的内容 | 登记后发生什么 |
| --- | --- | --- |
| 服务器 | 本地或已有 SSH 别名、工作区根目录 | 仅保存定位，不购置机器、不连接或配置 SSH |
| 仓库 | 固定服务器版本、已有 checkout 目录、远端身份 | 仅登记，不自动 clone 或 fetch |
| 环境 | 固定仓库与服务器版本、工作目录、Python 路径 | 仅描述既有环境，不安装依赖 |

密码、密钥和访问令牌放在既有 SSH/Git/环境配置中，不填入记录、命令参数或公开示例。更改资源会形成新修订，旧运行和已确认请求不会自动切到新地址。

## 4. 请求、确认、执行、看回执

从代码详情登记运行计划，固定实验、配置、输入和运行环境。计划不会产生结果。运行详情可提出启动请求；仓库详情可提出 Git 检查、分支、明确文件提交、标签或普通推送请求。

1. 模型或网页通过 `rws_operation_propose` 保存明确的参数与目标。
2. 对启动、停止、分支、提交、标签、推送等修改，你在网页确认或拒绝。模型权限不能调用成功人工审批操作。
3. 复制请求详情提供的执行器命令，到工作台服务器终端显式执行。只读检查无需单独审批，但同样需要执行器领取。
4. 查看任务 ID、状态、日志、退出码或错误。一次请求只领取一次；结果未知时保留未知，不自动重新启动。

命令结构如下。这里的项目、请求与路径都是占位；实际使用页面生成的精确版本命令：

```sh
python3 launch.py operate --db /absolute/path/studio.sqlite3 \
  --project-id example-project --operation-id operation-example --version 2
```

批准不会自行运行程序。这条 `operate` 命令才会执行。启动前检查 checkout 与固定代码 commit；不匹配时停止，不会擅自 reset、checkout 或覆盖代码。任务状态、日志、停止请求引用原启动任务，而不是凭 PID 猜测进程。执行器是受控操作通道，不是任意代码的安全沙箱。

SSH 路径已实现并由模拟传输测试覆盖；没有据此宣称实际远端已验收。执行器与记录客户端面向 macOS/Linux 等 POSIX 系统。

## 5. 批量记录过程数据

训练脚本按规范指标写入观察点，再批量上报。每一步无需模型调用，也不会成为一张新卡片。`x` 是规范声明的 step、epoch 或 time；`value:null` 必须说明缺失原因，不可当成 0。

JSONL 输入示意，每行一个对象：

```json
{"metricId":"train_loss","x":0,"value":0.8,"split":"train","eventId":"example-step-0"}
{"metricId":"train_loss","x":1,"value":null,"split":"train","reason":"sample unavailable","eventId":"example-step-1"}
```

向已登记运行导入：

```sh
python3 tools/track_metrics.py --db /absolute/path/studio.sqlite3 \
  --project example-project --run-id run-example --run-version 1 \
  --spool .local/example-spool --input .local/example-metrics.jsonl
```

用 `--studio-url http://127.0.0.1:8831` 可替代 `--db`，通过同一 HTTP 业务服务写入。spool 是此固定运行专用的本地待发目录。传输中断时保留待发内容；省略 `--input` 再次运行相同命令可继续发送。相同观察可重试，冲突值会被拒绝。

MLflow 接入是对已有服务的显式只读 HTTP 导入：

```sh
python3 tools/track_metrics.py --db /absolute/path/studio.sqlite3 \
  --project example-project --run-id run-example --run-version 1 \
  --spool .local/example-mlflow-spool \
  --mlflow-url http://127.0.0.1:5000 --mlflow-run-id external-run-example \
  --metric training_loss=train_loss --mlflow-split train
```

先在规范里定义对应指标，再给出外部字段到内部指标 ID 的映射。该导入器不安装 MLflow、不自动发现项目、不读取或改变外部任务状态、不接管训练，也不从数值导入成功推断研究结论。CLI URL 不接受内嵌凭据；程序接口可从内存提供额外请求头。

## 6. 浏览过程，固定证据

“产出与对比”保留图像布局，并提供曲线和指标布局。曲线只在指标、单位、横轴、范围和协议或规范相容时叠加；重复运行保留各自曲线，未知范围不强行对齐。界面可以刷新过程记录；查询有明确数量和分页限制。

过程观察仍可追加。把选中的指标与坐标区间保存为固定材料后，工作台记录截止序号，并生成 `metric-history` 产物。它可进入现有材料引用、比较、分析和报告链。后来追加的数据不进入旧材料或旧报告。

保存过程快照是在包装已有观察，不是重新评估模型。正式评估仍通过固定 `protocolRef` 声明输入配对、预处理、单位、聚合和缺失规则。分析写明观察、解释、范围与限制；报告固定选定证据和上下文。

## 安装与能力边界

安装和 MCP 配置见仓库 README；客户端更新后需重新连接以读取当前 37 个工具。公开在线演示只使用虚构材料，不保存、审批、执行或联系研究服务器。0.4 的浏览器、安装与发布验收以当前验证记录为准，不把文档更新当作上线证明。

[接口约定](../CONTRACT.md) · [0.4 数据约定](contract-v4.md) · [格式与示例](format-guide.md)


### 导入与推送边界

MLflow 历史没有 sampleId，此导入入口只用于 run 范围指标。规范声明 split 时，必须用 `--mlflow-split` 明确指定；不同 split 分别导入。样本级指标使用带显式 sampleId 的 JSONL。Git 推送要求先固定 `repository.remoteUrl`，并匹配唯一实际远端；本地 bare 远端的绝对路径必须在 `workspaceRoot` 内。
