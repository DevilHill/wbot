'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');
const os=require('node:os');
const {completionContext,projectElements}=require('../src/completions');
test('元素补全限定 SelectorStore 的名称与分组，不干扰普通字典',()=>{
 const source='elements = selector.SelectorStore()';
 assert.deepEqual(completionContext(source,'elements.get("登'),{field:'name',prefix:'登',quote:'"'});
 assert.deepEqual(completionContext(source,"elements.get('登录', group='财"),{field:'group',prefix:'财',quote:"'"});
 assert.equal(completionContext(source,'other.get("'),null);
});
test('离线读取项目元素，拒绝项目外文件与超限快照',async t=>{
 const directory=await fs.mkdtemp(path.join(os.tmpdir(),'wbot-completion-'));t.after(()=>fs.rm(directory,{recursive:true,force:true}));
 const entries=[{name:'登录',group:'页面',xpath:'//button'}];
 await fs.writeFile(path.join(directory,'elements.json'),JSON.stringify({format:'wbot-elements',version:1,items:entries}));
 await fs.writeFile(path.join(directory,'wbot.json'),JSON.stringify({elements:'elements.json'}));
 assert.deepEqual(await projectElements(directory),entries);
 await fs.writeFile(path.join(directory,'wbot.json'),JSON.stringify({elements:'../outside.json'}));assert.deepEqual(await projectElements(directory),[]);
});

test('通过目录别名读取项目元素，仍拒绝指向项目外的快照',async t=>{
 const directory=await fs.mkdtemp(path.join(os.tmpdir(),'wbot-completion-alias-'));
 t.after(()=>fs.rm(directory,{recursive:true,force:true}));
 const project=path.join(directory,'project'),alias=path.join(directory,'alias');
 await fs.mkdir(project);await fs.symlink(project,alias,process.platform==='win32'?'junction':'dir');
 const entries=[{name:'登录',group:'页面',xpath:'//button'}];
 await fs.writeFile(path.join(project,'elements.json'),JSON.stringify({format:'wbot-elements',items:entries}));
 await fs.writeFile(path.join(project,'wbot.json'),JSON.stringify({elements:'elements.json'}));
 assert.deepEqual(await projectElements(alias),entries);
 await fs.writeFile(path.join(directory,'outside.json'),JSON.stringify({format:'wbot-elements',items:entries}));
 await fs.symlink(directory,path.join(project,'outside'),process.platform==='win32'?'junction':'dir');
 await fs.writeFile(path.join(project,'wbot.json'),JSON.stringify({elements:'outside/outside.json'}));
 assert.deepEqual(await projectElements(alias),[]);
});
