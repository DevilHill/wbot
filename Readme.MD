# WBot 编码版

在 **VS Code 中编写 Python 自动化脚本**：使用 `wbot` 操作网页、管理元素库，并处理文件、文本、HTTP、ZIP 和 Excel。配套 **WBot Studio 0.4.0** 提供新建脚本、运行、调试、网页元素抓取和调用代码插入。

- 自动化逻辑直接写在 `.py` 文件中，使用 Python 的函数、条件、循环和模块。
- 通过 Microsoft Python Debugger 设置代码断点、单步执行、查看变量和调用栈。
- 元素库支持分组、搜索、编辑、导入导出，以及在抓取页面校验 XPath。

[VS Code 安装与使用](vscode-extension/README.md) · [wbot Python API 与范围](docs/wbot.md) · [浏览器扩展说明](extension/README.md)

## 获取代码

```powershell
git clone https://github.com/DevilHill/xpath_tool.git
cd xpath_tool
```

## 环境

- Windows；[Python 3.10+](https://www.python.org/downloads/)，推荐 3.13。核心依赖 `lxml`，安装 wbot 时自动安装。
- [VS Code 1.90+](https://code.visualstudio.com/) 用于安装 WBot Studio；代码调试还需要 **Microsoft Python Debugger**（`ms-python.debugpy`）。独立运行 Python 库不需要 VS Code。
- Chrome / Edge 和配套浏览器扩展用于抓取元素、连接已有网页；纯文件与文本脚本无需浏览器。
- [Git 2.x](https://git-scm.com/downloads/) 用于克隆；[Node.js 22](https://nodejs.org/en/download) 和 npm 用于构建、测试 VS Code 扩展。

## 安装与试运行

在仓库根目录创建 Python 环境并安装库：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -X utf8 vscode-extension/examples/code-demo.py
```

示例无需连接浏览器，会在日志中输出 `您好，WBot`。核心代码如下：

```python
from wbot import logging, strings

logging.configure()
message = "你好，WBot"
message = strings.replace(message, "你好", "您好")
logging.info(message)
```

需要 Excel 或独立 Playwright 浏览器时，安装相应可选依赖，见 [wbot 文档](docs/wbot.md)。

### 在 VS Code 中编码与调试

1. 通过扩展面板的 **从 VSIX 安装** 安装 `wbot-studio-0.4.0.vsix`，然后打开本机项目文件夹并信任工作区。安装包可按下文从源码构建。
2. 执行 **WBot: 选择 Python 解释器**，选中项目 `.venv` 中的 Python。尚未安装库时，执行 **WBot: 将 wbot 安装到所选 Python 环境**。
3. 执行 **WBot: 新建 Python 自动化脚本**，保存为 `.py`。默认模板可直接运行；也可打开 [code-demo.py](vscode-extension/examples/code-demo.py)。
4. 点击 Python 编辑器右上角的运行按钮，在集成终端查看输出。
5. 安装 Microsoft Python Debugger，在替换文本的代码行左侧设置断点，再执行 **WBot: 调试当前 Python 脚本**。暂停后使用 VS Code 的单步、继续、变量和调用栈工具。

升级到 0.4.0 后，扩展不再接管 `.wbot.json`，这些文件作为普通 JSON 打开。旧流程里的断点不会自动转换成 Python 代码断点。

### 网页自动化与元素库

1. 执行 **WBot: 启动 / 连接浏览器服务**，再执行 **WBot: 准备浏览器扩展目录**。
2. 在 `chrome://extensions` 或 `edge://extensions` 开启开发者模式，加载已复制的扩展目录，然后刷新目标网页。
3. 在 WBot 侧栏点击 **抓取元素**，切换到网页，`Ctrl+左键` 锁定、`Enter` 确认，回到 VS Code 保存元素名称和分组。
4. 点击元素条目的代码图标，将调用插入当前 Python 文件；也可通过元素菜单复制 XPath 或校验并高亮。

```python
from wbot import web, selector

browser = web.get(base_url="http://127.0.0.1:8790")
elements = selector.SelectorStore()
search = browser.find(elements.get("搜索框", group="首页"), timeout=5)
search.input("wbot")
```

以上代码需要先在目标网页抓取并保存名为“搜索框”、分组为“首页”的元素。浏览器桥只监听本机，默认端口 `8790`；代码中的地址应与 VS Code 的 `wbot.bridgeUrl` 一致。刷新、导航或切换抓取目标后应重新抓取；iframe 内的定位器仅在相应框架有效。

元素库默认保存在 `~/.xpath_studio/elements.sqlite3`，也可以直接使用 `wbot.ElementLibrary` API。更多示例和兼容范围见 [wbot 文档](docs/wbot.md)。

## 构建与测试

在仓库根目录执行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip wheel . --no-deps -w dist/wbot
$env:WBOT_TEST_PYTHON = (Resolve-Path .\.venv\Scripts\python.exe).Path
cd vscode-extension
npm ci
npm run prepare-runtime
npm test
npm run package
& $env:WBOT_TEST_PYTHON -X utf8 scripts/verify-package.py
```

产物为 `dist/wbot/wbot-0.1.0-py3-none-any.whl` 和 `dist/wbot-studio-0.4.0.vsix`。打包脚本从当前源码准备浏览器桥、浏览器扩展与 wbot 运行资源；VSIX 不包含可视化流程编辑器或桌面工作台页面。产物不提交到 Git，未配置自动发布。

VS Code 宿主测试、配置和故障排查见 [扩展指南](vscode-extension/README.md)。网页联动验证脚本位于 [tools/](tools/)；独立浏览器等可选测试需要对应依赖。

仓库中的 `app/` 与 `extension/` 保留共享浏览器服务、定位引擎和抓取能力。编码版由 VS Code 启动桥服务，使用时无需打开桌面应用。

## 贡献与许可

通过 [Issues](https://github.com/DevilHill/xpath_tool/issues) 报告问题，附复现步骤和脱敏日志。PR 请说明改动与验证结果；定位算法改动需保持 Python / JavaScript 两端一致。

wbot 是独立实现的 Python 库，支持范围以 [模块说明](docs/wbot.md#模块与兼容范围) 为准，不声称完整兼容 xbot。

本项目采用 [MIT 许可证](LICENSE)。
