'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const extension = path.resolve(__dirname, '..');
const manifest = require(path.join(extension, 'package.json'));
if (!manifest.publisher || manifest.publisher.endsWith('-local')) {
  throw new Error('请先将 package.json 的 publisher 设置为实际创建的 Marketplace Publisher ID');
}
if (!/^[A-Za-z0-9][A-Za-z0-9-]*$/.test(manifest.publisher)) throw new Error('Publisher ID 格式无效');
for (const key of ['repository','homepage','bugs','icon']) {
  if (!manifest[key]) throw new Error('缺少 Marketplace 元数据：'+key);
}
const directory = path.resolve(extension, '../dist/marketplace');
fs.mkdirSync(directory, {recursive:true});
const output = path.join(directory, `${manifest.publisher}.${manifest.name}-${manifest.version}-win32-x64.vsix`);
if (fs.existsSync(output)) throw new Error('发布包已存在，请核对版本或使用干净的构建目录，不覆盖已有产物：'+output);
const result = spawnSync(process.execPath,[path.join(extension,'node_modules/@vscode/vsce/vsce'),
  'package','--no-dependencies','--target','win32-x64','--out',output],{cwd:extension,stdio:'inherit',windowsHide:true});
if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
