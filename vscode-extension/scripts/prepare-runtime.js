'use strict';
// 编码版打包 Python API、浏览器桥与拾取扩展，不包含桌面工作台。
const fs = require('node:fs');
const path = require('node:path');
const extension = path.resolve(__dirname, '..');
const root = path.dirname(extension), dest = path.join(extension, 'runtime');
const wheel = path.join(root, 'dist/wbot/wbot-0.1.0-py3-none-any.whl');
// 先确认输入存在；生成目录只能位于当前扩展内，拒绝链接到其他目录后清理。
fs.accessSync(wheel);
const extensionReal = fs.realpathSync(extension);
if (path.relative(extension, dest) !== 'runtime') throw new Error('运行资源目录越界');
if (fs.existsSync(dest)) {
  const destReal = fs.realpathSync(dest);
  if (fs.lstatSync(dest).isSymbolicLink() || path.relative(extensionReal, destReal) !== 'runtime') {
    throw new Error('运行资源目录必须是当前扩展内的普通 runtime 目录');
  }
  // 每次从源码重建，避免旧版 flow_runner 或 app/web 遗留进新包。
  fs.rmSync(dest, {recursive:true, force:true});
}
function copyTree(source, target, filter, directoryFilter = () => true) {
  fs.mkdirSync(target, {recursive:true});
  for (const entry of fs.readdirSync(source, {withFileTypes:true})) {
    if (entry.name === '__pycache__' || entry.name.startsWith('.')) continue;
    const src = path.join(source, entry.name), out = path.join(target, entry.name);
    if (entry.isDirectory() && directoryFilter(entry.name)) copyTree(src, out, filter, directoryFilter);
    else if (entry.isFile() && filter(entry.name)) fs.copyFileSync(src, out);
  }
}
copyTree(path.join(root, 'app'), path.join(dest, 'app'), name => name.endsWith('.py'), name => name !== 'web');
copyTree(path.join(root, 'wbot'), path.join(dest, 'wbot'), name => name.endsWith('.py'));
copyTree(path.join(root, 'extension'), path.join(dest, 'extension'), name => /\.(js|json|html|png|svg)$/.test(name));
fs.copyFileSync(path.join(__dirname, 'bridge_server.py'), path.join(dest, 'bridge_server.py'));
fs.mkdirSync(path.join(dest, 'wheels'), {recursive:true});
fs.copyFileSync(wheel, path.join(dest, 'wheels/wbot-0.1.0-py3-none-any.whl'));
fs.copyFileSync(path.join(root, 'LICENSE'), path.resolve(__dirname, '../LICENSE'));
console.log('已准备编码版浏览器服务、wbot 和拾取扩展运行资源');
