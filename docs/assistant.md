# WBot Assistant Qt 桌面预览

Assistant 使用 **PySide6 + Qt Widgets** 提供本机小窗口，包含自动化搜索、发布包导入、参数填写、运行记录、日志和 JSON 结果。Qt 界面与后台执行服务是独立进程：关闭窗口收起到系统托盘，已接受的任务继续运行；重新打开可查看原作业。系统没有可用托盘时，关闭窗口退出界面，后台服务仍继续运行。

当前源码正在开发流程独立环境托管，尚未作为 Assistant 正式版本发布；已发布的 Assistant 0.10.0 仍采用旧的共享解释器。Studio 负责创建项目及 `.venv`，开发者或部署工具负责在目标机器准备环境，Assistant 只负责校验、进程托管、参数、日志和结果。[OC 管理端](oc.md) 可审批设备、管理发布包并派发任务；执行机器需要事先登记对应版本的流程目录。

## 流程独立环境托管（开发版）

1. 在 VS Code 执行“新建自动化项目（含虚拟环境）”，或在目标机器的流程目录中准备 `.venv` 与全部依赖。环境需要 Python 3.10+，禁止 `--system-site-packages`；非 Windows 平台使用 `venv --copies`。
2. 打开开发版 Assistant，在“我的自动化”点击“托管流程”，选择包含 `wbot.json` 和 `.venv` 的目录。登记时校验解释器和清单依赖，并保存声明代码的不可变副本。
3. 选择流程、填写参数后运行。Assistant 使用该目录 `.venv/Scripts/python.exe`（非 Windows 为 `.venv/bin/python`）；不会向子进程注入宿主 SDK 路径。使用 WBot API 的流程需要自行安装 SDK；纯标准库脚本不需要安装 WBot。
4. 同一版本可重复登记相同目录；更换代码、依赖或部署目录应发布新版本，并为新版本准备独立目录和环境。不同流程版本不能共享同一个已登记目录。

本机接口为 `POST /api/projects`，请求体为 `{"path":"D:/flows/example"}`，沿用现有本机会话授权。已登记信息保存在 Assistant 数据目录，重启后仍有效。任务使用独立工作目录，环境始终留在流程目录中；每次启动都重新检查环境与依赖。

旧 `.wbot.zip` 仍可导入和查看，但未登记运行环境时不允许执行，也不会回退到宿主 Python。已导入包可以通过登记内容完全一致的项目目录补上环境。OC 下发同名同版本、内容相同的包不会覆盖本机环境绑定；没有预先部署的环境时明确报告失败。

本阶段只实现本机部署目录托管；尚未实现跨电脑环境的打包、传输与重建。普通 `.venv` 不具备通用可搬运性，不能通过复制目录解决跨电脑部署。基础 Python 和流程目录都应位于 Assistant 安装目录之外，避免程序升级影响流程。

## 连接新版 OC（Assistant 0.8.0 起）

1. 管理员进入 OC 的 **Robot 连接 → 生成 Key**，填写用途名称与有效期。
2. 复制仅显示一次的 Key。在 Assistant 的设置中填写 **OC 服务地址、设备名称、接入 Key**，点击保存并申请绑定。生产地址为 `https://rpa.marswei.fun`，不需要额外路径。
3. 管理员核对设备 ID 与确认码后批准，Assistant 自动显示已绑定。

一个 Key 只能用于一台设备。首次使用前须在有效期内；同一身份的网络失败可以重试。Key 在本机待申请期间持久保存，绑定成功后清除，设置查询与日志不返回 Key。OC 只保存 Key 的哈希。撤销 Key 仅阻止绑定申请；禁用已绑定设备请使用 **撤销绑定**。已有设备重新连接无需重复输入 Key；拒绝或撤销后重新申请需要新的 Key。

新版 OC 拒绝旧客户端的无 Key 首次申请，已经批准的设备仍可继续工作。历史独立 Python OC 保留旧协议兼容，仅用于本地旧版测试；生产以独立 Go OC 为准。

## 界面与外观

首页分别显示本机后台和 OC 连接状态；点击 OC 状态或齿轮进入主窗口内的设置页。点击左上角“返回”或按 Esc 回到首页；搜索、选中项和运行记录页签保持不变，尚未提交的连接草稿在本次界面会话中保留。返回不等于保存，连接信息仍需点击“保存并申请绑定”；外观选项选择后立即生效。托盘中的“连接设置”也打开同一个页面，不另开窗口。设置支持浅色、深色、跟随系统和高对比度，选项保存在 Assistant 数据目录的 `appearance.ini`，不会改变后台连接。系统模式监听 Qt 提供的颜色与对比度偏好通知；手动选择不会被系统切换覆盖。

“我的自动化 / 运行记录”采用滑动选中块（200 ms）和内容淡入（180 ms）。快速切换会取消上一次过渡；隐藏页面或调整窗口时结束动画，保持当前页可操作。设置中的“减少动态效果”立即生效并保存在 `appearance.ini`，开启后直接切换。

外观与布尔参数使用统一的圆角下拉列表，当前值带勾选标记，支持方向键、Enter 确认与 Esc 取消；长选项会省略显示。下拉列表优先出现在控件下方，靠近屏幕底部时向上展开。

等待审批时展示确认码和复制按钮；已绑定后隐藏确认码与申请按钮，修改连接信息后重新显示提交操作。长名称可通过提示查看完整内容，列表支持键盘焦点边框。参数错误显示在字段旁，并聚焦首个错误字段。

参数定义可选添加 `title`（1–120 字符）作为显示名称，例如 `"count": {"type":"integer", "title":"执行次数", "required":true}`；运行时仍使用原来的 `count` 键。此字段要求构建工具、OC 和 Assistant 都更新到支持它的版本，旧版本会拒绝未知字段。不提供 `title` 的已有自动化保持兼容。

[内嵌设置页预览](images/assistant-settings-page/settings-page-light.png) · [下拉框预览](images/assistant-controls-motion/dropdown-light-480.png) · [页签切换动画](images/assistant-controls-motion/tab-switch.gif) · [深色主页预览](images/ui-polish/home-dark.png)。预览使用示例数据。

## 环境与首次运行

在仓库根目录执行以下 PowerShell 命令。当前固定的 Qt 依赖要求 Python 3.10–3.15，Windows 建议沿用项目的 Python 3.13 环境。Qt 界面依赖由 [requirements-assistant.txt](../requirements-assistant.txt) 安装；`wbot` wheel 只提供 Python 库，不包含 Assistant 应用，以下模块命令需要保留仓库源码。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m pip install -r requirements-assistant.txt
.\.venv\Scripts\python.exe -m app.automation_package build examples/assistant-demo
.\.venv\Scripts\python.exe -m app.assistant open
```

首次构建生成 `examples/assistant-demo/dist/assistant-demo-0.1.0.wbot.zip`。重复构建不会覆盖这个文件；修改项目后应先提高 `wbot.json` 的版本，再构建新包。

Qt 窗口打开后：

1. 在“我的自动化”点击“托管流程”，选择已准备独立 `.venv` 的流程目录。单独导入 `.wbot.zip` 只登记代码，还需要绑定相同版本的流程环境。
2. 选择 `assistant-demo`，点击“运行所选自动化”，填写 `name` 后点击“开始运行”。
3. 在运行详情查看“执行日志”和“运行结果”；成功时得到问候日志和 `{"message": "你好，填写的名字"}` 结果。以后可从“运行记录”重新打开详情。

服务默认监听 `127.0.0.1:8791`，只提供本机访问。若端口已被其他程序占用，可用 `--port 0` 自动分配，并以启动结果中的 URL 为准。

需要浏览器诊断界面时，可显式使用：

```powershell
.\.venv\Scripts\python.exe -m app.assistant open --browser
```

Qt 界面不需要 pywebview、WebView2 或网页前端。未安装 Qt 依赖时，默认入口会提示安装依赖，不会自动切换浏览器。浏览器诊断页导入时填写发布包的本机完整路径；它使用同一个后台服务与历史记录。原有 `run.py` 仍启动 pywebview 编码桌面，和 Assistant 是不同入口。

## 连接 OC 管理平台

在主窗口点击齿轮图标“连接设置”，填写 **OC 服务地址** 和 **设备名称**，点击“保存并申请绑定”。服务地址应由 OC 管理员提供，使用独立的设备接入端口；不要填写浏览器管理页面的地址。

| 默认地址 | 用途 |
| --- | --- |
| `127.0.0.1:8791` | Assistant 本机界面与执行服务通信 |
| `127.0.0.1:8792` | 在 OC 电脑上打开管理页面，仅本机可访问 |
| `127.0.0.1:8793` | OC 设备接入默认地址，仅适合同机测试；跨电脑时由管理员开放设备监听地址并提供可访问的 IP 或域名 |

跨电脑使用 `https://OC域名:设备端口`，或明确接受明文传输的测试 HTTP 地址。不能将 `0.0.0.0`、`::` 或另一台电脑上的 `127.0.0.1` 当作连接目标。设备端口、HTTPS 证书和启动命令见 [OC 接入说明](oc.md)。

申请提交后：

1. “设备绑定”显示“等待管理员批准”、设备 ID 和六位确认码。
2. 将设备名称、ID 和确认码提供给管理员，由其在 OC 的待审批列表中核对核验码，再批准申请。
3. Assistant 自动更新为“已绑定”，后台持续发送心跳并领取分配给本机的任务。
4. 管理员在 OC 上传发布包、部署到该设备并手动运行。Assistant 下载并校验包，在独立任务进程执行，再回报状态、日志和 JSON 结果。OC 的停止请求也会传递到实际任务进程。

主窗口分别显示本机服务和 OC 连接状态；打开设置页可查看详细的绑定状态。审批被拒绝或授权被撤销时，需要重新申请并由管理员再次批准，旧绑定不会自动恢复。本机手工导入与运行仍可用于开发试用；它不是组织授权流程目录。

### 断开、切换后台与结果补报

| 操作或状态 | 当前行为 |
| --- | --- |
| 关闭窗口或退出 Qt 界面 | 后台连接、已接受任务与结果同步继续 |
| 点击“断开连接” | 暂停本机与 OC 的连接，不撤销 OC 中的设备授权；使用原地址和设备名称可重新连接 |
| 本机仍有实际执行中的任务 | 不允许切换后台或断开，需先等待任务结束或明确停止任务 |
| 任务已结束，但结果尚未回传 | 允许断开或切换后台，保留原身份与待回报记录；回到原 OC 地址和原设备名称后继续补报 |
| 任务已领取但尚未启动时切换或断开 | 在本机取消该任务；重新连接原后台后回报“已停止”，不会为了补报而执行它 |
| 管理员在 OC 撤销绑定 | 阻止新任务和包下载；已经运行的任务继续，并仍可回报状态、日志和结果 |

切换到其他 OC 不会把旧任务结果发送给新后台，也不会同时维持多个后台连接。需要补报时，填写原 OC 地址与原设备名称，并保留 Assistant 数据目录。仍有效的原绑定会复用；已拒绝或撤销的绑定需要重新申请，旧任务按原身份记录向原后台补报。已记录的远程作业在连接服务重启或结果请求重试时不会重新执行。连接状态、任务执行结果和是否已经回报 OC 是不同信息，结果待同步不能当成任务仍在执行。

设备身份由本机后台生成和持久保存，Qt 与浏览器只获得公开连接状态，不会收到设备密钥。该能力用于设备绑定，不提供组织账号登录、用户角色或授权流程目录。

## 共享元素开发连接

VS Code 的共享元素功能也使用这条 OC 连接。新版后台提供本机工作副本、版本提交与申请接口，Qt 窗口无需保持打开。插件的 `wbot.assistantStateDir` 必须与该后台的数据目录一致；共享元素编辑、差异查看和发起申请均在 VS Code 中完成。见 [共享元素指南](shared-elements.md)。

## Windows 便携版

便携版面向 Windows x64。完整解压 `WBotAssistant-windows-x64.zip` 后，双击其中的 `WBotAssistant/WBotAssistant.exe` 即可打开 Qt 窗口。包内包含 Qt 及 Assistant 后台需要的 Python、wbot 和 lxml；流程运行环境由流程自行提供，与这些后台依赖分开。

请保留整个 `WBotAssistant` 目录，不要只复制 EXE：

| 路径 | 用途 |
| --- | --- |
| `WBotAssistant.exe` | 桌面入口，无参数时打开 Qt 窗口 |
| `_internal/` | Qt 界面及其打包依赖 |
| `python/` | 仅供 Assistant 后台服务使用的 Python |
| `runtime/` | 后台服务、wbot 和浏览器诊断页 |
| `licenses/`、`checksums.sha256.json` | 第三方许可和构建时的文件校验摘要 |

Qt 依赖随桌面入口分发，未安装到任务 Python 中。请用 EXE 打开窗口；管理后台服务时，在便携目录打开 PowerShell，可执行：

```powershell
.\python\python.exe -m app.assistant status
.\python\python.exe -m app.assistant stop
```

默认数据仍保存在 `%USERPROFILE%\.wbot-assistant`，不在便携目录里。源码入口和便携入口如果使用相同数据目录，会连接已运行的同一个服务；切换任务 Python 环境需要先停止原服务，再用目标入口启动。`stop` 会终止当前任务，退出 Qt 界面则不会。

如果旧版后台尚在运行，新版界面也会复用它；缺少连接设置接口的旧后台无法提供本次新增功能。当本机健康检查成功、`/api/settings` 返回 404 时，界面会提示“当前本机后台不支持连接设置”，并说明关闭窗口不会停止后台。可以等现有任务完成后停止旧后台，再启动新版。也可以在新版 `WBotAssistant` 目录打开 PowerShell，使用独立数据目录试用，保留旧版任务与数据：

```powershell
.\WBotAssistant.exe open --state-dir "$env:USERPROFILE\.wbot-assistant-preview" --port 0
```

独立试用目录不会自动导入旧版的自动化、记录和连接设置；以后需要继续这次试用时，使用相同命令。

需要额外依赖时，开发者或运维人员在流程自己的目录中安装。例如为清单中声明的 `openpyxl==3.1.5` 准备环境：

```powershell
.\.venv\Scripts\python.exe -m pip install "openpyxl==3.1.5"
```

业务依赖安装和环境重建都属于开发、部署环节，需要可用的软件源或离线 wheel。Assistant 不提供依赖安装、共享环境或环境切换功能。

开发者完成前面的源码依赖安装后，可在仓库根目录构建便携版：

```powershell
.\.venv\Scripts\python.exe -m pip install PyInstaller
.\.venv\Scripts\python.exe build_assistant.py
```

产物为 `dist/WBotAssistant/` 和 `dist/WBotAssistant-windows-x64.zip`。构建脚本会检查内置 Python、真实后台任务、Qt 初始化和重复启动唤起；已有构建也可运行 `python build_assistant.py --verify-only`。便携包包含版本元数据和文件校验清单，可由 OC 发布在线更新。这仍是便携预览，尚无安装向导、开机启动或 Windows 服务注册，企业部署与升级验收仍未完成。

## 在线更新（GitHub / OC）

从 Assistant 0.10.0 起，尚未配置 OC 的客户端直接从公开仓库 `DevilHill/wbot` 的 GitHub Releases 检查正式版本，不需要 GitHub Token。界面显示更新来源、更新说明和包大小。只接受 `assistant-v主版本.次版本.修订版本` 标签、Windows x64 附件和完整更新清单；忽略草稿、预发布和其他产品的 Release，按数字版本比较并处理分页。网络、限流和发布包异常会显示检查失败，不会误报为已是最新版本。

只要保存过 OC 连接配置，更新仍通过 OC 获取；待批准、断线、暂停连接、被拒绝或撤销授权时不会自动切换 GitHub。下载和安装前再次确认来源、发布状态、版本信息和校验值，下载后新配置 OC 也会阻止安装原来的 GitHub 更新。当前没有清除 OC 管理状态或手动切换更新源的界面。

旧版独立客户端需要手动安装 0.10.0 才能使用 GitHub 检查更新；已绑定 OC 的旧版可以由管理员上传 0.10.0 ZIP 后更新。当前只在用户点击“检查更新”时查询，不自动下载或安装。

从 Assistant 0.7.0 起支持用户确认的在线更新。更早的便携包没有更新入口，首次仍需手动安装 0.7.0，并在任务结束后停止旧后台、启动新版。源码运行可检查版本，不会自动替换开发目录。

1. 独立用户从 GitHub 获取已发布版本；OC 管理员在“客户端更新”上传构建生成的 ZIP，核对版本与说明后发布给全部已批准设备或指定设备。
2. 在 Assistant“设置 → 软件更新”点击“检查更新”，查看新版本和说明，再点击“下载更新”。下载与校验在后台完成。
3. 任务结束后点击“更新并重启”。执行端在锁内检查空闲状态，并暂停接受新任务；忙碌时拒绝安装并保留已下载内容，需要用户稍后重试。
4. 独立更新程序等待旧界面退出，停止旧后台，将旧程序保存在同级 `.wbot-backup-*` 目录后替换程序。新版后台和界面确认就绪后恢复接单；启动检查失败会恢复旧程序并重新启动。

跨电脑更新要求 HTTPS OC 接入地址和受信任证书；仅回环地址允许 HTTP 联调。更新请求复用已批准的设备身份，下载不跟随重定向。安装前再次核对发布授权、包的 SHA-256、文件清单和待安装内容；撤回版本会阻止后续安装申请，已经接受的安装不会被远程取消。管理员上传的是可执行软件，应只发布可信构建。当前没有独立代码签名或自动信任自签名证书。

GitHub 下载使用独立客户端，允许有限次数的 GitHub HTTPS 附件跳转，支持系统代理，不发送 OC 凭据或 GitHub Token。清单与附件大小、SHA-256 和 ZIP 内元数据必须一致，下载失败会清理本次不完整文件。GitHub 官方发布的信任依赖 HTTPS 和仓库发布权限；SHA-256 是内容一致性检查，不是独立发布者签名。

独立更新进程关闭 Windows 严重错误和崩溃对话框，让损坏的启动文件及时返回错误并进入回滚，避免更新停留在等待系统对话框的状态。

更新需要程序所在目录可写、至少 1 GiB 可用空间，且数据目录位于程序目录之外。默认 `%USERPROFILE%\.wbot-assistant` 符合要求。连接配置、包和作业记录保留在数据目录；更新替换整套程序及内置 Python，后续业务依赖应包含在发布包中，临时安装在旧程序目录里的依赖不会自动迁移。

当前为整包更新，无断点续传、强制批量安装或定时维护窗口。后台重启后需要重新检查和下载。旧程序与 `.wbot-update-*` 暂存目录保留便于排查，确认版本正常后可由管理员清理；更新过程中不要清理。结果保存在数据目录的 `update-result.json`，更新工作目录内有 `worker.log`。断电等进程外中断不保证自动恢复，应依据备份目录和工作目录的 `plan.json` 恢复程序；不会自动回滚用户数据或数据库迁移，发布版本须保持已有数据格式兼容。

构建版本由 `app/assistant/version.py` 管理，使用 `主版本.次版本.修订版本`，相同版本不可覆盖。可以用 `python build_assistant.py --release-notes path/to/notes.txt` 指定 UTF-8 更新说明（最多 8000 字）。上传旧版不含 `assistant-release.json` 的 ZIP 会被拒绝。

[软件更新界面预览](images/assistant-updates/updates-light-480.png)（示例数据）。

### 发布 Assistant 到 GitHub

1. 修改 `app/assistant/version.py`，增加对应的 UTF-8 更新说明 `docs/releases/assistant-<版本>.txt`，提交并推送代码。
2. 推送与代码版本一致的标签，例如 `assistant-v0.10.0`，触发 `.github/workflows/publish-assistant.yml`。普通分支提交不会发布版本。
3. Windows 工作流运行更新、连接和界面测试，再调用现有构建验证。产物包括 `WBotAssistant-windows-x64.zip` 和 `assistant-update.json`，外部清单由实际 ZIP 自动生成，包含版本、平台、说明、大小和 SHA-256。
4. 发布任务核对标签与产物，先创建草稿并上传两个附件，成功后再转为正式版。不会改动整个仓库的 Latest 标记，客户端自行筛选 Assistant 版本。同名 Release 已存在时发布失败，不覆盖原有附件；若失败留下未发布草稿，需核查并删除该草稿后再重跑，正式版修复必须使用新版本号。

工作流只使用内置 `GITHUB_TOKEN`，发布任务需要仓库 `contents: write` 权限，无需另设个人 Token。Actions 中手动运行此工作流只构建并保存 artifact，不发布版本。第一期 OC 继续使用上传 ZIP 的方式，尚未自动同步 GitHub。

本地构建示例：

```powershell
python build_assistant.py --distpath dist/assistant-0.10.0 --release-notes docs/releases/assistant-0.10.0.txt
```

同一份说明同时写入 ZIP 内元数据、外部清单和 GitHub Release 正文。发布后的标签、附件与版本号应保持不变。

开发者可在已安装 Qt 的 Windows 构建环境执行 `python tools/verify_assistant_updates.py dist/WBotAssistant`。该验证使用独立临时目录、临时 OC 和真实便携程序，检查忙碌拒绝、通过 Qt 按钮正常退出并升级、数据保留，以及注入无效新版界面后的回退；不会连接日常使用的 Assistant 数据目录。

## 服务命令与生命周期

以下为源码方式的命令，均在仓库根目录执行；可将 `python` 换为 Assistant 自身的解释器。业务任务始终使用已登记流程目录中的独立虚拟环境。

| 命令 | 行为 |
| --- | --- |
| `python -m app.assistant start` | 启动后台服务和 HTTP 工作台，输出包含 URL 的 JSON；命令随即退出，不打开窗口 |
| `python -m app.assistant open` | 启动或连接后台服务，打开 Qt 窗口；同一数据目录已有界面时唤起原窗口 |
| `python -m app.assistant open --browser` | 使用系统浏览器打开诊断工作台，不启动 Qt 窗口 |
| `python -m app.assistant serve` | 在当前终端前台运行服务；按 Ctrl+C 停止服务及正在执行的任务 |
| `python -m app.assistant status` | 输出服务是否运行及其 URL、进程 ID |
| `python -m app.assistant stop` | 停止后台服务；正在执行的任务也会被终止 |

所有动作支持 `--state-dir PATH`，默认目录为 `~/.wbot-assistant`，Windows 对应 `%USERPROFILE%\.wbot-assistant`。`--port` 默认 `8791`，`0` 表示自动分配。连接已有数据目录的服务时会复用其地址；改变端口或 Python 环境需先停止再启动。

为试用指定独立目录时，后续查询和停止应使用同一路径：

```powershell
python -m app.assistant start --state-dir .local/assistant-preview --port 0
python -m app.assistant open --state-dir .local/assistant-preview
python -m app.assistant status --state-dir .local/assistant-preview
python -m app.assistant stop --state-dir .local/assistant-preview
```

“关闭窗口”“退出界面”“停止当前任务”和“停止后台服务”是不同动作：

- 关闭 Qt 主窗口：有系统托盘时收起到托盘，可从托盘重新打开。
- 退出 Qt 界面：结束界面进程，后台服务和已接受任务继续运行；再次执行 `open` 可恢复查看。
- 在作业详情停止任务：只终止选中的任务及其子进程。
- 执行 `stop`：停止后台服务及当前任务。

同一数据目录只保留一个 Qt 界面实例；不同数据目录可连接各自的后台服务。当前没有 Windows 服务注册或开机启动，也不保证注销或关机后任务继续。服务异常退出后，重启会将未确认任务标记为“中断待核实”，不会自动从头重跑。

## 项目清单与构建

创建项目必须指定一个尚不存在的目录：

```powershell
python -m app.automation_package init automations/my-automation --name my-automation
python -m app.automation_package build automations/my-automation
python -m app.automation_package inspect automations/my-automation/dist/my-automation-0.1.0.wbot.zip
```

也可在 VS Code 执行 **WBot: 初始化自动化项目** 和 **WBot: 构建自动化发布包**。构建前会保存编辑内容，详情见 [VS Code 指南](../vscode-extension/README.md)。当前构建生成本地文件，不会上传到 OC。

最小项目由 `wbot.json` 和 `main.py` 组成。初始化清单如下：

```json
{
  "schemaVersion": 1,
  "name": "my-automation",
  "version": "0.1.0",
  "entry": "main.py",
  "files": ["main.py"],
  "parameters": {
    "name": {
      "type": "string",
      "default": "WBot",
      "description": "问候对象"
    }
  },
  "requirements": {}
}
```

| 字段 | 当前规则 |
| --- | --- |
| `schemaVersion` | 必须是整数 `1` |
| `name` | 1–80 位，英文字母或数字开头，只使用英文字母、数字、`_`、`-` |
| `version` | 固定语义版本，如 `0.1.0`、`1.0.0`；不接受 `latest` |
| `entry` | `files` 中声明的 `.py` 文件，使用项目内相对路径 |
| `files` | 显式文件白名单，可包含 Python 模块和数据；未声明文件不打包，不支持通配符或目录条目 |
| `parameters` | 参数名到声明的对象；无参数时为 `{}` |
| `requirements` | 依赖包名到精确版本的对象，如 `{"openpyxl": "3.1.5"}`；无额外依赖时为 `{}` |
| `elements` | 可选，`wbot-elements` JSON 的相对路径，且必须同时列入 `files` |

清单不接受上述范围外的字段。相对路径统一使用 `/`，拒绝绝对路径、`..`、链接、保留设备名和大小写冲突。包内只包含清单、白名单文件及 `checksums.sha256.json` 完整性索引。

默认输出为 `<项目>/dist/<name>-<version>.wbot.zip`。`build --output PATH` 可指定完整输出文件路径，但已有文件仍不会覆盖。Assistant 允许重复导入内容完全相同的同名版本；同名同版本内容不同则拒绝。更新业务代码时提高版本并重新构建，不要直接改动已安装目录。

包上限为 1000 个文件、单文件 16 MiB、总解压大小 64 MiB、清单/校验元数据各 256 KiB。导入先验证文件集合和完整性再安装；哈希不验证发布者身份，应导入自己信任的来源提供的包。

## 参数与运行结果

参数支持 `string`、`number`、`integer`、`boolean`，可声明 `required`、`default`、`description`。参数名使用英文字母或下划线开头，后续为字母、数字或下划线，最多 80 位。

本次输入覆盖默认值；未输入且有默认值时使用默认值；缺少必填参数时拒绝运行；既无默认值又非必填的参数可省略。未知参数会被拒绝，类型不会自动转换，例如字符串 `"true"` 不能代替布尔 `true`。当前没有枚举、文件上传、密码控件或声明式输出 schema。

包中的 Python 入口通过 `wbot.runtime` 使用运行上下文：

```python
from wbot import runtime

parameters = runtime.parameters()
message = f"你好，{parameters['name']}"
print(f"作业 {runtime.job_id()}：{message}")
runtime.set_result({"message": message})
```

| API | 行为 |
| --- | --- |
| `runtime.parameters()` | 返回已经校验并合并默认值的参数字典 |
| `runtime.job_id()` | 返回本次作业 ID，用于关联日志和记录 |
| `runtime.set_result(result)` | 保存 JSON 对象结果；再次调用会替换本次结果，不会追加 |

结果必须是可序列化的 JSON 对象，最大 1 MiB，不接受 NaN/Infinity。脚本正常退出后界面显示该结果；没有设置结果也可正常完成，界面显示“尚无返回结果”。异常和强制终止不作为成功结果展示。

这些 API 需要 Assistant 执行上下文。直接 `python main.py` 或用现有 VS Code“运行当前 Python 脚本”执行初始化示例，会提示没有运行上下文；当前应通过构建、导入、运行来验证它。普通 `.py` 脚本的原有 VS Code 运行与 debugpy 调试继续可用，自动注入包运行上下文的调试入口尚未提供。

## 依赖、工作目录与元素资产

源码和便携服务都使用流程自带的 `.venv`，按 `requirements` 检查已安装版本是否完全相符。环境缺失、失效、开启系统依赖共享，或依赖版本不符时明确失败；Assistant 不安装依赖，不创建环境，也不回退到自身 Python。

每次作业将已安装包复制到自己的工作目录，避免业务脚本修改发布版本。相对输出路径落在该作业的 `work` 目录。工作目录隔离不限制 Python 对本机其他文件、网络或进程的访问，不是安全沙箱。

需要元素资产时，从元素库导出 `wbot-elements` JSON，将文件加入 `files`，并设置例如 `"elements": "assets/elements.json"`。构建副本会移除临时的浏览器、标签页、框架及文档 ID，原始项目文件不变。每次运行导入独立 SQLite 元素库，脚本使用：

```python
from wbot import selector

elements = selector.SelectorStore()
search = elements.get("搜索框", group="首页")
```

避免在发布脚本中写作者机器上的元素库绝对路径；该路径会覆盖运行服务提供的项目库位置。元素资产包含定位规则，不包含可跨次恢复的浏览器登录和 iframe 链。

Assistant 目前不自动启动或管理浏览器桥。`web.get()` 仍需要有效的本机桥、浏览器扩展及最近一次抓取；关闭 VS Code 会关闭其自建桥，因此不能把该模式直接承诺为脱离编辑器的无人值守运行。需要独立浏览器时使用 `web.create()`，另行准备 Playwright、浏览器及业务登录条件，具体限制见 [wbot 文档](wbot.md)。

## 运行、停止与本地记录

同一服务一次只接受一个任务；忙时拒绝新的运行请求，不进入等待队列。界面通过请求 ID 避免同次提交重试重复执行；有意再次运行会创建新作业。

“运行记录”显示总作业数，列表最多加载 200 条摘要，优先显示活动任务，其余按创建时间倒序。搜索只筛选当前加载的记录；更早的历史仍保留，当前没有翻页入口。打开单条详情后才读取完整输入参数和结果，历史列表不会同时加载每份大结果。

状态包括准备环境、运行中、停止中、已完成、失败、已停止和中断待核实。停止当前任务会强制终止该任务拥有的进程及子进程，不支持任意 Python 代码暂停/恢复或业务回滚。停止时可能已经完成部分外部写入，重新执行前需核实结果。`stop` 服务命令也会终止正在运行的任务。

默认数据目录包含：

| 路径 | 内容 |
| --- | --- |
| `assistant.sqlite3` | 已安装包记录和作业历史 |
| `connection.sqlite3` | OC 连接身份档案及远程作业回报记录，包含本机绑定身份，备份时按凭据管理 |
| `packages/<name>@<version>/` | 通过校验的安装内容 |
| `jobs/<job-id>/work/` | 本次运行的工作副本及脚本写入的相对路径文件 |
| `jobs/<job-id>/output.log` | 标准输出与错误输出，最多 4 MiB，截断会标记 |
| `jobs/<job-id>/result.json` | 脚本通过 runtime 写入的结构化结果 |
| `service.log` | 后台服务启动和处理错误日志 |

Qt 详情最多显示最近 20000 行日志；本机 `output.log` 仍受 4 MiB 上限约束。远程回报最多携带 512 KiB 日志尾部，超出时带截断说明；这不改变本机日志上限。当前不提供产物下载、自动日志保留期限、包卸载或磁盘配额管理。历史和本地文件会保留；OC 可以主动读取本机接入的记录，或接收远程 Assistant 上报。输入参数和脚本日志可能包含业务数据，不应把凭据直接当普通参数传入或打印。

## 验证与常见问题

在仓库根目录执行相关测试：

```powershell
python -m unittest discover -s tests -p "test_automation_package.py" -v
python -m unittest discover -s tests -p "test_assistant*.py" -v
```

| 现象 | 处理方法 |
| --- | --- |
| `No module named app` | 回到仓库根目录；单独安装 wbot wheel 不包含 Assistant |
| 提示缺少 PySide6 | 使用运行 Assistant 的同一个 Python 安装 `requirements-assistant.txt`；或显式使用 `open --browser` 诊断后台服务 |
| 便携版提示运行资源不完整 | 重新完整解压便携目录，保留 EXE 旁的 `_internal/`、`python/` 和 `runtime/` |
| 点击关闭后仍有托盘图标 | 关闭窗口只收起界面；用托盘退出界面，停止服务则使用 `stop` |
| 重复启动没有出现第二个窗口 | 同一数据目录会唤起原窗口，避免重复托盘实例 |
| 主窗口已连接，但 OC 显示离线 | 主窗口指本机服务；打开“连接设置”检查 OC 地址、绑定审批与错误提示 |
| 一直等待管理员批准 | 将设备 ID 和确认码提供给管理员，在 OC 的待审批列表核对后批准 |
| OC 地址提示服务不兼容 | 检查是否误填了管理端口 8792；应使用管理员提供的设备接入地址，默认端口为 8793 |
| 结果待同步但需要切换后台 | 任务已经结束时可以切换；保留数据目录，之后使用原地址与原设备名称恢复连接并补报 |
| 构建提示目标已存在 | 保留已有版本，增加清单版本后重新构建 |
| 导入提示同名同版本内容不同 | 不覆盖已发布版本，使用新的版本号 |
| 任务提示依赖缺失/不符 | 在启动服务的 Python 环境安装声明的精确版本，再运行 |
| 服务启动失败 | 查看所选数据目录下 `service.log`；检查端口或用 `--port 0` |
| 任务成功但没有结果 | 确认脚本调用 `runtime.set_result()`；`print()` 只进入日志 |
| 服务重启后显示中断待核实 | 先核实业务系统结果，再决定是否作为新作业重跑 |

当前未实现 Assistant 组织登录及授权目录同步、定时调度、业务凭据托管、开机服务、自动环境准备或完整无人值守桌面能力。远程设备绑定、手动派发与结果回报已经提供；Qt 的“我的自动化”仍展示本机已安装包，OC 的流程名称、用户授权与部署目录尚未同步成 Assistant 的业务目录。其余能力按产品需求继续建设，不计为开发预览已经交付。


## 0.9.0：统一元素与浏览器服务

Assistant 后台启动时持有本机 8790 浏览器桥，VS Code 插件通过 Assistant 会话调用元素库、抓取与 XPath 校验。插件不再启动独立 Python 服务；关闭编辑器不影响 Assistant。默认沿用 `~/.xpath_studio/elements.sqlite3`，启动 Assistant 前可用 `WBOT_ELEMENT_LIBRARY` 指定原有自定义库；`WBOT_BROWSER_PORT` 可调整监听端口（隔离测试可用 0），浏览器扩展目录会按实际地址生成。

升级需同时更新 Assistant 与插件到 0.9.0，重新加载旧版 VS Code 窗口释放其桥接端口。端口冲突时 Assistant 继续提供任务与连接功能，元素操作明确报错，不复用身份不明的服务。浏览器扩展通过插件“准备浏览器扩展目录”取得 Assistant 持有的副本。
