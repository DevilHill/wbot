# WBot 开发工具

**WBot 开发工具 0.11.0** 用于编写和运行 `wbot` Python 自动化脚本：直接编辑 `.py` 文件，使用 VS Code 的代码调试工具，并从元素库插入网页操作代码。共享元素仓库支持个人分支、版本提交和向 OC 发起合并申请。

支持新建脚本、选择 Python、安装 wbot、运行当前文件、调用 Python Debugger，以及网页元素抓取、管理、校验和代码插入。新增自动化项目初始化和本地发布包构建，可直接发布到 Assistant 或 OC，使用说明见[Assistant 使用说明](https://github.com/DevilHill/wbot/blob/main/docs/assistant.md)。默认普通脚本演示文本替换与日志，无需启动浏览器。

## 环境要求

- 当前完整产品面向 Windows x64，本机 VS Code 1.90+，项目 Python 3.10+。
- 元素库、抓取与定位需要单独运行 Assistant 0.9.0+，不需要配置 OC 即可使用本地元素功能。
- Python 提示使用 Microsoft Python / Pylance；调试需 Microsoft Python Debugger。
- [Assistant 获取与使用说明](https://github.com/DevilHill/wbot/blob/main/docs/assistant.md) · [问题反馈](https://github.com/DevilHill/wbot/issues)

## 连接 Assistant 和 OC

WBot 侧栏的“连接”只包含两个入口：

- **本机 Assistant**：打开 Assistant 后，插件自动检查运行进程、本机会话和产品身份，并在约 10 秒内显示已连接；无需填写 URL、端口或数据目录。Windows 支持从进程发现自定义数据目录。同一台电脑存在多个实例时，点击这一项选择要使用的实例。失联会显示未运行，重启原实例后自动恢复。
- **OC 平台**：直接读取当前 Assistant 的 OC 绑定状态。Assistant 离线时显示离线并提示启动；未绑定时点击这一项，按“OC 地址 → 设备名称 → 接入 Key”提交给 Assistant。待审批、已批准、拒绝、撤销和连接错误会自动更新。已有绑定重连可留空 Key。

OC 连接与 Assistant 绑定一致，不另建插件账号连接。Key 只提交给本机 Assistant，不写入插件设置或发布记录；OC 管理员核对并批准设备后，共享元素功能复用这条连接。点击 OC 项可查看确认码、打开平台、重新绑定或明确断开；断开会影响使用同一 Assistant 的其他工具。

发布到 OC 时目标地址来自 Assistant 的已批准绑定。上传自动化包仍按 OC 现有权限要求验证开发者账号；该发布授权只用于当次上传，不建立独立的插件连接，不保存密码。

元素库、浏览器连接、抓取、XPath 校验与高亮统一由 Assistant 0.9.0 或更新版本提供。插件不再启动 Python 浏览器服务；Assistant 离线时显示启动提示。开发者 Python 仅用于项目构建、脚本运行与调试。设置页只保留 Python 解释器和脚本参数。

升级时同时更新 Assistant 与插件，并重新加载 VS Code，释放旧插件占用的 8790 端口。 Assistant 仅关闭窗口不会停止后台；先等待任务结束并从托盘退出旧界面，再在新版程序目录执行 `WBotAssistant.exe stop`、`WBotAssistant.exe open`，完成后台版本切换。默认继续使用 `~/.xpath_studio/elements.sqlite3`。原先使用自定义库的用户可通过旧版导出 JSON 后导入，或在启动 Assistant 时设置 `WBOT_ELEMENT_LIBRARY` 为原库路径；插件的旧 `bridgeUrl` / `libraryPath` 配置不再控制服务。

## 0.7 开发、元素与发布

- 元素库单击打开只读详情；复制 XPath 使用行内复制按钮或右键菜单，浏览不会改变剪贴板。
- 新增和编辑使用一个紧凑表单，集中填写名称、分组、XPath、页面与描述；保存失败保留草稿。
- 共享仓库侧栏持续显示仓库、分支、申请状态和本地修改；可见时每 15 秒更新，也可手动刷新。连接异常保留上次数据并明确提示，写入前仍会重新校验状态。
- 点击变更元素打开该元素的原生 Diff；“查看本地差异”也可选择完整快照。侧栏仓库图标根据当前状态提供下一步操作，详细 JSON 保留为诊断入口。
- 欢迎内容按本地元素库是否就绪区分准备环境和添加元素；进度通知说明正在读取、提交还是拉取。

## 安装与首次使用

1. 在 VS Code 的扩展面板菜单中选择 **从 VSIX 安装**，选择 `wbot-studio-0.11.0.vsix`。正式 Marketplace 版本与本地测试版属于不同扩展身份，请避免同时启用。
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

1. 执行 **WBot: 新建自动化项目（含虚拟环境）**，选择父目录、填写项目名称，并选择 Python 3.10+ 作为基础解释器。命令创建项目专属 `.venv`，安装扩展内置 WBot SDK 及 `lxml`，完成后可在新窗口打开。基础 Python 无需预装 WBot，也不会被安装业务依赖；获取 `lxml` 可能需要网络。
2. 编辑 `main.py` 和 `wbot.json`，声明入口、版本、文件白名单、输入参数及精确依赖。项目名使用英文字母或数字开头，只包含英文字母、数字、`_`、`-`，最多 80 位。
3. 从 0.11.0 起，执行 **WBot: 构建自动化发布包** 会使用项目 `.venv` 中的 Python，将业务代码、独立 Python 和现有依赖构建为 Windows x64 完整环境包。命令先保存编辑内容；多工作区时使用当前编辑文件所属项目，没有对应项目时让你选择。构建不安装依赖；缺少依赖时先在开发端准备。
4. 构建结果保存在项目 `dist/<name>-<version>.wbot.zip`，可点击提示在文件管理器中显示。相同输出不会覆盖；更改发布内容后先提高版本。
5. 执行 **WBot: 发布自动化到 Assistant / OC**，选择目标。可构建当前项目或选择已有发布包；重试时选择同一个包，内容有变化先提高版本。Assistant 收到后校验并解压包内环境，出现在“我的自动化”；OC 收到后进入自动化包仓库。发布不会自动运行或创建流程部署。完整环境包需要 Assistant 0.11.0 及支持 schemaVersion=2 的 OC；也可将 ZIP 复制到目标电脑后离线导入。Assistant 不创建环境、不安装依赖。

项目创建和构建均不需要连接 Assistant。`wbot.json` 是项目清单，与旧版 `.wbot.json` 流程文件不同。新建项目保留 `wbot.initProject` 命令 ID，旧快捷入口仍可使用。

新项目包含：

```text
my-automation/
├─ main.py                 # 本地可运行的示例入口
├─ wbot.json               # 发布清单、参数、精确依赖
├─ requirements.txt        # 安装完成后记录的依赖版本
├─ .venv/                  # 仅属于本项目的虚拟环境
├─ .wbot/wheels/           # 内置 WBot SDK，便于重建环境
├─ .vscode/                # 解释器配置与断点调试配置
├─ data/                   # 输入资料
├─ output/                 # 运行输出，不提交到 Git
├─ .gitignore
└─ README.md
```

示例在本地直接运行时使用默认参数；有 Assistant 运行上下文时调用 `runtime.parameters()` 和 `runtime.set_result()`。项目配置让 WBot 的运行/调试命令使用本项目 `.venv`；断点调试需 Microsoft Python Debugger。

已有目录不会被覆盖。创建失败时不显示就绪提示，保留已创建内容并显示失败阶段，详细安装日志位于“输出 → WBot”。可按生成的 README 修复环境，或选择新的项目目录重建。新增依赖后应同步维护 `requirements.txt` 与清单中的精确依赖；初始锁定只反映创建时安装的版本。

Studio 0.11.0 会将项目环境转换为独立 Python 发布包，由 Assistant 0.11.0 校验、解压和托管。普通 `.venv` 仍只用于开发，不应直接复制到其他电脑；Assistant 不创建环境或安装依赖。

元素资产需要显式导出为 `wbot-elements` JSON，列入清单的 `files` 并填写 `elements` 路径。发布脚本应使用 `selector.SelectorStore()` 读取 Assistant 提供的任务元素库；从旧代码插入模板得到的个人绝对路径需移除，避免继续访问开发机全局库。清单完整示例、命令行用法、依赖与运行限制见[Assistant 使用说明](https://github.com/DevilHill/wbot/blob/main/docs/assistant.md)。

## 网页自动化与元素抓取

仅处理文本、文件等任务时，可直接运行 Python。需要操作已打开的 Chrome / Edge 网页时，再准备浏览器桥：

1. 打开 Assistant 0.9.0 或更新版本，再打开 WBot 元素库，插件自动连接，无需选择 Python 来启动服务。
2. 执行 **WBot: 准备浏览器扩展目录**。目录会复制到剪贴板并在文件管理器中打开。
3. 进入 `chrome://extensions` 或 `edge://extensions`，开启开发者模式，选择 **加载已解压的扩展程序**，加载上述目录，再刷新目标网页。
4. 在 WBot 侧栏点击 **抓取元素**。切换到网页，悬停选择元素，`Ctrl + 左键` 锁定，`Enter` 确认；回到 VS Code 填写名称、分组、XPath、页面 URL 和描述。
5. 在元素条目上点击代码图标，向当前 Python 文件插入调用代码。根据任务补上点击、输入或读取文本等操作。

浏览器扩展首次加载需在浏览器管理页面完成。已有 XPath Studio 1.4.0 浏览器扩展且连接地址一致时可以继续使用；更新后重新加载扩展并刷新网页。浏览器桥由 Assistant 后台持有，关闭 VS Code 后仍可使用；停止 Assistant 后台后抓取和定位不可用。

## 元素库与代码片段

- 按组展示、搜索、新增、编辑、删除；单击查看详情，复制按钮复制 XPath，代码图标插入调用代码。
- 支持 `wbot-elements` JSON 导入 / 导出；导入同名记录时可选择停止、跳过或替换。
- 默认数据库为 `~/.xpath_studio/elements.sqlite3`，与 `wbot.ElementLibrary()` 共用。数据库路径由 Assistant 返回，插件统一使用该元素库。
- **校验并高亮**使用最近抓取结果的浏览器、标签页、框架和文档身份；更换页面或导航后请重新抓取，跨域 iframe 的 XPath 只在对应框架内有效。
- 插入代码使用 Assistant 的浏览器地址，元素库路径由运行环境提供。

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

共享元素入口位于 WBot 元素库标题栏的菜单，也可在命令面板执行 **WBot: 共享元素仓库**。它复用当前本地元素库；元素的抓取、编辑和校验仍使用原有操作。

先启动包含共享元素接口的新版 Assistant，在其连接设置中填写 OC 地址和接入 Key，再由管理员批准设备绑定。OC 管理员在“共享元素”创建仓库。插件通过 Assistant 本机会话访问共享仓库，远端设备密钥只由 Assistant 持有。Windows 下独立预览实例会通过运行进程被发现，在“本机 Assistant”选择即可，无需填写目录。

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
| `wbot.scriptArgs` | `[]` | 运行 / 调试脚本的字符串参数数组 |

元素服务随 Assistant 后台运行；退出 VS Code 不会停止 Assistant 或浏览器桥。

## 故障处理与范围

- 运行报 `No module named wbot`：确认 **选择 Python 解释器** 与安装 wbot 时使用的是同一个环境。
- 调试提示缺少扩展：安装 Microsoft Python Debugger（`ms-python.debugpy`）。
- 元素服务不可用：确认 Assistant 已升级到 0.9.0 并重启后台；端口被占用时先重新加载旧版 VS Code 窗口，释放旧插件持有的服务。查看 **输出 → WBot** 获取具体原因。
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

产物为仓库 `dist/wbot-studio-0.11.0.vsix`。`runtime/` 从当前项目准备；VSIX 包含项目构建工具、wbot 及其 wheel；浏览器桥与抓取扩展由 Assistant 提供，不包含桌面工作台页面、可视化流程编辑器或 Node 开发依赖。Assistant 界面仍按[Assistant 使用说明](https://github.com/DevilHill/wbot/blob/main/docs/assistant.md) 启动；VSIX 不作为 Assistant 桌面安装包。

`npm test` 运行插件与 Assistant 元素服务通信回归。扩展宿主集成测试使用隔离的用户数据和扩展目录，入口为 `test/integration.js`；可从当前扩展目录执行：

```powershell
& $env:WBOT_TEST_PYTHON -X utf8 scripts/test-host.py --code "你的 VS Code 可执行文件绝对路径"
```

要验证真实 Python 调试，可在上述命令末尾加上 `--debugger-extension "本机 ms-python.debugpy 扩展目录"`。测试会在隔离环境中使用指定扩展；未提供时，报告会将真实调试项标记为未验证。

添加 `--project-setup` 可单独验证“创建项目 → 在新窗口打开 → 使用项目 `.venv` 运行”的完整路径，测试会将隔离配置中的全局 Python 设为无效路径，确认项目配置生效。依赖安装需要可用的软件源；离线测试可提前准备匹配 Python 版本的 `lxml` wheel，并设置 `PIP_NO_INDEX=1`、`PIP_FIND_LINKS` 指向该目录。`npm test` 的完整环境创建用例通过设置 `WBOT_TEST_WHEELS` 启用，配合相同的 pip 环境变量运行。

## 许可

本项目采用 MIT 许可证，见扩展包内的 `LICENSE.txt` 或源码中的 `LICENSE`。


## SDK 提示与项目元素

安装 Microsoft Python / Pylance，并选中安装了 wbot 的解释器。内置 wbot 0.1.1 带有 `py.typed`、选择器和运行上下文类型信息；模块提示、函数签名和文档由 Python 语言服务提供。未来的 wbot_oc Python 客户端安装到同一解释器后沿用这条机制；当前不生成尚未存在的 API。

`elements = selector.SelectorStore()` 后输入 `elements.get("` 可获得元素名提示，`group="` 可获得分组提示。优先读取当前项目 `wbot.json` 声明的 JSON 快照，未声明时使用已加载的本地元素库。共享仓库仍在“共享与版本”提供分支、提交和合并操作。

发布前执行 **WBot: 将元素加入项目快照**，勾选所需元素。命令创建新 JSON 并写入清单 `files` / `elements`，不会覆盖现有快照。构建校验 XPath 并移除临时浏览器标识。新插入的代码使用 `SelectorStore()`，由运行环境提供元素库路径。

## 发布认证与回执

- Assistant：自动发现运行中的本机 Assistant 并读取其会话，只访问回环地址；通过已有包安装接口交付，任务托管仍由 Assistant 负责。
- OC：目标地址跟随 Assistant 的已批准绑定，使用具有 `packages.manage` 权限的开发者账号完成本次上传授权。密码只用于本次发布，完成后退出会话，不保存密码。发布接口要求 HTTPS，仅本机测试允许 HTTP。
- 回执中的包名、版本、标识匹配后才标为成功。网络异常显示“未确认”，先核对目标包列表；不会自动重放上传。
- **WBot: 查看发布记录** 保存最近 100 次的目标、版本、产物路径和回执，不保存密码、Cookie 或设备凭据。
- 发布到 OC 后，由管理端选择 Robot / Environment 部署流程并配置任务调度。发布、部署、运行是三个独立操作。

连接侧栏的「本机 Assistant」行提供 **重新连接** 和 **断开** 按钮，也可点击该行选择操作。断开只暂停此 VS Code 插件的自动连接，Assistant 后台任务和 OC 绑定继续运行；重新打开 VS Code 后仍保持断开，需主动点击重新连接。重连会重新发现服务并刷新元素库与 OC 状态。
