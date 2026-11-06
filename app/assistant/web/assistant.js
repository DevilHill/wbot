"use strict";

const $ = selector => document.querySelector(selector);
const statusNames = {preparing:"准备环境",running:"运行中",succeeded:"已完成",failed:"失败",stopped:"已停止",interrupted:"中断待核实",stopping:"停止中"};
let token = "", packages = [], jobs = [], selectedPackage = null, selectedJobId = null;
let packageSnapshot = "", pendingRequest = null, submitting = false;

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function message(text, isError = false) {
  $("#message").textContent = text;
  $("#message").className = "message" + (isError ? " error" : "");
  $("#message").hidden = !text;
}

async function api(path, body) {
  const headers = {"X-WBot-Token":token};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {method:body === undefined ? "GET" : "POST", headers,
    body:body === undefined ? undefined : JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "请求失败，请重试");
  return result;
}

function showView(view) {
  $("#automationsView").hidden = view !== "automations";
  $("#historyView").hidden = view !== "history";
  $("#viewLabel").textContent = view === "automations" ? "我的自动化" : "运行记录";
  $("#pageTitle").textContent = view === "automations" ? "让重复的工作，自动完成。" : "每一次运行，都有记录。";
  $("#pageDescription").textContent = view === "automations" ? "选择一个自动化，填写参数，剩下的交给 WBot。" : "查看任务进度、执行结果与日志，随时了解发生了什么。";
  document.querySelectorAll("[data-view]").forEach(button => {
    button.classList.toggle("active", button.dataset.view === view);
    if (button.dataset.view === view) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
}

function selectPackage(item) {
  selectedPackage = item;
  pendingRequest = null;
  $("#noSelection").hidden = true;
  $("#runForm").hidden = false;
  $("#selectedName").textContent = item.manifest.name;
  $("#selectedVersion").textContent = "版本 " + item.manifest.version + " · 在本机运行";
  $("#parameters").replaceChildren();
  const parameters = Object.entries(item.manifest.parameters || {});
  $("#noParameters").hidden = parameters.length > 0;
  parameters.forEach(([name, definition], index) => {
    const field = node("div", undefined, "field");
    const label = node("label", name + (definition.required ? " *" : ""));
    const input = node("input");
    input.id = "parameter-" + index;
    label.htmlFor = input.id;
    input.name = name;
    input.dataset.parameter = name;
    input.type = definition.type === "boolean" ? "checkbox" : ["number","integer"].includes(definition.type) ? "number" : "text";
    if (input.type === "checkbox") input.checked = definition.default === true;
    else {
      input.value = definition.default ?? "";
      input.required = definition.required === true;
      if (input.type === "number") input.step = definition.type === "integer" ? "1" : "any";
    }
    field.append(label, input);
    if (definition.description) field.append(node("p", definition.description, "field-help"));
    $("#parameters").append(field);
  });
  renderPackages();
}

function renderPackages() {
  $("#packages").replaceChildren();
  $("#emptyPackages").hidden = packages.length > 0;
  for (const item of packages) {
    const button = node("button", undefined, "package-card" + (item.id === selectedPackage?.id ? " selected" : ""));
    button.append(node("span", "◇", "package-symbol"), node("strong", item.manifest.name), node("small", "v" + item.manifest.version));
    button.addEventListener("click", () => selectPackage(item));
    $("#packages").append(button);
  }
}

function packageName(job) {
  return packages.find(item => item.id === job.package_id)?.manifest.name || job.package_id;
}

function renderJobs() {
  $("#jobs").replaceChildren();
  if (!jobs.length) $("#jobs").append(node("p", "还没有运行记录。启动一个自动化后，记录会出现在这里。", "muted"));
  for (const job of jobs) {
    const button = node("button", undefined, "job-card" + (job.id === selectedJobId ? " selected" : ""));
    button.append(node("strong", packageName(job)), node("small", new Date(job.created_at * 1000).toLocaleString()),
      node("span", statusNames[job.state] || job.state, "badge " + job.state));
    button.addEventListener("click", async () => {
      selectedJobId = job.id;
      renderJobs();
      try { await renderJobDetail(); } catch (error) { message(error.message, true); }
    });
    $("#jobs").append(button);
  }
}

async function renderJobDetail() {
  if (!selectedJobId) return;
  const requestedId = selectedJobId;
  const [detail, log] = await Promise.all([api("/api/jobs/" + requestedId), api("/api/jobs/" + requestedId + "/log")]);
  if (requestedId !== selectedJobId) return;
  const job = detail.job;
  $("#emptyJob").hidden = true;
  $("#jobContent").hidden = false;
  $("#jobTitle").textContent = packageName(job);
  $("#jobMetadata").textContent = (statusNames[job.state] || job.state) + " · " + job.id;
  $("#jobError").hidden = !job.error;
  $("#jobError").textContent = job.error || "";
  $("#stopJob").hidden = !["preparing","running","stopping"].includes(job.state);
  $("#jobResult").textContent = job.result == null ? "尚无返回结果" : JSON.stringify(job.result, null, 2);
  const console = $("#jobLog");
  const atBottom = console.scrollTop + console.clientHeight >= console.scrollHeight - 15;
  console.textContent = log.log || "等待日志…";
  if (atBottom) console.scrollTop = console.scrollHeight;
}

async function refresh() {
  const [catalog, history] = await Promise.all([api("/api/packages"), api("/api/jobs")]);
  packages = catalog.items;
  jobs = history.items;
  $("#packageCount").textContent = packages.length;
  $("#runningCount").textContent = jobs.filter(job => ["preparing","running","stopping"].includes(job.state)).length;
  $("#completedCount").textContent = jobs.filter(job => job.state === "succeeded").length;
  const snapshot = JSON.stringify(packages);
  if (snapshot !== packageSnapshot) { packageSnapshot = snapshot; renderPackages(); }
  renderJobs();
  if (!$("#historyView").hidden) await renderJobDetail();
}

async function poll() {
  try {
    if (!token) token = (await api("/api/session")).token;
    await refresh();
    $("#connection").textContent = "● 后台服务已连接";
    $("#connection").classList.remove("offline");
  } catch (error) {
    $("#connection").textContent = "后台服务未连接 · 正在重试";
    $("#connection").classList.add("offline");
    token = "";
  } finally { setTimeout(poll, 1500); }
}

document.querySelectorAll("[data-view]").forEach(button => button.addEventListener("click", () => showView(button.dataset.view)));
function openImport() { $("#importError").hidden = true; $("#importDialog").showModal(); }
$("#importButton").addEventListener("click", openImport);
$("#emptyImport").addEventListener("click", openImport);
$("#cancelImport").addEventListener("click", () => $("#importDialog").close());
$("#importForm").addEventListener("submit", async event => {
  event.preventDefault();
  $("#confirmImport").disabled = true;
  $("#importError").hidden = true;
  try {
    const path = $("#packagePath").value.trim().replace(/^"(.*)"$/, "$1");
    const result = await api("/api/packages", {path});
    await refresh();
    selectPackage(result.package);
    showView("automations");
    $("#importDialog").close();
    message("已导入 " + result.package.manifest.name + "，可以开始运行了。");
  } catch (error) { $("#importError").textContent = error.message; $("#importError").hidden = false; }
  finally { $("#confirmImport").disabled = false; }
});
$("#runForm").addEventListener("submit", async event => {
  event.preventDefault();
  if (submitting || !selectedPackage) return;
  const parameters = {};
  $("#parameters").querySelectorAll("input").forEach(input => {
    if (input.type === "checkbox") parameters[input.name] = input.checked;
    else if (input.type === "text") parameters[input.name] = input.value;
    else if (input.value !== "") parameters[input.name] = Number(input.value);
  });
  const payload = {package_id:selectedPackage.id, parameters};
  const signature = JSON.stringify(payload);
  if (pendingRequest?.signature !== signature) pendingRequest = {signature, id:crypto.randomUUID()};
  submitting = true;
  $("#runButton").disabled = true;
  try {
    const result = await api("/api/jobs", {...payload, request_id:pendingRequest.id});
    selectedJobId = result.job.id;
    pendingRequest = null;
    message("");
    showView("history");
    await refresh();
  } catch (error) { message(error.message, true); }
  finally { submitting = false; $("#runButton").disabled = false; }
});
$("#stopJob").addEventListener("click", async () => {
  $("#stopJob").disabled = true;
  try { await api("/api/jobs/" + selectedJobId + "/stop", {}); await refresh(); }
  catch (error) { message(error.message, true); }
  finally { $("#stopJob").disabled = false; }
});
poll();
