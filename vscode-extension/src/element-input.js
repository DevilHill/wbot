'use strict';

function inputStep(vscode, options) {
  return new Promise(resolve => {
    const input = vscode.window.createInputBox();
    Object.assign(input, options);
    input.ignoreFocusOut = true;
    input.buttons = options.step > 1 ? [vscode.QuickInputButtons.Back] : [];
    const listeners = [];
    let settled = false;
    function finish(result) {
      if (settled) return;
      settled = true;
      listeners.forEach(listener => listener.dispose());
      input.dispose();
      resolve(result);
    }
    listeners.push(input.onDidAccept(() => {
      if (options.required && !input.value.trim()) { input.validationMessage = '不能为空'; return; }
      finish({value:input.value});
    }), input.onDidTriggerButton(() => finish({back:true, value:input.value})), input.onDidHide(() => finish(null)));
    input.show();
  });
}

async function editElementDraft(vscode, original = {}) {
  const draft = {...original, group:original.group || '默认'};
  const fields = [['name','元素名称',true], ['group','元素分组',true], ['xpath','XPath',true], ['url','页面 URL（可留空）'], ['description','描述（可留空）']];
  let index = 0;
  while (index < fields.length) {
    const [key, prompt, required] = fields[index];
    const result = await inputStep(vscode, {title:original.id ? '编辑元素' : '新增元素', step:index+1, totalSteps:fields.length,
      prompt, placeholder:prompt, value:draft[key] || '', required});
    if (!result) return;
    draft[key] = result.value;
    index += result.back ? -1 : 1;
  }
  const choice = await vscode.window.showInformationMessage(
    `保存「${draft.group} / ${draft.name}」？`, {modal:true, detail:`XPath：${draft.xpath}\n页面：${draft.url || '未指定'}\n描述：${draft.description || '无'}`}, '保存');
  return choice === '保存' ? draft : undefined;
}

module.exports = {editElementDraft, inputStep};
