# WBot OC 管理与设备接入预览

OC 提供自动化包、流程部署、执行设备和作业记录的统一入口。管理界面采用 **React + TypeScript + Vite**；Python 服务保存包与部署配置，连接本机 Assistant，或接受其他电脑上的 Assistant 申请绑定并在批准后派发任务。自动化脚本由 Assistant 的独立任务进程执行。

管理页面和管理 API 仍只允许 OC 本机访问；跨电脑 Assistant 使用独立的设备接入地址。一个 OC 可管理本机目录接入与已批准的远程绑定。界面中的“默认组织”是预览范围标识，设备绑定审批不等于组织账号或用户权限系统。完整企业私有部署与调度目标见 [产品需求架构](product-requirements.md)。

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

首次打开应看到空的管理台；页面中的包、设备、流程与作业计数都来自当前 OC 数据目录，不自动生成演示业务记录。

## 跑通一个真实作业

1. 在仓库根目录构建示例：

   ```powershell
   .\.venv\Scripts\python.exe -m app.automation_package build examples/assistant-demo
   ```

   生成 `examples/assistant-demo/dist/assistant-demo-0.1.0.wbot.zip`。已有输出不会被覆盖；相同文件可直接使用，业务内容变更后应提高清单版本并重新构建。

2. 在 OC 的自动化包页面上传这个 ZIP。上传会校验并保存包，**不会执行其中的脚本**。

3. 在执行设备页面点击“接入本机设备”，填写设备名称，以及前面启动服务时使用的数据目录完整路径。可以在 PowerShell 中查看：

   ```powershell
   Resolve-Path build/assistant-local
   ```

   此处填写 Assistant 数据目录，不是项目源码目录、Python 路径或 OC 数据目录。Assistant 必须已经运行；OC 不替用户启动或注册 Windows 服务。

4. 创建流程，选择已上传包的确定版本和已接入设备，填写业务名称、说明与参数默认值。

5. 手动运行流程，填写 `name`。OC 将包安装到目标 Assistant，然后派发固定版本和参数的作业。

6. 在作业记录中打开本次作业，查看状态、日志与 `{"message": "你好，填写的名字"}` 结果。

原有 Assistant 工作台仍可单独打开。OC 流程部署和本次派发记录属于 OC；Assistant 负责实际执行，因此界面分别展示 OC 作业 ID 与执行服务作业 ID。尚未实现业务用户登录 Assistant 后自动取得 OC 授权目录。

## 跨电脑 Assistant 绑定审批

OC 默认将设备接入服务监听在 `127.0.0.1:8793`，用于同机测试。跨电脑接入时，在 OC 电脑上指定可被执行电脑访问的监听地址。准备好证书和私钥后，可启用 HTTPS：

```powershell
python -m app.oc open --state-dir build/oc-remote --agent-host 0.0.0.0 --agent-port 8793 --agent-cert certs/oc.pem --agent-key certs/oc-key.pem
```

`--agent-cert` 和 `--agent-key` 必须成对提供，路径对应部署方准备的 PEM 文件；实际连接 IP 或域名应与证书匹配。未提供证书时使用 HTTP，传输不加密；仅用于明确接受该条件的测试环境。执行电脑必须能访问设备端口。管理页面仍使用 OC 电脑上的 `http://127.0.0.1:8792`，不会随设备监听地址开放到网络。已运行的同一 OC 数据目录会复用现有服务；改变监听地址、端口或证书前，应停止对应 OC 服务再启动。

OC 启用设备接入服务后，“执行设备”页面顶部会显示 Assistant 连接接入地址。将它提供给执行电脑上的 Assistant。该地址与浏览器管理地址不同；`127.0.0.1` 只能用于同机测试，`0.0.0.0` 或 `::` 是监听地址，连接时应替换为 OC 电脑可访问的 IP 或域名，并保留实际端口。

1. 在 Assistant 的 OC 连接设置中填写设备接入地址和设备名称，提交绑定申请。
2. 在 OC 的“执行设备 → 待审批申请”核对设备名称、完整设备 ID、六位核验码与申请时间。设备使用者应提供 Assistant 中显示的同一设备 ID 和核验码；核验码用于确认申请，不是登录凭据。
3. 点击“批准”。界面显示“已批准”后仍需等待 Assistant 心跳；批准与在线是不同状态。也可点击“拒绝”，保留处理记录。
4. 已批准设备显示 `agent` 接入方式、绑定状态、在线/忙碌/离线状态、最近心跳、当前作业数和维护模式。原有本机目录设备显示 `local`，不需要远程申请审批。
5. 创建或编辑流程时，设备选项只包含已批准的远程绑定和本机设备。待审批、已拒绝、已撤销的设备不可选；流程运行还要求设备在线、空闲且未维护。

需要取消授权时，在已批准的远程设备卡片点击“撤销绑定”，核对确认框中的设备名称与 ID，再点击“确认撤销绑定”。撤销或拒绝后，当前绑定不能领取新任务或下载包；已经运行的任务继续执行，并可向 OC 上报状态、日志和结果。尚未领取的派发记录会标记失败，已经领取但尚未开始执行的任务也可能因授权撤销而无法启动；管理端不会因此把正在运行的任务直接标记为成功或停止。

被拒绝或撤销的绑定不能直接恢复。Assistant 需重新提交申请，生成新的设备 ID 和核验码，由管理端再次核对并批准。设备页只展示核验信息，不展示设备密钥。审批操作提交期间禁用重复操作；服务拒绝请求或网络异常时保留错误提示，请先核对刷新后的绑定状态。

## 当前管理能力

| 页面 | 可执行的操作 | 边界 |
| --- | --- | --- |
| 概览 | 查看真实包、流程、设备与作业状态，进入相关页面 | 不展示虚构统计；未连接设备时不能推断任务已完成 |
| 自动化包 | 上传并查看包版本与清单信息 | 同名同版本内容不可变；完整性校验不验证发布者身份 |
| 流程 | 指定包版本、执行设备和参数默认值，编辑、启停及手动运行 | 修改部署只影响后续作业，已有作业保留创建时的快照 |
| 执行设备 | 接入本机 Assistant；审批、拒绝、撤销远程绑定；查看接入方式、绑定状态与心跳，设置维护 | 管理页仍仅本机访问；未批准设备不能部署，维护或撤销阻止新任务但不终止已接受任务 |
| 作业 | 查看状态、参数、错误、日志与结果，停止已派发任务 | 停止为强制终止，可能已有业务副作用；没有作业队列或自动重跑 |

单个 Assistant 同时只运行一个作业，忙碌时拒绝新作业。远程派发先保存为“派发中”，等待 Assistant 领取；每台设备仍只接受一个未完成的 OC 作业，这不是多任务等待队列或时间调度。禁用流程、未批准绑定、设备维护、离线或参数无效都不应当作运行成功。OC 提交使用请求身份避免同次请求重复派发；不确定的派发结果先与执行服务核对，不在重启时自动重新执行。

本机目录接入的日志与结果由 OC 主动读取；远程 Assistant 主动上报状态、日志与结果。已缓存内容可在设备离线时查看；同步失败或使用缓存应与最新执行状态区分。远程每次上报最多 512 KiB 日志尾部，超出时显示截断说明；Assistant 本机日志仍最多保留 4 MiB，JSON 结果最多 1 MiB。当前没有文件产物下载、日志自动清理或磁盘配额管理。

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

React 源码位于 [oc-web](../oc-web/)，后端位于 [app/oc](../app/oc/)。前端开发模式与发布构建不同：Vite 提供热更新，OC 服务负责接口与持久化。具体开发代理配置见 [vite.config.ts](../oc-web/vite.config.ts)。

## 尚未交付

本次没有多用户登录、组织/空间权限、时间触发器、业务等待队列、业务凭据托管、审计中心、自动依赖环境或 OC 生产部署安装包。Assistant 已提供 **PySide6 + Qt Widgets** 本机小窗口与托盘，使用方法见 [Assistant 指南](assistant.md)；设备绑定已经纳入 OC 审批，但业务用户登录与授权流程目录同步尚未完成。

OC 管理 API 的本机边界、管理会话和设备绑定分别承担不同职责，不等于完整企业身份认证。设备接入能力不表示企业权限、安装升级、审计、容量与灾难恢复已经验收完成。
