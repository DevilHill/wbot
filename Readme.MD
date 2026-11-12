# WBot · Studio、Assistant 与 Python SDK

WBot 提供 Python 自动化开发与执行工具。本仓库维护 Studio（VS Code 插件）、Assistant 及其内部 Runner、Python SDK 和浏览器扩展。Studio 支持项目初始化和发布包构建；Assistant 使用 Qt 小窗口和系统托盘，负责本机使用、实际执行、日志与结果回报。

**OC 管理端已拆分至私有仓库 [DevilHill/wbot_oc](https://github.com/DevilHill/wbot_oc)**，其源码、架构规范与云端自动部署以该仓库为准，需要相应访问权限。本仓库现有 Python OC、`oc-web/` 及旧部署资料暂作历史兼容保留，后续另行移除；新增 OC 开发与生产发布请使用 `wbot_oc`。

原有独立 Python 自动化编码桌面继续提供：**文件树、多标签、Monaco 编辑器、保存、运行/停止、实时日志**。抓取浏览器元素后，可将 XPath 插入代码，并在右侧工作台校验、同步高亮。

- 行号、语法高亮、折叠、查找替换、基础补全与 wbot 代码片段。
- 新建/打开本机项目；保存时检测磁盘改动，避免覆盖外部修改。
- 打包 EXE 内置 Python 与 wbot 基础运行环境；编辑器资源离线使用。
- 保留元素库、抓取元素与 iframe 内的 XPath 校验。

[编码界面](docs/images/studio-code.png) · [VS Code 插件](vscode-extension/README.md) · [OC 管理端](docs/oc.md) · [共享元素与合并](docs/shared-elements.md) · [Assistant 桌面与 OC 连接](docs/assistant.md) · [产品需求架构](docs/product-requirements.md) · [wbot API](docs/wbot.md) · [浏览器扩展](extension/README.md)

## 获取代码

```powershell
git clone https://github.com/DevilHill/wbot.git
cd wbot
```

## 环境

- 源码方式使用 Windows 与 Python，推荐 [Python 3.13](https://www.python.org/downloads/)。Assistant 便携版已包含独立 Python 和 Qt。
- Assistant 桌面界面使用 [PySide6 / Qt Widgets](https://doc.qt.io/qtforpython-6/)，依赖见 [requirements-assistant.txt](requirements-assistant.txt)。
- 原有编码桌面的 pywebview 窗口使用 [WebView2 Runtime](https://developer.microsoft.com/en-us/microsoft-edge/webview2/)。
- Chrome / Edge 与配套扩展用于网页抓取；纯 Python 脚本无需浏览器。
- 运行历史 OC 前端兼容测试需要 [Node.js 22.12+ 与 npm](https://nodejs.org/)，依赖由 [oc-web/package-lock.json](oc-web/package-lock.json) 固定；新版 OC 环境要求见 `wbot_oc`。

## 启动与使用

以下为原有编码桌面的源码启动方式；Assistant 使用下方独立入口。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

也可用 `run.py --browser` 打开浏览器界面。服务只监听本机，默认端口 `8790`，被占用时顺延，以终端输出为准。

1. 点击 **新建项目** 或 **打开项目**；浏览器模式直接填写本机目录完整路径。
2. 在文件树打开 `.py`，或点击 **＋** 新建文件；可同时编辑多个标签。
3. **Ctrl+S** 保存，**F5** 或“运行”执行当前 Python 文件，结果显示在下方日志。
4. “停止”结束本次脚本及其子进程。运行前会保存已打开文件中的改动。

### 网页抓取与代码插入

1. 点击连接状态，在扩展页开启开发者模式，加载程序准备的扩展目录；刷新目标网页。
2. 点击 **抓取元素**，切到网页，`Ctrl+左键` 锁定、`Enter` 确认。
3. 在工作台点击 **插入代码**，把浏览器连接与定位代码插入当前 Python 文件；元素库记录也可插入。
4. 点击 **校验** 同步高亮匹配节点；页面刷新、导航后需重新抓取，iframe 定位器仅在对应框架内有效。

独立桌面当前支持运行/停止和日志。源码断点、单步、变量与调用栈可使用已有的 [VS Code 扩展](vscode-extension/README.md)。额外 Python 依赖与 wbot 范围见 [模块说明](docs/wbot.md)。

## 自动化项目与 Assistant 桌面

Windows 便携版完整解压后，双击 `WBotAssistant/WBotAssistant.exe` 打开小窗口，无需预装 Python 或 VS Code。应保留整个目录；构建方式、内置任务环境和使用限制见 [Assistant 指南](docs/assistant.md)。

完成上面的虚拟环境安装后，在仓库根目录构建示例并打开 Assistant：

```powershell
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m pip install -r requirements-assistant.txt
.\.venv\Scripts\python.exe -m app.automation_package build examples/assistant-demo
.\.venv\Scripts\python.exe -m app.assistant open
```

在 Qt 窗口点击导入按钮，通过系统文件选择器选择 `examples/assistant-demo/dist/assistant-demo-0.1.0.wbot.zip`，选择示例、填写 `name` 后运行，即可查看日志与 JSON 问候结果。构建不会覆盖同版本输出，修改示例后请先增加 `wbot.json` 的版本。

`open` 默认打开 Qt 窗口，同一数据目录重复启动会唤起原窗口；有系统托盘时，关闭窗口会收起到托盘。`open --browser` 显式打开浏览器诊断界面；`start` 只启动后台服务并输出 URL，默认端口 `8791`；`status` 查询服务，`stop` 停止服务及当前任务。关闭窗口或退出 Qt 界面均不终止已接受的后台任务。该行为与原有 `run.py` 编码桌面的进程生命周期不同。

在 Assistant 的齿轮“连接设置”中填写 OC 设备接入地址与设备名称，可提交绑定申请。管理员在 OC 核对设备 ID 与确认码并批准后，Assistant 会自动领取任务、下载校验包并回报状态、日志与结果。断开连接只暂停本机连接；撤销授权由 OC 管理员操作。切换后台和未同步结果的恢复步骤见 [Assistant 指南](docs/assistant.md)。

VS Code 新增 **WBot: 初始化自动化项目** 和 **WBot: 构建自动化发布包**。当前已有本地包运行和远程手动派发，没有组织用户登录、定时调度、自动依赖安装或依赖环境隔离；同一服务一次只运行一个任务。完整命令、清单、`wbot.runtime` API 和使用限制见 [Assistant 指南](docs/assistant.md)。

## OC React 管理端（历史兼容预览）

以下命令对应本仓库保留的旧 Python OC。新版管理端的启动、部署与迁移说明见 [wbot_oc README](https://github.com/DevilHill/wbot_oc#readme)；本仓库不再作为 OC 生产发布来源。

共享 XPath 元素现支持受保护的主分支、个人分支、版本记录与合并申请。VS Code 插件 0.5.0 可从当前元素库查看差异、提交并发起申请；OC 管理员可处理冲突、合并、关闭申请或恢复历史快照。通信复用已批准的 Assistant 设备连接，现阶段作者按设备记录。操作步骤和本地修改保护规则见 [共享元素指南](docs/shared-elements.md)。

完成 Python 虚拟环境与 wbot 安装后，构建管理页面并启动 OC：

```powershell
npm --prefix oc-web ci
npm --prefix oc-web run build
.\.venv\Scripts\python.exe -m app.assistant start
.\.venv\Scripts\python.exe -m app.oc open
```

OC 管理页面默认打开 `http://127.0.0.1:8792`，仍只允许本机访问。在管理台上传 `.wbot.zip`，接入本机 Assistant 数据目录或批准远程绑定，创建固定包版本和设备的流程，再手动运行并查看作业。上传包本身不会执行脚本。

设备接入使用另一个端口，默认 `127.0.0.1:8793`。跨电脑时由 OC 配置 `--agent-host 0.0.0.0 --agent-port 8793`，Assistant 填写 OC 电脑可访问的 IP 或域名。HTTPS 使用成对的 `--agent-cert` 和 `--agent-key` 参数；设备地址不等于管理页面地址。完整启动命令、TLS 配置、审批与撤销步骤见 [OC 指南](docs/oc.md)。

OC 使用 React + TypeScript + Vite、Python 标准库 HTTP 服务和 SQLite。Assistant 使用 PySide6 + Qt Widgets 的紧凑桌面窗口；两端复用独立执行服务，界面生命周期不控制已接受作业的执行。

## 构建与测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe build.py --distpath dist/1.5.0
.\.venv\Scripts\python.exe tools/verify_exe.py --exe dist/1.5.0/XPathStudio.exe
.\.venv\Scripts\python.exe tools/verify_studio_exe.py --exe dist/1.5.0/XPathStudio.exe
```

以上 EXE 构建命令对应原有编码桌面，产物为 `dist/1.5.0/XPathStudio.exe`；修改界面后需重新打包。

Assistant 使用独立的 [build_assistant.py](build_assistant.py)。安装 `requirements-assistant.txt`、wbot 与 PyInstaller 后运行 `python build_assistant.py`，生成 `dist/WBotAssistant/WBotAssistant.exe` 及包含完整目录的 `dist/WBotAssistant-windows-x64.zip`。这是带独立任务 Python 的便携预览；0.7.0 起支持 OC 发布版本、用户确认的在线更新与启动失败回退，尚无安装向导或开机启动。构建时会验证内置运行环境与 Qt 启动链路，首次安装与更新条件见 [Assistant 指南](docs/assistant.md#oc-在线更新)。

浏览器扩展可用 `tools/pack_extension.py` 打包，VS Code 扩展构建见其指南。

Monaco 固定为 **0.57.0**，资源及许可证位于 [vendor/monaco](app/web/vendor/monaco/)。需要重取资源时运行 `tools/vendor_monaco.py`，脚本核对 npm SHA-512，不执行安装脚本。

## 贡献与许可

通过 [Issues](https://github.com/DevilHill/wbot/issues) 提交问题，附复现步骤和脱敏日志。PR 请说明验证结果；定位规则应保持 Python / JavaScript 两端一致。

本项目采用 [MIT 许可证](LICENSE)。wbot 为独立实现，不声称完整兼容 xbot。Monaco 的第三方许可见其 [LICENSE](app/web/vendor/monaco/LICENSE) 和 [ThirdPartyNotices.txt](app/web/vendor/monaco/ThirdPartyNotices.txt)。
