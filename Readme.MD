# WBot Studio 编码版

独立的 Python 自动化编码桌面：**文件树、多标签、Monaco 编辑器、保存、运行/停止、实时日志**。抓取浏览器元素后，可将 XPath 插入代码，并在右侧工作台校验、同步高亮。

- 行号、语法高亮、折叠、查找替换、基础补全与 wbot 代码片段。
- 新建/打开本机项目；保存时检测磁盘改动，避免覆盖外部修改。
- 打包 EXE 内置 Python 与 wbot 基础运行环境；编辑器资源离线使用。
- 保留元素库、抓取元素与 iframe 内的 XPath 校验。

[编码界面](docs/images/studio-code.png) · [wbot API](docs/wbot.md) · [浏览器扩展](extension/README.md)

## 获取代码

```powershell
git clone https://github.com/DevilHill/xpath_tool.git
cd xpath_tool
```

## 环境

- Windows，推荐 [Python 3.13](https://www.python.org/downloads/)。
- 原生窗口使用 [WebView2 Runtime](https://developer.microsoft.com/en-us/microsoft-edge/webview2/)。
- Chrome / Edge 与配套扩展用于网页抓取；纯 Python 脚本无需浏览器。

## 启动与使用

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

## 构建与测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe build.py --distpath dist/1.5.0
.\.venv\Scripts\python.exe tools/verify_exe.py --exe dist/1.5.0/XPathStudio.exe
.\.venv\Scripts\python.exe tools/verify_studio_exe.py --exe dist/1.5.0/XPathStudio.exe
```

产物为 `dist/1.5.0/XPathStudio.exe`；修改界面后需重新打包。浏览器扩展可用 `tools/pack_extension.py` 打包，VS Code 扩展构建见其指南。

Monaco 固定为 **0.57.0**，资源及许可证位于 [vendor/monaco](app/web/vendor/monaco/)。需要重取资源时运行 `tools/vendor_monaco.py`，脚本核对 npm SHA-512，不执行安装脚本。

## 贡献与许可

通过 [Issues](https://github.com/DevilHill/xpath_tool/issues) 提交问题，附复现步骤和脱敏日志。PR 请说明验证结果；定位规则应保持 Python / JavaScript 两端一致。

本项目采用 [MIT 许可证](LICENSE)。wbot 为独立实现，不声称完整兼容 xbot。Monaco 的第三方许可见其 [LICENSE](app/web/vendor/monaco/LICENSE) 和 [ThirdPartyNotices.txt](app/web/vendor/monaco/ThirdPartyNotices.txt)。
