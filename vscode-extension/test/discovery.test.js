"use strict";
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const os=require('node:os');
const path=require('node:path');
const http=require('node:http');
const {parseAssistantProcesses,assistantProcesses,discoverAssistants}=require('../src/assistant-discovery');

test('仅识别 Assistant serve 进程，支持有空格的数据目录',()=>{
 const rows=parseAssistantProcesses([{ProcessId:123,CommandLine:'"C:\\Python\\python.exe" -m app.assistant serve --state-dir "D:\\My Data\\assistant" --port 0'},{ProcessId:124,CommandLine:'python unrelated.py --state-dir C:\\wrong'},{ProcessId:125,CommandLine:'python -m app.assistant open --state-dir C:\\wrong'}]);
 assert.deepEqual(rows,[{pid:123,directory:'D:\\My Data\\assistant'}]);
});
test('发现需要活进程和正确产品健康响应，不接受陈旧记录或其他本机服务',async t=>{
 const directory=await fs.mkdtemp(path.join(os.tmpdir(),'wbot-discovery-'));
 let product='wbot-assistant';
 const server=http.createServer((req,res)=>{assert.equal(req.headers['x-wbot-token'],'local-secret');res.setHeader('Content-Type','application/json');res.end(JSON.stringify({product,version:'0.8.0'}));});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 t.after(async()=>{server.closeAllConnections();await new Promise(resolve=>server.close(resolve));await fs.rm(directory,{recursive:true,force:true});});
 await fs.writeFile(path.join(directory,'service.json'),JSON.stringify({url:`http://127.0.0.1:${server.address().port}`,token:'local-secret',pid:321}));
 const options={directories:[directory],processes:[],isAlive:pid=>pid===321};
 const found=await discoverAssistants(options);assert.equal(found.length,1);assert.equal(found[0].directory,directory);assert.equal(JSON.stringify(found).includes('local-secret'),false);
 assert.deepEqual(await discoverAssistants({...options,isAlive:()=>false}),[]);
 product='another-product';assert.deepEqual(await discoverAssistants(options),[]);
 assert.deepEqual(await discoverAssistants({...options,processes:[{pid:999,directory}]}),[]);
});

test('从真实 Windows 进程发现自定义目录的 Assistant，退出后不再误连',{skip:process.platform!=='win32' || !process.env.WBOT_TEST_PYTHON},async t=>{
 const {spawn}=require('node:child_process');
 const {once}=require('node:events');
 const {send}=require('../src/publish-client');
 const directory=await fs.realpath(await fs.mkdtemp(path.join(os.tmpdir(),'wbot auto discovery ')));
 const child=spawn(process.env.WBOT_TEST_PYTHON,['-X','utf8','-m','app.assistant','serve','--state-dir',directory,'--port','0'],{cwd:path.resolve(__dirname,'../..'),windowsHide:true,env:{...process.env,WBOT_BROWSER_PORT:'0'},stdio:['ignore','pipe','pipe']});
 let errors='';child.stderr.on('data',chunk=>{errors+=chunk;});
 t.after(async()=>{if(child.exitCode===null){const closed=once(child,'close');child.kill();await closed;}await fs.rm(directory,{recursive:true,force:true});});
 let metadata;
 const deadline=Date.now()+10000;
 while(Date.now()<deadline){try{metadata=JSON.parse(await fs.readFile(path.join(directory,'service.json'),'utf8'));break;}catch{}if(child.exitCode!==null)throw new Error(errors);await new Promise(resolve=>setTimeout(resolve,50));}
 assert.ok(metadata,'Assistant must become ready');
 const processes=await assistantProcesses();
 assert.ok(processes.some(item=>item.pid===metadata.pid),'CIM must report the live Assistant PID');
 const found=await discoverAssistants({directories:[],processes});
 assert.ok(found.some(item=>item.directory===directory && item.pid===metadata.pid));
 const closed=once(child,'close');
 await send(metadata.url,'/api/service/stop',{method:'POST',headers:{'X-WBot-Token':metadata.token,'Content-Type':'application/json'},body:{}});
 await closed;
 assert.equal((await discoverAssistants({directories:[directory],processes:[]})).length,0);
});
