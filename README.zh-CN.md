# Research Workflow Studio

![Research Workflow Studio](docs/assets/research-workflow-studio.png)

**由人掌握方向、AI 协助记录与推进的研究工作流：把问题、代码、证据和报告连接起来。**

[官网与在线体验](https://borgdiven.github.io/research-workflow-studio/) · [English website](https://borgdiven.github.io/research-workflow-studio/en/) · [代码模板](templates/README.md) · [数据约定](CONTRACT.md)

它是一个本地网页工作台，配套 Python 后端、SQLite 数据库和 MCP 服务。MCP 是模型读写工作台记录的接口：模型可以创建项目和研究节点、读取上下文、登记实现与材料、整理评估和报告；实际写代码、运行程序仍使用开发工具。研究判断、项目基础修改和来源纠正由人决定。

## 开始使用

需要 Python 3.9+，运行时没有第三方依赖；界面面向电脑端，当前使用中文。

```sh
git clone https://github.com/BorgDiven/research-workflow-studio.git
cd research-workflow-studio
mkdir -p .local
python3 tools/seed_showcase.py --db "$PWD/.local/showcase.sqlite3"
python3 launch.py serve --db "$PWD/.local/showcase.sqlite3" --port 8831
```

打开 http://127.0.0.1:8831。演示包含虚构项目主页、分叉研究树、四类代码、几何图形、曲线与固定报告。可重复导入，拒绝向含其他项目的数据库写入；不运行模型、不代表科研结论。建立自己的空工作台时，换一个数据库文件并省略 `seed_showcase.py`。

## 三个视图，共用同一份记录

- **研究**：先读项目基础，再看问题、假设、探索和阶段；小实验也可以只为寻找 insight。
- **代码与执行**：推理、评估、分析、报告分别展示。先定义代码块的输入输出和验收规则，再编写可复用实现；不同案例和参数不另造代码版本。
- **产出与对比**：单案例比较不同设置，多案例对齐不同实现；按产物类型与步骤筛选，缺图留空、重复结果明确选择，查看来源时再展开实际执行记录。

对比集合用于探索；分析说明观察、解释、范围和限制；报告固定当时选中的证据和项目基础。相同材料可以被多个研究或报告引用，来源不变。

以下动图和桌面预览使用独立的虚构项目、程序生成的几何图形及人为设定的示例指标，不含真实研究数据。

[观看完整操作演示](https://github.com/BorgDiven/research-workflow-studio/releases/download/v0.3.3/workspace-tour.mp4)

![从项目主页进入研究、代码与执行及产出对比](docs/assets/workspace-tour.gif)

**研究**
![项目基础与研究关系](docs/assets/research-view.png)

**代码与执行**
![可复用实现与代码角色](docs/assets/code-view.png)

**产出与对比**
![按输入和条件对齐的产出对比](docs/assets/comparison-view.png)

## 接入 AI

在支持 stdio MCP 的客户端中配置 `python3 /绝对路径/research-workflow-studio/launch.py mcp --db /绝对路径/studio.sqlite3 --web-url http://127.0.0.1:8831`。网页和 MCP 必须指向同一数据库，客户端需要重新连接。完整配置见 [英文 README](README.md#connect-your-ai-client)。

可以这样开场：

> 进入我的项目，读取项目基础和当前节点，说明已经完成什么、缺少什么、下一步建议做什么。写代码前先找可复用实现，并建立输入输出规则。实际执行和科研决策按我的指令进行。

工作台的 MCP 不提供任意 shell、文件读取或 GPU 启动接口；登记一条运行记录不等于运行程序。模型提出的基础修改与来源纠正需要独立的人工确认。

## 开发和使用边界

四类可复用模板见 [templates](templates/README.md)。代码实现绑定规则版本、Git commit、入口及检查证据；案例、指令、普通参数放在外部输入中。检查器默认只做静态检查，`--execute` 才会实际执行本地代码。

当前是 0.3.3 单用户早期版本，没有多用户协作权限、自动实验调度或手机布局。可以通过 [Tailscale 私有访问](docs/deployment.md) 跨电脑使用；公开仓库不包含真实研究数据库和材料。历史来源纠正保留原记录，旧报告不会被新数据改写。

[数据约定](CONTRACT.md) · [架构](docs/architecture.md) · [后续方向](docs/roadmap.md) · [贡献](CONTRIBUTING.md)
