'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {requestBrowser}=require('../src/assistant-browser');
const {startSharedFixture}=require('./shared-fixture');

test('元素读写、导入导出由真实 Assistant 托管，不启动插件 Python 服务',async t=>{
 const fixture=await startSharedFixture();t.after(()=>fixture.close());
 const directory=fixture.assistant_dir;
 const info=await requestBrowser(directory);assert.equal(info.library_path,fixture.library_path);
 const saved=await requestBrowser(directory,'/api/elements/save',{record:{name:'搜索框',group:'首页',xpath:'//input'}});
 assert.equal((await requestBrowser(directory,'/api/elements')).items.length,1);
 const exported=(await requestBrowser(directory,'/api/elements/export')).data;
 await requestBrowser(directory,'/api/elements/delete',{id:saved.item.id});
 assert.equal((await requestBrowser(directory,'/api/elements')).items.length,0);
 await requestBrowser(directory,'/api/elements/import',{data:exported,conflict:'error'});
 assert.equal((await requestBrowser(directory,'/api/elements')).items[0].name,'搜索框');
 await assert.rejects(requestBrowser(directory,'/api/bridge/pick',{}),/浏览器扩展/);
 assert.equal((await requestBrowser(directory,'/api/extension/prepare')).directory.endsWith('browser-extension'),true);
});

test('旧版 Assistant 返回升级提示，离线不会回退启动本地 Python',async t=>{
 const fs=require('node:fs/promises'),os=require('node:os'),path=require('node:path'),http=require('node:http');
 const directory=await fs.mkdtemp(path.join(os.tmpdir(),'wbot-old-assistant-'));
 const server=http.createServer((_request,response)=>{response.writeHead(404,{'Content-Type':'application/json'});response.end(JSON.stringify({error:'页面不存在'}));});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 t.after(async()=>{server.closeAllConnections();await new Promise(resolve=>server.close(resolve));await fs.rm(directory,{recursive:true,force:true});});
 await fs.writeFile(path.join(directory,'service.json'),JSON.stringify({url:`http://127.0.0.1:${server.address().port}`,token:'test-session'}));
 await assert.rejects(requestBrowser(directory),/升级到 0.9.0/);
 await fs.unlink(path.join(directory,'service.json'));
 await assert.rejects(requestBrowser(directory),/请先打开 Assistant/);
});
