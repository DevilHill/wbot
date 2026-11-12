# WBot 的 VS Code Marketplace 发布

正式 Publisher ID：`marswei`。扩展标识：`marswei.wbot-studio`。

## 首次创建发布者

1. 用自己的 Microsoft 账号登录 https://marketplace.visualstudio.com/manage 。
2. 点击 Create publisher，填写 Publisher ID 与显示名称。建议显示名称为 WBot；ID 以实际可注册的结果为准。ID 创建后不能修改。
3. 将实际 ID 写入 `vscode-extension/package.json` 的 `publisher`。本地测试用的 `xpath-studio-local` 不能直接当作自己的市场账号使用。
4. 在扩展目录运行 `npm run package:marketplace`。构建先生成 SDK 运行资源，输出 Windows x64 的 VSIX；不覆盖已经存在的同版本产物。
5. 在管理页选择 New extension → Visual Studio Code，上传经校验的 VSIX，等待平台验证完成，再核对公开商品页。

## GitHub Actions Trusted Publishing

官方说明：https://code.visualstudio.com/api/working-with-extensions/publishing-extension

仓库包含 `.github/workflows/publish-vscode.yml`，只允许在 main 分支手动运行，并要求输入与 package.json 一致的版本。普通 push 不会发布市场版本。

在 Marketplace 的 Publisher 管理页选择 Trusted Publishing，创建如下策略：

| 字段 | 值 |
| --- | --- |
| Policy name | WBot VS Code release |
| Repository owner | DevilHill |
| Repository | wbot |
| Workflow | publish-vscode.yml |
| Environment | 留空 |

这条策略允许指定仓库的指定 workflow 以该 Publisher 的身份发布。创建策略后，进入 GitHub Actions，选择 Publish VS Code extension → Run workflow，选择 main 并填写准确版本。无需向聊天或仓库提供 PAT。

流程会安装锁定版本的发布工具，构建 wheel、运行插件回归、生成并逐字节校验 VSIX、保存构建产物，然后使用 `vsce publish --oidc --packagePath` 发布同一产物。若发布或验证失败，检查工作流日志；不要自动增加版本绕过错误。下一次正式发布须提高版本号。

## 本地准备

```powershell
python -m pip wheel . --no-deps --wheel-dir dist/wbot
cd vscode-extension
npm ci
npm run package:marketplace
```

发布工具会阻止 `*-local` 的 Publisher 和缺少商店元数据的包。首次上架前确认：真实 Publisher ID、Windows x64 平台、Assistant 0.9.0+ 的获取方式、README 链接及包内资源。Assistant 是单独的桌面软件，插件不会把它一起安装。

原先安装 `xpath-studio-local.wbot-studio` 的本地用户需要在正式市场插件可用后卸载测试版，再安装正式版，避免两个身份同时激活。
