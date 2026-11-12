'use strict';
const {randomBytes} = require('node:crypto');
const fields = [['name','元素名称',200,true], ['group','分组',200,true], ['xpath','XPath',8192,true], ['url','页面 URL',4096,false], ['description','描述',4000,false]];
const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
function validateDraft(value, original = {}) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some(key => !fields.some(([name])=>name===key))) throw new Error('元素表单格式无效');
  const record = {...original};
  for (const [key,label,limit,required] of fields) {
    if (typeof value[key] !== 'string' || value[key].length > limit || value[key].includes('\0')) throw new Error(`${label}格式无效或过长`);
    record[key] = value[key].trim();
    if (required && !record[key]) throw new Error(`${label}不能为空`);
  }
  return record;
}
function editorHTML(nonce, original) {
  return `<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}';"><style nonce="${nonce}">
  body{font:var(--vscode-font-size)/1.6 var(--vscode-font-family);color:var(--vscode-foreground);background:var(--vscode-editor-background);padding:24px;max-width:680px;margin:auto}h1{font-size:22px;margin-bottom:4px}.hint{color:var(--vscode-descriptionForeground)}form{margin-top:24px}label{display:block;margin:16px 0 6px;font-weight:600}input,textarea{box-sizing:border-box;width:100%;padding:10px 12px;color:var(--vscode-input-foreground);background:var(--vscode-input-background);border:1px solid var(--vscode-input-border,var(--vscode-widget-border));border-radius:9px;font:inherit}textarea{resize:vertical;min-height:90px}input:focus,textarea:focus,button:focus-visible{outline:2px solid var(--vscode-focusBorder);outline-offset:2px}footer{display:flex;gap:12px;margin-top:24px}button{cursor:pointer;border:0;border-radius:8px;padding:9px 18px;background:var(--vscode-button-background);color:var(--vscode-button-foreground);font:inherit}button:hover{background:var(--vscode-button-hoverBackground)}button:disabled{opacity:.6;cursor:wait}button.secondary{background:var(--vscode-button-secondaryBackground);color:var(--vscode-button-secondaryForeground)}#error{color:var(--vscode-errorForeground);white-space:pre-wrap}.pair{display:grid;grid-template-columns:2fr 1fr;gap:16px}@media(max-width:450px){.pair{grid-template-columns:1fr}body{padding:16px}}fieldset{border:0;padding:0;margin:0}small{font-weight:400;color:var(--vscode-descriptionForeground)}
  </style></head><body><h1>${original.id?'编辑元素':'新增元素'}</h1><p class="hint">保存 XPath 和页面信息，供 Python 脚本通过名称调用。</p><form><fieldset><div class="pair">${fields.slice(0,2).map(field=>control(field,original)).join('')}</div>${fields.slice(2).map(field=>control(field,original)).join('')}<footer><button type="submit">保存元素</button><button type="button" id="cancel" class="secondary">取消</button></footer></fieldset><p id="error" role="alert"></p></form>
  <script nonce="${nonce}">(()=>{const api=acquireVsCodeApi();const form=document.querySelector('form');const fieldset=document.querySelector('fieldset');let busy=false;document.querySelector('input').focus();form.addEventListener('submit',event=>{event.preventDefault();if(busy)return;busy=true;fieldset.disabled=true;document.getElementById('error').textContent='';const fields={};new FormData(form).forEach((value,key)=>fields[key]=value);/* disabled controls are excluded: read owned fields explicitly */for(const field of form.querySelectorAll('[name]'))fields[field.name]=field.value;api.postMessage({action:'save',session:'${nonce}',fields});});document.getElementById('cancel').addEventListener('click',()=>api.postMessage({action:'cancel',session:'${nonce}'}));window.addEventListener('message',event=>{const message=event.data;if(message?.session!=='${nonce}'||message.action!=='error')return;busy=false;fieldset.disabled=false;document.getElementById('error').textContent=message.error;});})();</script></body></html>`;
}
function control([key,label,limit,required], original) {
  const attrs = `id="${key}" name="${key}" maxlength="${limit}" ${required?'required':''}`;
  const value = original[key] ?? (key==='group'?'默认':'');
  return `<div><label for="${key}">${label}${required?'':' <small>可选</small>'}</label>${['xpath','description'].includes(key)?`<textarea ${attrs} spellcheck="false">${escape(value)}</textarea>`:`<input ${attrs} value="${escape(value)}">`}</div>`;
}
function editElementDraft(vscode, original = {}, save = async record => record) {
  const nonce = randomBytes(24).toString('hex');
  const panel = vscode.window.createWebviewPanel('wbot.elementEditor', original.id?'编辑元素':'新增元素', vscode.ViewColumn.Active, {enableScripts:true,localResourceRoots:[]});
  panel.webview.html = editorHTML(nonce, original);
  return new Promise(resolve => {
    let closed=false, busy=false;
    const listener=panel.webview.onDidReceiveMessage(async message=>{
      if(closed || busy || !message || message.session!==nonce)return;
      if(message.action==='cancel'){panel.dispose();return;}
      if(message.action!=='save')return;
      busy=true;
      try {const record=validateDraft(message.fields,original);const saved=await save(record);if(!closed){resolve(saved);panel.dispose();}}
      catch(error){if(!closed)await panel.webview.postMessage({action:'error',session:nonce,error:error.message});}
      finally{busy=false;}
    });
    const disposed=panel.onDidDispose(()=>{closed=true;listener.dispose();disposed.dispose();resolve(undefined);});
  });
}
module.exports={editElementDraft,validateDraft,editorHTML};
