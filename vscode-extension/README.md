# WBot Studio for VS Code · 编码版

**WBot 开发工具 0.7.1** 用于编写和运行 `wbot` Python 自动化脚本：直接编辑 `.py` 文件，使用 VS Code 的代码调试工具，并从元素库插入网页操作代码。共享元素仓库支持个人分支、版本提交和向 OC 发起合并申请。

支持新建脚本、选择 Python、安装 wbot、运行当前文件、调用 Python Debugger，以及网页元素抓取、管理、校验和代码插入。新增自动化项目初始化和本地发布包构建，可直接发布到 Assistant 或 OC，使用说明见源码仓库的 `docs/assistant.md`。默认普通脚本演示文本替换与日志，无需启动浏览器。

## 0.7 开发、元素与发布

- 元素库单击打开只读详情；复制 XPath 使用行内复制按钮或右键菜单，浏览不会改变剪贴板。
- 新增和编辑使用一个紧凑表单，集中填写名称、分组、XPath、页面与描述；保存失败保留草稿。
- 共享仓库侧栏持续显示仓库、分支、申请状态和本地修改；可见时每 15 秒更新，也可手动刷新。连接异常保留上次数据并明确提示，写入前仍会重新校验状态。
- 点击变更元素打开该元素的原生 Diff；“查看本地差异”也可选择完整快照。侧栏仓库图标根据当前状态提供下一步操作，详细 JSON 保留为诊断入口。
- 欢迎内容按浏览器服务是否连接区分准备环境和添加元素；进度通知说明正在读取、提交还是拉取。

## 安装与首次使用

1. 在 VS Code 的扩展面板菜单中选择 **从 VSIX 安装**，选择 `wbot-studio-0.7.1.vsix`。本版通过 VSIX 分发，未发布到 Marketplace。
2. 打开本机项目文件夹，并将工作区设为受信任。需要 VS Code **1.90+** 和 Python **3.10+**。
3. 打开左侧 **WBot**，执行 **选择 Python 解释器**，选择项目环境中的 `python.exe`。留空时依次使用 Microsoft Python 扩展当前解释器、项目 `.venv` 或 PATH 中的 `python`。
4. 执行 **WBot: 将 wbot 安装到所选 Python 环境**，等待终端显示安装成功。VSIX 内置 wbot wheel，安装 `lxml` 依赖可能需要网络。
5. 执行 **WBot: 新建 Python 自动化脚本**，保存为 `.py`。点击 Python 编辑器右上角的运行按钮，或执行 **WBot: 运行当前 Python 脚本**，终端会输出 `您好，WBot`。

也可将 `examples/code-demo.py` 复制到自己的工作区。它使用 `wbot.strings` 和 `wbot.logging`，不依赖网页或已有元素库。

## Python 运行与断点调试

自动化逻辑直接使用 Python 的变量、条件、循环、函数和模块。运行前会保存当前文件，脚本以其所属工作区文件夹为当前目录，输出显示在集成终端；可通过终端停止任务。运行任务通过 VS Code 的 ProcessExecution 传入解释器和参数。

代码调试使用 **Microsoft Python Debugger**（扩展 ID：`ms-python.debugpy`）：

1. 在 VS Code 中安装 Python Debugger，打开已保存的 `.py` 文件。
2. 点击代码行号左侧设置断点。可先在 `code-demo.py` 的 `message = strings.replace(...)` 行设置断点。
3. 执行 **WBot: 调试当前 Python 脚本**。WBot 将当前文件、所选 Python、工作目录和 `wbot.scriptArgs` 交给 Python Debugger。
4. 命中断点后，在 VS Code 的“运行和调试”中查看变量、监视表达式和调用栈；使用调试工具栏的单步跳过、单步进入、继续和停止。

在示例的文本替换行暂停时，`message` 为 `你好，WBot`；执行这一行后变为 `您好，WBot`。代码断点与单步由 Python Debugger 处理。

从旧版升级后，扩展不再接管 `.wbot.json`；已有文件可作为普通 JSON 查看，旧流程的断点不会自动转换为 Python 断点。

## 自动化项目与发布包

1. 执行 **WBot: 初始化自动化项目**，选择父目录并填写项目名称。命令创建新目录及 `wbot.json`、`main.py`，不会覆盖已有目录；完成后可选择“添加到工作区”。
2. 编辑 `main.py` 和 `wbot.json`，声明入口、版本、文件白名单、输入参数及精确依赖。项目名使用英文字母或数字开头，只包含英文字母、数字、`_`、`-`，最多 80 位。
3. 执行 **WBot: 构建自动化发布包**。命令先保存编辑内容；多工作区时使用当前编辑文件所属项目，没有对应项目时让你选择。
4. 构建结果保存在项目 `dist/<name>-<version>.wbot.zip`，可点击提示在文件管理器中显示。相同输出不会覆盖；更改发布内容后先提高版本。
5. 执行 **WBot: 发布自动化到 Assistant / OC**，选择目标。可构建当前项目或选择已有发布包；重试时选择同一个包，内容有变化先提高版本。Assistant 收到后出现在“我的自动化”；OC 收到后进入自动化包仓库。发布不会自动运行或创建流程部署。

这两个命令使用选定的 Python 和扩展内的包工具，不依赖浏览器服务运行。`wbot.json` 是新的项目清单，与旧版 `.wbot.json` 流程文件不同。

初始化入口使用 `wbot.runtime.parameters()` 和 `runtime.set_result()`，需要 Assistant 提供运行上下文；请通过“构建 → 发布 → 在 Assistant 运行”验证该示例。现有“运行当前 Python 脚本”和 Python Debugger 不会自动注入这一上下文，普通脚本运行调试继续保持原有行为。

元素资产需要显式导出为 `wbot-elements` JSON，列入清单的 `files` 并填写 `elements` 路径。发布脚本应使用 `selector.SelectorStore()` 读取 Assistant 提供的任务元素库；从旧代码插入模板得到的个人绝对路径需移除，避免继续访问开发机全局库。清单完整示例、命令行用法、依赖与运行限制见源码仓库的 `docs/assistant.md`。

## 网页自动化与元素抓取

仅处理文本、文件等任务时，可直接运行 Python。需要操作已打开的 Chrome / Edge 网页时，再准备浏览器桥：

1. 点击 WBot 侧栏的插头图标，执行 **启动 / 连接浏览器服务**。
2. 执行 **WBot: 准备浏览器扩展目录**。目录会复制到剪贴板并在文件管理器中打开。
3. 进入 `chrome://extensions` 或 `edge://extensions`，开启开发者模式，选择 **加载已解压的扩展程序**，加载上述目录，再刷新目标网页。
4. 在 WBot 侧栏点击 **抓取元素**。切换到网页，悬停选择元素，`Ctrl + 左键` 锁定，`Enter` 确认；回到 VS Code 填写名称、分组、XPath、页面 URL 和描述。
5. 在元素条目上点击代码图标，向当前 Python 文件插入调用代码。根据任务补上点击、输入或读取文本等操作。

浏览器扩展首次加载需在浏览器管理页面完成。已有 XPath Studio 1.4.0 浏览器扩展且连接地址一致时可以继续使用；更新后重新加载扩展并刷新网页。VS Code 扩展独立启动本机桥服务，使用时无需打开桌面应用。

## 元素库与代码片段

- 按组展示、搜索、新增、编辑、删除；单击元素复制 XPath，代码图标插入调用代码。
- 支持 `wbot-elements` JSON 导入 / 导出；导入同名记录时可选择停止、跳过或替换。
- 默认数据库为 `~/.xpath_studio/elements.sqlite3`，与 `wbot.ElementLibrary()` 共用。通过 `wbot.libraryPath` 可指定另一个绝对路径。
- **校验并高亮**使用最近抓取结果的浏览器、标签页、框架和文档身份；更换页面或导航后请重新抓取，跨域 iframe 的 XPath 只在对应框架内有效。
- 插入的代码带有服务地址和元素库路径；移到其他机器时需调整这些参数。

```python
from wbot import web, selector

browser = web.get(base_url="http://127.0.0.1:8790")
elements = selector.SelectorStore()
element = browser.find(elements.get("搜索框", group="首页"), timeout=10)
element.input("wbot")
```

运行前先在目标页面抓取并保存“首页”分组下的“搜索框”。在 Python 编辑器中输入 `wbot-connect`、`wbot-element` 或 `wbot-browser` 可以使用代码片段。

安装命令只安装 wbot 核心与 `lxml`。Excel 和独立 Playwright 浏览器功能需要在同一 Python 环境中额外安装 `openpyxl`、`playwright`；使用 Playwright 自带浏览器时还需安装相应浏览器。文件、文件夹、文本、正则、JSON、CSV、ZIP、HTTP、日志与进程等模块可直接通过 Python 调用。

## 共享元素仓库、版本与合并

共享元素入口位于 WBot 元素库标题栏的菜单，也可在命令面板执行 **WBot: 共享元素仓库**。它复用当前 `wbot.libraryPath` 指向的元素库；元素的抓取、编辑和校验仍使用原有操作。

先启动包含共享元素接口的新版 Assistant，在其连接设置中填写 OC 地址并由管理员批准设备绑定。OC 管理员在“共享元素”创建仓库。插件通过 Assistant 本机会话访问共享仓库，远端设备密钥只由 Assistant 持有。若使用独立预览数据目录，将 `wbot.assistantStateDir` 指向该目录；不需要在插件中重复填写 OC 地址或密钥。

1. 执行 **连接共享元素仓库 / 创建分支**，选择仓库并填写个人分支名称。共享主分支中本地缺少的元素会加入当前库；已有相同 ID 的元素保留本地内容，作为待提交修改。不同 ID 的同分组同名元素会导致操作停止，需要先处理冲突。
2. 通过现有元素库编辑或抓取 XPath，执行 **查看共享元素本地差异**。VS Code 只读差异编辑器对比最近提交与本地元素，涵盖名称、分组、XPath、URL、框架和描述。
3. 执行 **提交共享元素版本** 并填写说明。版本保存在个人分支，不直接改变共享主分支。
4. 执行 **发起元素合并申请**，填写标题、修改原因和验证说明。OC 管理员查看差异、处理冲突并合并，或关闭申请。已有打开的申请会跟随后续提交更新。
5. 执行 **查看共享元素与合并状态** 查看结果。申请合并后，且本地没有未提交修改时，可执行 **拉取共享元素主分支**。继续开发前再创建新的个人分支。如果合并后已继续编辑本地元素，可以直接在同一仓库创建新分支，系统会结合上次基准、最新主分支和本地内容整合修改；同一字段存在冲突时停止并保留本地内容。

当前支持受保护的共享主分支与设备拥有的个人分支；不提供任意 Git 远程仓库、命令行 Git 协议或个人账户权限。分支及提交归属于已批准设备，设备名称不是经过验证的用户身份。主分支变化不会自动覆盖本地库，也不会改变已经构建的自动化发布包。

操作会校验审阅时的分支头和本地内容指纹。输入说明期间若元素或分支发生变化，请重新查看差异后重试。网络写入不会自动重放；如果返回超时，先查看状态，Assistant 会读取 OC 已接受操作的回执来恢复本机记录。相同参数的手动重试复用请求身份，Assistant 也会持久化待确认操作。离线时可查看本地差异，提交和申请需要恢复连接。

拉取仅用于已经合并的个人分支；未合并的分支或本地未提交改动会阻止拉取。已合并分支上的新修改可通过同仓库新分支继续提交；切换到其他仓库仍须先处理未提交修改。也可导出 JSON 保留本地内容后再明确处理工作副本，不提供强制覆盖入口。

## 配置

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `wbot.pythonPath` | 空 | Python 可执行文件路径，不含参数 |
| `wbot.bridgeUrl` | `http://127.0.0.1:8790` | 仅支持本机 HTTP 服务 |
| `wbot.libraryPath` | 空 | 空值使用默认元素库；否则须为绝对路径 |
| `wbot.assistantStateDir` | 空 | 共享元素使用的 Assistant 数据目录；空值为 `~/.wbot-assistant`，支持 `~/` 路径 |
| `wbot.scriptArgs` | `[]` | 运行 / 调试脚本的字符串参数数组 |

修改服务端口、解释器或数据库路径后，请停止本扩展的服务，再启动。修改端口后还需重新执行 **准备浏览器扩展目录**，并在浏览器中重新加载扩展。

已有 XPath Studio 1.4.0 服务时会复用它，`wbot.libraryPath` 应与外部服务实际使用的数据库一致。**停止本扩展启动的服务**只关闭本扩展创建的子进程；VS Code 退出时也会关闭该子进程。

## 故障处理与范围

- 运行报 `No module named wbot`：确认 **选择 Python 解释器** 与安装 wbot 时使用的是同一个环境。
- 调试提示缺少扩展：安装 Microsoft Python Debugger（`ms-python.debugpy`）。
- 服务启动失败：检查 **输出 → WBot**，确认 Python 中已有 wbot / lxml、端口可用。
- 没有浏览器连接：确认浏览器扩展已启用、地址和端口一致，刷新普通 HTTP/HTTPS 网页；浏览器内部页面不能抓取。
- 抓取后暂不显示：点击侧栏刷新；外部修改数据库后也需要刷新。
- 仅支持本机可信工作区；不支持 Remote SSH、WSL、Dev Container 和虚拟工作区。
- 本版提供 Python 编码与网页元素辅助能力；wbot 各模块的范围见仓库 `docs/wbot.md`，不包含桌面 UIA 抓取。

## 从源码构建与验证

先在仓库根目录创建 Python 环境、安装 wbot 并构建 wheel，再构建扩展：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m pip wheel . --no-deps -w dist/wbot
$env:WBOT_TEST_PYTHON = (Resolve-Path .\.venv\Scripts\python.exe).Path
cd vscode-extension
npm ci
npm run prepare-runtime
npm test
npm run package
& $env:WBOT_TEST_PYTHON -X utf8 scripts/verify-package.py
```

产物为仓库 `dist/wbot-studio-0.7.1.vsix`。`runtime/` 从当前项目准备；VSIX 包含项目包工具、浏览器桥、抓取扩展、wbot 及其 wheel，不包含桌面工作台页面、可视化流程编辑器或 Node 开发依赖。Assistant 界面仍按源码仓库的 `docs/assistant.md` 启动；VSIX 不作为 Assistant 桌面安装包。

`npm test` 运行编码版与桥服务回归。扩展宿主集成测试使用隔离的用户数据和扩展目录，入口为 `test/integration.js`；可从当前扩展目录执行：

```powershell
& $env:WBOT_TEST_PYTHON -X utf8 scripts/test-host.py --code "你的 VS Code 可执行文件绝对路径"
```

要验证真实 Python 调试，可在上述命令末尾加上 `--debugger-extension "本机 ms-python.debugpy 扩展目录"`。测试会在隔离环境中使用指定扩展；未提供时，报告会将真实调试项标记为未验证。

## 许可

本项目采用 MIT 许可证，见扩展包内的 `LICENSE.txt` 或源码中的 `LICENSE`。


## SDK 提示与项目元素

安装 Microsoft Python / Pylance，并选中安装了 wbot 的解释器。内置 wbot 0.1.1 带有 `py.typed`、选择器和运行上下文类型信息；模块提示、函数签名和文档由 Python 语言服务提供。未来的 wbot_oc Python 客户端安装到同一解释器后沿用这条机制；当前不生成尚未存在的 API。

`elements = selector.SelectorStore()` 后输入 `elements.get("` 可获得元素名提示，`group="` 可获得分组提示。优先读取当前项目 `wbot.json` 声明的 JSON 快照，未声明时使用已加载的本地元素库。共享仓库仍在“共享与版本”提供分支、提交和合并操作。

发布前执行 **WBot: 将元素加入项目快照**，勾选所需元素。命令创建新 JSON 并写入清单 `files` / `elements`，不会覆盖现有快照。构建校验 XPath 并移除临时浏览器标识。新插入的代码使用 `SelectorStore()`，由运行环境提供元素库路径。

## 发布认证与回执

- Assistant：从 `wbot.assistantStateDir` 读取本机会话，只访问回环地址；通过已有包安装接口交付，任务托管仍由 Assistant 负责。
- OC：设置 `wbot.ocUrl` 或在发布时输入 HTTPS 地址，使用具有 `packages.manage` 权限的开发者账号登录。密码只用于本次发布，完成后退出会话；不借用 Robot 设备授权。仅本机测试允许 HTTP。
- 回执中的包名、版本、标识匹配后才标为成功。网络异常显示“未确认”，先核对目标包列表；不会自动重放上传。
- **WBot: 查看发布记录** 保存最近 100 次的目标、版本、产物路径和回执，不保存密码、Cookie 或设备凭据。
- 发布到 OC 后，由管理端选择 Robot / Environment 部署流程并配置任务调度。发布、部署、运行是三个独立操作。
