# WBot OC 管理与设备接入预览

**本文保留的是 wbot 仓库中的历史 Python OC 兼容说明。** OC 的正式源码、架构规范与云端自动部署已迁至私有仓库 [DevilHill/wbot_oc](https://github.com/DevilHill/wbot_oc)，新版启动、数据迁移和部署请以该仓库文档为准，需要相应访问权限。公开 `wbot` 仓库继续维护 Assistant / Runner、Studio 与 Python SDK；旧 OC 代码暂时保留，后续另行移除，不再作为生产发布来源。

OC 提供 Robot 连接、Environment 环境、Asset 配置、自动化包、流程部署、运行队列和运行日志的统一入口。管理界面采用 **React + TypeScript + Vite**；Python 服务保存配置与任务，连接本机 Assistant，或接受其他电脑上的 Assistant 申请绑定并在批准后派发任务。自动化脚本由 Assistant 的独立任务进程执行。

管理页面和管理 API 默认只监听 OC 本机；云端部署通过 HTTPS 访问，使用 OC 自带账号登录与管理员、开发者、操作员、只读用户四类角色。跨电脑 Assistant 使用独立的设备接口。一个 OC 可管理本机目录接入与已批准的远程绑定。界面中的“默认组织”是预览范围标识，设备绑定审批不等于组织账号或用户权限系统。完整企业私有部署与调度目标见 [产品需求架构](product-requirements.md)。

云端支持 PostgreSQL 持久化与 Redis 心跳缓存；本机未配置数据库连接时继续使用 SQLite。服务器部署、数据迁移、备份和运行边界见 [OC 部署指南](oc-deployment.md)。服务器驱动单独列在 `requirements-oc.txt`，Assistant 无需安装。

## 获取代码与环境

```powershell
git clone https://github.com/DevilHill/xpath_tool.git
cd xpath_tool
```

- [Python](https://www.python.org/downloads/) 3.10+，Windows 推荐 3.13。用于 OC 服务和 Assistant 执行环境。
- [Node.js](https://nodejs.org/) 22.12+ 与 npm，用于构建 React 页面及运行前端测试。依赖版本由 [oc-web/package-lock.json](../oc-web/package-lock.json) 固定。
- Windows 本机浏览器。只试运行问候示例时，不需要浏览器自动化扩展或 Playwright。

先确认命令可用：

```powershell
python --version
node --version
npm --version
```

下方演示从源码启动 OC 和 Assistant，单独安装 `wbot` wheel 不包含这两个应用。执行以下命令时应处于仓库根目录。Assistant 也可使用带独立 Python 的 Windows 便携版，启动方式见 [Assistant 指南](assistant.md)。本机接入填写服务的数据目录；跨电脑接入则在 Assistant 中填写 OC 设备接入地址。

## 首次启动

管理台同时提供“客户端更新”入口，发布流程见下方“Assistant 版本发布”。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
npm --prefix oc-web ci
npm --prefix oc-web run build
.\.venv\Scripts\python.exe -m app.assistant start --state-dir build/assistant-local --port 0
.\.venv\Scripts\python.exe -m app.oc open --state-dir build/oc-local
```

已有虚拟环境时可复用，执行服务使用启动它的 Python 环境。`npm ci` 按锁文件安装依赖，构建输出位于 `oc-web/dist`。OC 直接提供构建后的页面和 API，正常使用时无需同时运行 Vite 开发服务。

OC 默认地址为 `http://127.0.0.1:8792`。它只监听本机回环地址，不能把该地址给另一台电脑访问。端口占用时可指定 `--port 0` 自动分配，并以启动输出中的 URL 为准。

## Assistant 版本发布

“客户端更新”管理 Assistant 软件版本，与“自动化包”中的业务脚本包分别管理：

1. 上传 `build_assistant.py` 生成的 Windows x64 ZIP（最多 128 MiB）。OC 校验版本元数据、包内路径和全部文件哈希，成功后保存为草稿，相同版本号不能覆盖。
2. 点击“发布版本”，选择全部已批准远程设备或指定设备。全部设备范围包含后续批准的设备；本机目录接入设备需要先完成 OC 绑定才能获取在线更新。
3. 用户在 Assistant 设置页检查和下载更新，并在设备空闲时确认安装。只有高于当前版本、已发布且属于设备发布范围的版本会被返回。
4. 发现问题时点击“撤回”，阻止新的下载和安装授权；此操作不会取消已接受的安装，也不会把已经升级的设备降级。

客户端跨电脑在线更新必须使用 HTTPS 设备接入服务，证书配置方式见“跨电脑设备接入”。管理页面仍复用现有本机管理会话，云端管理账号及权限见 [部署指南](oc-deployment.md#账号与角色)。首版提供用户确认的整包更新，不做强制推送、灰度比例、定时安装或数据迁移回滚。首次将旧客户端升级到支持在线更新的 0.7.0 仍需手动安装。

更新包保存在 OC 数据目录的 `assistant-releases/`，版本与发布范围记录在所配置的数据库中（本机默认 `oc.sqlite3`，云端为 PostgreSQL）。备份 OC 时应同时保留数据库和文件。具体客户端流程与回退边界见 [Assistant 在线更新](assistant.md#oc-在线更新)。

首次打开应看到空的管理台；页面中的包、设备、流程与作业计数都来自当前 OC 数据目录，不自动生成演示业务记录。

## 跑通一个真实作业

1. 在仓库根目录构建示例：

   ```powershell
   .\.venv\Scripts\python.exe -m app.automation_package build examples/assistant-demo
   ```

   生成 `examples/assistant-demo/dist/assistant-demo-0.1.0.wbot.zip`。已有输出不会被覆盖；相同文件可直接使用，业务内容变更后应提高清单版本并重新构建。

2. 在 OC 的自动化包页面上传这个 ZIP。上传会校验并保存包，**不会执行其中的脚本**。

3. 在 Robot 连接页面点击“接入本机设备”，填写名称，以及前面启动服务时使用的数据目录完整路径。可以在 PowerShell 中查看：

   ```powershell
   Resolve-Path build/assistant-local
   ```

   此处填写 Assistant 数据目录，不是项目源码目录、Python 路径或 OC 数据目录。Assistant 必须已经运行；OC 不替用户启动或注册 Windows 服务。

4. 创建流程，选择已上传包的确定版本和已接入 Robot，或创建 Environment 后将其设为执行目标。填写业务名称、说明与参数默认值；需要统一维护的参数可绑定同类型 Asset。

5. 点击“入队”，填写 `name`、选择优先级并提交。OC 等待目标 Robot 就绪，再安装包并派发固定版本和参数的作业。

6. 在运行队列跟踪等待和执行状态；在运行日志中打开本次作业，查看日志与 `{"message": "你好，填写的名字"}` 结果，也可以搜索日志行或下载 OC 已收到的完整文本。

原有 Assistant 工作台仍可单独打开。OC 流程部署和本次派发记录属于 OC；Assistant 负责实际执行，因此界面分别展示 OC 作业 ID 与执行服务作业 ID。尚未实现业务用户登录 Assistant 后自动取得 OC 授权目录。

## 跨电脑 Assistant 绑定审批

OC 默认将设备接入服务监听在 `127.0.0.1:8793`，用于同机测试。跨电脑接入时，在 OC 电脑上指定可被执行电脑访问的监听地址。准备好证书和私钥后，可启用 HTTPS：

```powershell
python -m app.oc open --state-dir build/oc-remote --agent-host 0.0.0.0 --agent-port 8793 --agent-cert certs/oc.pem --agent-key certs/oc-key.pem
```

`--agent-cert` 和 `--agent-key` 必须成对提供，路径对应部署方准备的 PEM 文件；实际连接 IP 或域名应与证书匹配。未提供证书时使用 HTTP，传输不加密；仅用于明确接受该条件的测试环境。执行电脑必须能访问设备端口。管理页面仍使用 OC 电脑上的 `http://127.0.0.1:8792`，不会随设备监听地址开放到网络。已运行的同一 OC 数据目录会复用现有服务；改变监听地址、端口或证书前，应停止对应 OC 服务再启动。

OC 启用设备接入服务后，“Robot 连接”页面顶部会显示 Assistant 连接接入地址。将它提供给执行电脑上的 Assistant。该地址与浏览器管理地址不同；`127.0.0.1` 只能用于同机测试，`0.0.0.0` 或 `::` 是监听地址，连接时应替换为 OC 电脑可访问的 IP 或域名，并保留实际端口。

1. 在 Assistant 的 OC 连接设置中填写设备接入地址和设备名称，提交绑定申请。
2. 在 OC 的“Robot 连接 → 待审批申请”核对设备名称、完整设备 ID、六位核验码与申请时间。设备使用者应提供 Assistant 中显示的同一设备 ID 和核验码；核验码用于确认申请，不是登录凭据。
3. 点击“批准”。界面显示“已批准”后仍需等待 Assistant 心跳；批准与在线是不同状态。也可点击“拒绝”，保留处理记录。
4. 已批准设备显示 `agent` 接入方式、绑定状态、在线/忙碌/离线状态、最近心跳、当前作业数和维护模式。原有本机目录设备显示 `local`，不需要远程申请审批。
5. 创建或编辑流程时，Robot 选项只包含已批准的远程绑定和本机设备。待审批、已拒绝、已撤销的连接不可选；忙碌、离线或维护中的 Robot 可以作为排队目标，实际派发必须等待它在线、空闲且未维护。

需要取消授权时，在已批准的远程设备卡片点击“撤销绑定”，核对确认框中的设备名称与 ID，再点击“确认撤销绑定”。撤销或拒绝后，当前绑定不能领取新任务或下载包；已经运行的任务继续执行，并可向 OC 上报状态、日志和结果。尚未领取的派发记录会标记失败，已经领取但尚未开始执行的任务也可能因授权撤销而无法启动；管理端不会因此把正在运行的任务直接标记为成功或停止。

被拒绝或撤销的绑定不能直接恢复。Assistant 需重新提交申请，生成新的设备 ID 和核验码，由管理端再次核对并批准。设备页只展示核验信息，不展示设备密钥。审批操作提交期间禁用重复操作；服务拒绝请求或网络异常时保留错误提示，请先核对刷新后的绑定状态。

## 当前管理能力

| 页面 | 可执行的操作 | 边界 |
| --- | --- | --- |
| 概览 | 查看真实包、流程、设备与作业状态，进入相关页面 | 不展示虚构统计；未连接设备时不能推断任务已完成 |
| 自动化包 | 上传并查看包版本与清单信息 | 同名同版本内容不可变；完整性校验不验证发布者身份 |
| 流程 | 指定包版本、Robot 或 Environment、默认参数和 Asset 绑定，编辑、启停及提交队列 | 修改版本与参数只影响后续作业；停用会暂停已有等待任务的调度 |
| Robot 连接 | 接入本机 Assistant；审批、拒绝、撤销远程绑定；查看所属环境、绑定与心跳，设置维护 | 一个连接身份对应一个 Robot；旧设备 ID 和接口保留兼容 |
| Environment | 创建、编辑、删除环境；添加或移除 Robot；启用或暂停调度 | 环境可为空；一个 Robot 可加入多个环境，但容量在所有环境间共享 |
| Asset | 创建、编辑、删除文本、数字、整数或布尔配置；自动增加修订号 | 普通配置明文保存，不用于密码或令牌；被流程引用时不可删除或修改类型 |
| 运行队列 | 按优先级查看等待任务，查看等待原因、取消等待，跟踪派发与执行 | 优先级在提交时确定；无自动重试、抢占、等待超时或计划触发 |
| 运行日志 | 搜索运行记录、筛选状态，查看日志、参数、Asset 修订和结果，下载日志 | 执行中的停止为强制终止，可能已有业务副作用；日志下载仅包含 OC 已收到的内容 |

运行队列持久化在所配置的数据库中，Redis 不作为任务存储。管理端提交进入 `queued`；调度按优先级 0–100 从高到低、同优先级按提交顺序处理。界面提供低（10）、普通（50）、高（90）三档。有可用资源时先在服务锁内预留 Robot，保存为 `dispatching`，然后交给 Assistant。每个 Robot 同时只承接一个未结束的 OC 作业；派发未知状态也占用资源，避免重复执行。不能运行的任务不会阻塞其他有可用目标的任务。高优先级持续到达可能延后低优先级任务，目前没有优先级老化。

OC 服务独立驱动调度，关闭浏览器不影响队列；停止 OC 后暂停派发，重新启动同一数据目录继续等待任务。已接受的 Assistant 作业独立执行。禁用流程或暂停 Environment 会暂停等待任务，恢复后继续；更换环境成员影响尚未派发任务的候选 Robot。流程版本、参数、目标环境 ID 和 Asset 值在入队时固定；流程改绑不会改写已有队列目标。已派发任务不会被重新分配。撤销指定 Robot 后，其等待任务标为失败；环境任务可以等待其他已授权成员。

Asset 绑定在流程部署中按参数类型选择。解析顺序为包默认值、流程默认值、Asset 当前值、API 显式参数覆盖；React 运行表单将绑定参数显示为只读来源。作业保存解析后的参数及实际使用的 Asset ID、名称、修订号，因此修改 Asset 不改变等待或运行中的作业。当前 Asset 属于默认组织，不按环境覆盖，也没有脚本端动态读取或凭据托管。

旧 `POST /api/oc/processes/{id}/run` 保留立即运行语义，仅支持指定 Robot；新管理界面使用 `POST /api/oc/processes/{id}/enqueue`，正文为 `request_id`、可选 `parameters` 和可选 `priority`。重复请求 ID 与同一内容返回同一作业，不同内容返回错误。资源管理接口为 `/api/oc/environments` 和 `/api/oc/assets`（GET 列表、POST 创建）、`/{id}`（PATCH 更新）、`/{id}/delete`（POST 空对象删除），沿用本机管理会话鉴权。`GET /api/oc/robots` 提供连接列表，不向普通 Agent 开放整个配置目录。状态快照保留 `devices` 并提供同身份的 `robots` 列表。

本机目录接入的日志与结果由 OC 主动读取；远程 Assistant 主动上报状态、日志与结果。已缓存内容可在设备离线时查看；同步失败或使用缓存应与最新执行状态区分。远程每次上报最多 512 KiB 日志尾部，超出时显示截断说明；Assistant 本机日志仍最多保留 4 MiB，JSON 结果最多 1 MiB。当前没有文件产物下载、日志自动清理或磁盘配额管理。

## 共享元素与合并

共享元素管理位于左侧“共享元素”：管理员可创建仓库、查看主分支元素和版本、审阅开发者提交的合并申请，逐项解决冲突后合并，或填写原因关闭申请。历史恢复会产生新的主分支提交，保留原有历史。开发者从 VS Code 插件提交，身份沿用批准的 Assistant 设备；当前没有按个人账号或仓库配置的成员权限。详细流程见 [共享元素与合并管理](shared-elements.md)。

## 服务命令与数据目录

| 命令 | 行为 |
| --- | --- |
| `python -m app.oc start` | 启动后台 OC 服务，输出 URL 后返回终端 |
| `python -m app.oc open` | 启动或连接 OC 服务并在浏览器打开管理台 |
| `python -m app.oc serve` | 在当前终端前台运行，Ctrl+C 停止 OC |
| `python -m app.oc status` | 查看所选数据目录对应的 OC 服务是否运行 |
| `python -m app.oc stop` | 停止 OC 服务，不停止 Assistant 或已接受的任务 |

命令默认数据目录为 `~/.wbot-oc`，管理端口默认 `8792`，设备接入端口默认 `8793`。使用 `--state-dir PATH` 时，后续 `open`、`status`、`stop` 应指定同一路径。`--web-dir PATH` 可指定已构建页面的目录，默认使用仓库的 `oc-web/dist`。设备接入另用 `--agent-host`、`--agent-port` 配置，HTTPS 证书参数见前面的跨电脑接入步骤。

```powershell
.\.venv\Scripts\python.exe -m app.oc status --state-dir build/oc-local
.\.venv\Scripts\python.exe -m app.oc stop --state-dir build/oc-local
.\.venv\Scripts\python.exe -m app.assistant stop --state-dir build/assistant-local
```

最后一条命令才会停止 Assistant 及其当前任务。只关闭浏览器或停止 OC 时，Assistant 可继续执行；重新打开 OC 后需要再次读取并核对状态。

OC 数据目录与 Assistant 数据目录应分别保留。OC 保存包、部署、设备和作业记录；Assistant 保存实际安装包、工作目录及执行日志。远程连接使用任务派发和结果上报，不是两个数据目录的整体同步；当前没有自动备份或升级迁移工具。

## 前端开发与验证

构建前端：

```powershell
npm --prefix oc-web ci
npm --prefix oc-web run build
npm --prefix oc-web test
```

开发时先完成一次构建，再在两个终端分别运行后端与 Vite：

```powershell
# 终端一：API 固定使用 8792，与开发代理配置一致
python -m app.oc serve --state-dir build/oc-dev --port 8792
```

```powershell
# 终端二：Vite 热更新页面
npm --prefix oc-web run dev
```

访问 Vite 输出的 Local 地址，通常为 `http://127.0.0.1:5173`。`/api` 请求由 Vite 代理到 `127.0.0.1:8792`，同源请求的 Origin 一并转换；后端仍保留 Host、Origin 和会话令牌校验。若已有 OC 占用 `8792`，可复用该服务，或先使用对应数据目录停止它。修改前端后需重新执行 `npm run build`，才会更新 OC 直接提供的静态页面。

后端回归测试：

```powershell
python -m unittest discover -s tests -p "test_oc*.py" -v
```

资源管理与队列浏览器回归脚本为 `tools/verify_oc_operations.py`。使用已安装 Playwright 的 Python 和本机 Edge，在完成前端构建后运行：

```powershell
python tools/verify_oc_operations.py
```

脚本创建独立临时 OC 数据目录，验证 Environment、Asset、流程绑定、任务参数快照、远程任务领取和上报、日志搜索与下载，并检查桌面及 390 像素窄窗口布局。它不连接日常使用的 OC；截图保存在 `output/playwright/oc-operations/`。该脚本模拟远程 Robot 的报告；真实 Assistant 任务进程与连续调度由 `tests/test_oc_service.py` 覆盖。前端构建包含严格 TypeScript 检查，当前未配置独立 lint 命令。

React 源码位于 [oc-web](../oc-web/)，后端位于 [app/oc](../app/oc/)。前端开发模式与发布构建不同：Vite 提供热更新，OC 服务负责接口与持久化。具体开发代理配置见 [vite.config.ts](../oc-web/vite.config.ts)。

## 尚未交付

本次没有多用户登录、组织/空间权限、时间触发器、逐订单或发票的业务事务队列、业务凭据托管、审计中心、自动依赖环境或 OC 生产部署安装包。流程运行队列已交付；Environment 是 Robot 分组，不负责安装 Python 依赖或校验成员能力，管理员需要确保成员具备流程所需软件与访问权限。Assistant 已提供 **PySide6 + Qt Widgets** 本机小窗口与托盘，使用方法见 [Assistant 指南](assistant.md)；连接绑定已经纳入 OC 审批，但业务用户登录与授权流程目录同步尚未完成。

OC 管理 API 的本机边界、管理会话和设备绑定分别承担不同职责，不等于完整企业身份认证。设备接入能力不表示企业权限、安装升级、审计、容量与灾难恢复已经验收完成。
