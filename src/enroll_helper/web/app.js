const $ = (id) => document.getElementById(id);
const REPO_URL = "https://github.com/WilloTwisper/SUSTech-CourseCat";
let lastEvent = 0;
let queueNames = [];
let enrolledN = 0;
let page = 1, size = 30;
let facetsLoaded = false;
let lang = "zh";
try { lang = localStorage.getItem("cc-lang") || "zh"; } catch (e) {}

const I18N = {
zh: {
  hello: "您好", fullscreen: "全屏", notice: "本地抢课控制台：仅在你点“开始抢课”后才会向教务系统提交真实请求。",
  consoleTitle: "抢课控制台", consoleMini: "（按优先级从上到下）",
  mode: "模式", now: "立即", at: "定时", retry: "蹲退课",
  atLabel: "开抢时间", atPh: "10:00 或 2026-09-08 10:00:00",
  interval: "间隔ms", target: "提交", direct: "直选", cart: "购物车",
  cascade: "满员轮询", ntp: "NTP校时",
  start: "开始抢课", stop: "停止", refresh: "刷新目录", login: "重新登录",
  qCourse: "待选课程", qType: "类别", qSeats: "余量", qStatus: "状态", qOp: "操作",
  stWaiting: "等待", watchBadge: "🔥待释放",
  semLabel: "学年学期", school: "开课学院", allSchools: "请选择",
  cat: "课程类别", allCats: "课程类别", course: "课程", coursePh: "课程",
  ignoreConflict: "忽略冲突", hideFull: "忽略零余量", search: "查询",
  tabYx: "已选", tabBxxk: "通识必修选课", tabXxxk: "通识选修选课",
  tabKzyxk: "培养方案内课程", tabZynknjxk: "非培养方案内课程", tabCxxk: "重修选课",
  cTask: "教学班", cCode: "课程代码", cTitle: "课程名称", cNature: "课程性质",
  cCat: "课程类别", cLang: "授课语言", cGrade: "计分方式", cCredit: "学分",
  cHours: "学时", cSkxx: "上课信息", cSeats: "容量/已选", cConflict: "冲突课程",
  cSchool: "开课学院", cOp: "操作",
  fHome: "主页", fXk: "我要选课", fShare: "推荐给同学", fDisc: "免责声明", fClose: "关闭标签",
  dTitle: "免责声明",
  d1: "抢课猫 CourseCat 仅供个人学习与研究使用。使用本工具产生的任何行为由使用者本人承担，请确保符合学校规章制度与相关法规。",
  d2: "本工具不规避任何安全机制、不做流量伪装、不承诺任何效果；作者不对封号、处分等任何直接或间接后果负责。",
  d3: "如果你觉得好用，欢迎 Star 本项目并推荐给同学（页脚可一键分享）。",
  dOk: "我知道了",
  ribbonHide: "收起 ▴", ribbonShow: "展开 ▾",
  enroll: "选课", added: "已加入",
  queueEmpty: "队列为空：在下方课程表点“选课”加入喵",
  enrolledEmpty: "暂无已选课程（退课请去教务页面手动操作）",
  needRefresh: "目录为空：点“刷新目录”（首次约半分钟）",
  queryFail: "查询失败: ", addFail: "加入失败: ", notFound: "未找到: ",
  queueFail: "队列更新失败: ", statusFail: "状态同步失败: ",
  startNeedTime: "定时模式请填写开抢时间", startOk: "已启动…", startFail: "启动失败: ",
  stopOk: "已请求停止…", stopFail: "停止失败: ",
  refreshOk: "开始下载目录（约半分钟）…", refreshFail: "刷新失败: ",
  loginOk: "已打开浏览器，请完成统一身份认证登录…", loginFail: "登录失败: ",
  sessOk: "会话 ✓", sessNo: "✗（点重新登录）",
  bannerWaiting: "等待开抢 {t} …（可点停止取消）",
  bannerRunning: "抢课进行中…（串行请求，间隔 ≥1500ms）",
  bannerDone: "本轮结束喵，详见日志。",
  bannerIdle: "{sem} · 待选 {n} 门",
  bannerSnap: " · 目录快照 {snap}",
  bannerReady: " · 就绪",
  doneSummary: "运行结束: 请求{n1} 成功{n2} 跳过{n3}",
  doneOne: "  成功: ", shareTitle: "抢课猫 CourseCat",
  shareText: "南科大 TIS 抢课助手，开源免费",
  shareCopied: "推荐链接已复制，去发给同学吧",
  sharePrompt: "复制这个链接发给同学：",
  docTitle: "抢课猫 CourseCat · 南科大 TIS 助手",
  pgTotal: "共 {n} 条", pgGo: "跳至", pgPage: "页", pgPer: "{n}条/页",
},
en: {
  hello: "Hello", fullscreen: "Fullscreen", notice: "Local grab console: real requests are only sent after you press Start.",
  consoleTitle: "Grab Console", consoleMini: "(strict priority, top first)",
  mode: "Mode", now: "Now", at: "Scheduled", retry: "Waitlist",
  atLabel: "Start at", atPh: "10:00 or 2026-09-08 10:00:00",
  interval: "Interval ms", target: "Submit", direct: "Direct", cart: "Cart",
  cascade: "Full rotation", ntp: "NTP sync",
  start: "Start", stop: "Stop", refresh: "Refresh", login: "Re-login",
  qCourse: "Watched courses", qType: "Type", qSeats: "Seats", qStatus: "Status", qOp: "Actions",
  stWaiting: "Waiting", watchBadge: "🔥releasing",
  semLabel: "Semester", school: "School", allSchools: "All",
  cat: "Category", allCats: "All", course: "Course", coursePh: "Keyword",
  ignoreConflict: "Hide conflicts", hideFull: "Hide full", search: "Search",
  tabYx: "Enrolled", tabBxxk: "GenEd Required", tabXxxk: "GenEd Electives",
  tabKzyxk: "In-Program", tabZynknjxk: "Extra-Program", tabCxxk: "Retakes",
  cTask: "Class", cCode: "Code", cTitle: "Title", cNature: "Nature",
  cCat: "Category", cLang: "Language", cGrade: "Grading", cCredit: "Credits",
  cHours: "Hours", cSkxx: "Schedule", cSeats: "Cap/Enrolled", cConflict: "Conflicts",
  cSchool: "School", cOp: "Action",
  fHome: "Home", fXk: "Enroll", fShare: "Recommend", fDisc: "Disclaimer", fClose: "Close tab",
  dTitle: "Disclaimer",
  d1: "CourseCat is for personal study and research only. You are responsible for your own actions; make sure they comply with school regulations and applicable laws.",
  d2: "This tool circumvents no security mechanisms, disguises no traffic, and guarantees nothing. The author is not liable for bans, penalties, or any consequences.",
  d3: "If you find it useful, please Star the project and recommend it to friends (one-click share in the footer).",
  dOk: "Got it",
  ribbonHide: "Collapse ▴", ribbonShow: "Expand ▾",
  enroll: "Enroll", added: "Added",
  queueEmpty: "Queue empty: hit Enroll below to add some, meow",
  enrolledEmpty: "No enrolled courses (drop courses on the TIS page)",
  needRefresh: "Catalog empty: hit Refresh (~30s first time)",
  queryFail: "Query failed: ", addFail: "Add failed: ", notFound: "Not found: ",
  queueFail: "Queue update failed: ", statusFail: "Status sync failed: ",
  startNeedTime: "Set a start time for scheduled mode", startOk: "Started…", startFail: "Start failed: ",
  stopOk: "Stop requested…", stopFail: "Stop failed: ",
  refreshOk: "Downloading catalog (~30s)…", refreshFail: "Refresh failed: ",
  loginOk: "Browser opened, please complete SSO login…", loginFail: "Login failed: ",
  sessOk: "Session ✓", sessNo: "✗ (click Re-login)",
  bannerWaiting: "Waiting for {t}… (Stop to cancel)",
  bannerRunning: "Grabbing… (serial requests, ≥1500ms interval)",
  bannerDone: "Round done, see log, meow.",
  bannerIdle: "{sem} · {n} queued",
  bannerSnap: " · snapshot {snap}",
  bannerReady: " · ready",
  doneSummary: "Round over: {n1} requests, {n2} success, {n3} skipped",
  doneOne: "  Enrolled: ", shareTitle: "CourseCat",
  shareText: "SUSTech TIS enrollment helper, free and open source",
  shareCopied: "Referral link copied, send it to friends",
  sharePrompt: "Copy this link to a friend:",
  docTitle: "CourseCat · SUSTech TIS Helper",
  pgTotal: "{n} courses", pgGo: "Go to", pgPage: "", pgPer: "{n}/page",
},
};

const TAB_DEFS = [
  ["yx", "tabYx"],
  ["bxxk", "tabBxxk"],
  ["xxxk", "tabXxxk"],
  ["kzyxk", "tabKzyxk"],
  ["zynknjxk", "tabZynknjxk"],
  ["cxxk", "tabCxxk"],
];
let activeTab = "xxxk";

function t(k, vars) {
  let s = (I18N[lang] && I18N[lang][k] != null) ? I18N[lang][k] : (I18N.zh[k] != null ? I18N.zh[k] : k);
  if (vars) for (const key of Object.keys(vars)) s = s.replace("{" + key + "}", vars[key]);
  return s;
}

function applyI18n() {
  document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  document.title = t("docTitle");
  document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll("[data-i18n-ph]").forEach((el) => { el.placeholder = t(el.dataset.i18nPh); });
  $("lang").textContent = lang === "zh" ? "EN" : "中文";
  renderTabs();
  refreshCourses();
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((data && data.error) || ("HTTP " + r.status));
  return data;
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => (
    {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
}

function logLine(text, cls) {
  const box = $("log");
  const div = document.createElement("div");
  if (cls) div.className = cls;
  div.textContent = text;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function beep() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.connect(g); g.connect(ctx.destination);
    o.frequency.value = 880; g.gain.value = 0.12;
    o.start(); o.stop(ctx.currentTime + 0.35);
  } catch (e) { /* ignore */ }
}

function renderTabs() {
  const box = $("tabs");
  box.innerHTML = "";
  for (const [code, key] of TAB_DEFS) {
    const b = document.createElement("button");
    b.className = "tab" + (code === activeTab ? " active" : "");
    b.textContent = code === "yx" ? `${t(key)}(${enrolledN})` : t(key);
    b.onclick = () => { activeTab = code; renderTabs(); refreshCourses(); };
    box.appendChild(b);
  }
}

function courseRow(r, inQueue) {
  const tr = document.createElement("tr");
  tr.innerHTML =
    `<td>${esc(r.task)}</td><td>${esc(r.code)}</td>` +
    `<td><span class="cname">${esc(r.title)}<small>${esc(r.title_en)}</small></span></td>` +
    `<td>${esc(r.nature) || "—"}</td><td>${esc(r.category) || "—"}</td>` +
    `<td>${esc(r.lang) || "—"}</td><td>${esc(r.grade) || "—"}</td>` +
    `<td>${esc(r.credit) || "—"}</td><td>${esc(r.hours) || "—"}</td>` +
    `<td>${r.teacher ? `<div class="tname">${esc(r.teacher)}</div>` : ""}` +
    `${(r.sched_tags || []).length
      ? `<div><b>${t("cSkxx")}：</b>${r.sched_tags.map((x) => `<span class="tag">${esc(x)}</span>`).join("")}</div>`
      : (r.teacher ? "" : '<span class="mini">—</span>')}</td>` +
    `<td class="seats">对内容量：<b>${r.cap == null ? "—" : r.cap}</b>，` +
    `已选人数：<b>${r.enrolled == null ? "—" : r.enrolled}</b></td>` +
    `<td>${(r.conflicts || []).length
      ? `<span class="conflict">${r.conflicts.map(esc).join("；")}</span>` : "—"}</td>` +
    `<td>${esc(r.school) || "—"}</td>`;
  const td = document.createElement("td");
  const btn = document.createElement("button");
  btn.className = "btn btn-green";
  btn.style.padding = "0 12px";
  btn.style.height = "28px";
  btn.textContent = inQueue ? t("added") : t("enroll");
  btn.disabled = !!inQueue;
  btn.onclick = async () => {
    try {
      await api("/api/queue", {method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({names: queueNames.concat([r.task])})});
      await refreshStatus();
    } catch (e) { logLine(t("addFail") + e.message, "err"); }
  };
  td.appendChild(btn);
  tr.appendChild(td);
  return tr;
}

async function loadFacets() {
  try {
    const d = await api("/api/facets");
    const fill = (id, items, first) => {
      const sel = $(id), cur = sel.value;
      sel.innerHTML = "";
      const o0 = document.createElement("option");
      o0.value = ""; o0.textContent = first; sel.appendChild(o0);
      for (const v of items) {
        const o = document.createElement("option");
        o.value = v; o.textContent = v; sel.appendChild(o);
      }
      if (items.includes(cur)) sel.value = cur;
    };
    fill("school", d.schools || [], t("allSchools"));
    fill("cat2", d.categories || [], t("allCats"));
  } catch (e) { /* 目录未就绪 */ }
}

function renderPager(total, pg, pages, sz) {
  const box = $("pager");
  box.innerHTML = "";
  const span = (x) => {
    const s = document.createElement("span"); s.textContent = x; box.appendChild(s);
  };
  span(t("pgTotal", {n: total}));
  const btn = (x, p, dis, cur) => {
    const b = document.createElement("button");
    b.textContent = x; b.disabled = !!dis;
    if (cur) b.className = "cur";
    b.onclick = () => { page = p; refreshCourses(); };
    box.appendChild(b);
  };
  btn("<", Math.max(pg - 1, 1), pg <= 1);
  const lo = Math.max(1, Math.min(pg - 2, pages - 4)), hi = Math.min(pages, lo + 4);
  for (let p = lo; p <= hi; p++) btn(String(p), p, false, p === pg);
  btn(">", Math.min(pg + 1, pages), pg >= pages);
  const sel = document.createElement("select");
  for (const n of [17, 30, 50, 100]) {
    const o = document.createElement("option");
    o.value = n; o.textContent = t("pgPer", {n}); if (n === sz) o.selected = true;
    sel.appendChild(o);
  }
  sel.onchange = () => { size = parseInt(sel.value, 10); page = 1; refreshCourses(); };
  box.appendChild(sel);
  span(t("pgGo"));
  const inp = document.createElement("input");
  inp.value = pg;
  inp.onkeydown = (e) => {
    if (e.key === "Enter") { page = parseInt(inp.value, 10) || 1; refreshCourses(); }
  };
  box.appendChild(inp);
  span(t("pgPage"));
}

async function refreshCourses() {
  const body = $("course-body");
  try {
    if (activeTab === "yx") {
      const d = await api("/api/enrolled");
      body.innerHTML = "";
      if (!d.enrolled.length) {
        body.innerHTML = `<tr><td colspan="14" style="color:#808695">${esc(t("enrolledEmpty"))}</td></tr>`;
      }
      for (const e of d.enrolled) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td colspan="2">${esc(e.name)}</td>` +
          `<td colspan="11" class="mini">${esc((e.teachers || []).join("、"))} ${esc(e.schedule || "").slice(0, 120)}</td>` +
          `<td class="mini">${esc(e.id)}</td>`;
        body.appendChild(tr);
      }
      $("pager").innerHTML = `<span>${esc(t("pgTotal", {n: d.enrolled.length}))}</span>`;
      return;
    }
    const q = $("q").value.trim();
    const hide = $("hidefull").checked ? "&hide_full=1" : "";
    const hidec = $("ignoreConflict").checked ? "&hide_conflict=1" : "";
    const school = encodeURIComponent($("school").value || "");
    const cat = encodeURIComponent($("cat2").value || "");
    const d = await api(`/api/courses?tab=${activeTab}&q=${encodeURIComponent(q)}${hide}${hidec}` +
      `&school=${school}&category=${cat}&page=${page}&size=${size}`);
    if (d.needs_refresh) {
      body.innerHTML = `<tr><td colspan="14" style="color:#808695">${esc(t("needRefresh"))}</td></tr>`;
      $("pager").innerHTML = "";
      return;
    }
    body.innerHTML = "";
    for (const r of d.courses) body.appendChild(courseRow(r, queueNames.includes(r.task)));
    renderPager(d.total, d.page, d.pages, d.size);
    $("count").textContent = "";
  } catch (e) {
    body.innerHTML = `<tr><td colspan="14" style="color:#ED4014">${esc(t("queryFail") + e.message)}</td></tr>`;
  }
}

function fmtSeats(row) {
  if (row.cap != null && row.enrolled != null) {
    const left = Math.max(row.cap - row.enrolled, 0);
    return lang === "zh" ? `余${left}/${row.cap}` : `${left}/${row.cap} left`;
  }
  return row.seats;
}

function queueRow(row) {
  const tr = document.createElement("tr");
  const st = row.status === "等待" ? t("stWaiting") : row.status;
  if (row.status && row.status !== "等待") tr.className = "qrow";
  tr.innerHTML = `<td>${row.index}</td><td>${esc(row.name)}</td><td>${esc(row.type)}</td>` +
    `<td>${esc(fmtSeats(row))}</td>` +
    `<td class="st-${esc(row.status)}">${esc(st)}${row.watch ? " " + t("watchBadge") : ""} ${esc(row.message).slice(0, 40)}</td>`;
  const td = document.createElement("td");
  const mk = (x, fn) => {
    const b = document.createElement("button");
    b.className = "btn"; b.style.padding = "2px 8px"; b.textContent = x;
    b.onclick = fn; td.appendChild(b); td.appendChild(document.createTextNode(" "));
  };
  mk("↑", () => moveQueue(row.index - 1, -1));
  mk("↓", () => moveQueue(row.index - 1, 1));
  mk("×", () => setQueue(queueNames.filter((_, i) => i !== row.index - 1)));
  tr.appendChild(td);
  return tr;
}

async function setQueue(names) {
  try {
    const d = await api("/api/queue", {method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({names})});
    if (d.unknown && d.unknown.length) logLine(t("notFound") + d.unknown.join("、"), "warn");
    await refreshStatus();
  } catch (e) { logLine(t("queueFail") + e.message, "err"); }
}

async function moveQueue(idx, delta) {
  const arr = queueNames.slice();
  const j = idx + delta;
  if (idx < 0 || idx >= arr.length || j < 0 || j >= arr.length) return;
  [arr[idx], arr[j]] = [arr[j], arr[idx]];
  await setQueue(arr);
}

async function refreshStatus() {
  try {
    const s = await api("/api/status");
    $("session-badge").textContent = (s.session ? t("sessOk") : t("sessNo"));
    $("semester-label").textContent = s.semester || "…";
    $("xnxq").textContent = s.semester_code || "…";
    queueNames = s.queue.map((r) => r.name);
    const qb = $("queue-body");
    qb.innerHTML = "";
    if (!s.queue.length) {
      qb.innerHTML = `<tr><td colspan="6" style="color:#808695">${esc(t("queueEmpty"))}</td></tr>`;
    }
    for (const r of s.queue) qb.appendChild(queueRow(r));
    $("start").disabled = !!s.running;
    const banner = $("phase-text");
    if (s.running) banner.textContent = s.phase === "waiting"
      ? t("bannerWaiting", {t: s.target || ""})
      : t("bannerRunning");
    else if (s.phase === "done") banner.textContent = t("bannerDone");
    else banner.textContent =
      t("bannerIdle", {sem: s.semester || "?", n: s.queue.length}) +
      (s.cache_snap ? t("bannerSnap", {snap: s.cache_snap}) : "") + t("bannerReady");
    if (s.catalog_count > 0 && !facetsLoaded) {
      facetsLoaded = true;
      loadFacets();
    }
    try {
      const e = await api("/api/enrolled");
      enrolledN = e.enrolled.length;
    } catch (_) { /* 会话未就绪时静默 */ }
    renderTabs();
    return s;
  } catch (e) {
    logLine(t("statusFail") + e.message, "err");
    return null;
  }
}

async function pollEvents() {
  try {
    const d = await api(`/api/events?since=${lastEvent}`);
    for (const e of d.events) {
      lastEvent = Math.max(lastEvent, e.id);
      if (e.kind === "log") logLine(e.text);
      else if (e.kind === "attempt") {
        const cls = e.status === "SUCCESS" ? "good"
          : (e.status === "FULL" || e.status === "CONFLICT" ? "warn" : "");
        logLine(`#${e.index} ${e.course} -> ${e.status} ${e.message} (${e.latency_ms}ms)`, cls);
        if (e.status === "SUCCESS") { beep(); document.title = "✓ " + t("doneOne").trim() + " - CourseCat"; }
      } else if (e.kind === "done") {
        const s = e.summary;
        logLine(t("doneSummary", {n1: s.total_requests, n2: s.successes.length, n3: s.skipped.length}), "ok");
        for (const c of s.successes) logLine(t("doneOne") + c, "good");
        await refreshStatus();
        await refreshCourses();
      } else if (e.kind === "error") {
        logLine("✗ " + e.text, "err");
        await refreshStatus();
      }
    }
  } catch (e) { /* 下轮重试 */ }
}

function collectStart() {
  const mode = document.querySelector('input[name=mode]:checked').value;
  return {
    mode,
    at: $("at").value.trim(),
    interval_ms: parseInt($("interval").value, 10) || 1600,
    retry: mode === "retry",
    cascade: $("cascade").checked,
    ignore_conflict: $("ignoreConflict").checked,
    ntp: $("ntp").checked,
    target: document.querySelector('input[name=target]:checked').value,
  };
}

window.addEventListener("DOMContentLoaded", () => {
  try {
    if (localStorage.getItem("cc-lang") === "en") lang = "en";
  } catch (e) {}
  applyI18n();
  refreshStatus().then(refreshCourses);
  setInterval(pollEvents, 600);
  setInterval(refreshStatus, 4000);
  let deb = null;
  $("q").addEventListener("input", () => {
    clearTimeout(deb); deb = setTimeout(() => { page = 1; refreshCourses(); }, 350);
  });
  $("search").onclick = () => { page = 1; refreshCourses(); };
  $("hidefull").onchange = () => { page = 1; refreshCourses(); };
  $("school").onchange = () => { page = 1; refreshCourses(); };
  $("cat2").onchange = () => { page = 1; refreshCourses(); };
  $("fs").onclick = () => {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    else document.documentElement.requestFullscreen().catch(() => {});
  };
  $("theme").onclick = () => {
    const dark = document.body.classList.toggle("dark");
    $("theme").textContent = dark ? "☀️" : "🌙";
    try { localStorage.setItem("cc-theme", dark ? "dark" : "light"); } catch (e) {}
  };
  try {
    const qp = new URLSearchParams(location.search);
    if (qp.get("theme") === "dark") localStorage.setItem("cc-theme", "dark");
    if (localStorage.getItem("cc-theme") === "dark") {
      document.body.classList.add("dark");
      $("theme").textContent = "☀️";
    }
  } catch (e) {}
  $("lang").onclick = () => {
    lang = lang === "zh" ? "en" : "zh";
    try { localStorage.setItem("cc-lang", lang); } catch (e) {}
    applyI18n();
  };
  $("star").onclick = () => window.open(REPO_URL, "_blank");
  $("disclaimer").onclick = () => { $("modal-mask").hidden = false; };
  $("modal-ok").onclick = () => { $("modal-mask").hidden = true; };
  $("modal-mask").onclick = (e) => { if (e.target.id === "modal-mask") e.target.hidden = true; };
  $("share").onclick = async () => {
    const data = {title: t("shareTitle"), text: t("shareText"), url: REPO_URL};
    try {
      if (navigator.share) { await navigator.share(data); return; }
      throw new Error("no-share");
    } catch (e) {
      try {
        await navigator.clipboard.writeText(`${data.text} ${REPO_URL}`);
        logLine(t("shareCopied"), "ok");
      } catch (_) { prompt(t("sharePrompt"), REPO_URL); }
    }
  };
  $("ribbon").onclick = () => {
    const b = $("console-body");
    const hidden = b.style.display === "none";
    b.style.display = hidden ? "" : "none";
    $("ribbon").textContent = hidden ? t("ribbonHide") : t("ribbonShow");
  };
  $("start").onclick = async () => {
    const body = collectStart();
    if (body.mode === "at" && !body.at) { logLine(t("startNeedTime"), "warn"); return; }
    try {
      await api("/api/start", {method: "POST",
        headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
      logLine(t("startOk"), "ok");
    } catch (e) { logLine(t("startFail") + e.message, "err"); }
  };
  $("stop").onclick = async () => {
    try { await api("/api/stop", {method: "POST"}); logLine(t("stopOk")); }
    catch (e) { logLine(t("stopFail") + e.message, "err"); }
  };
  $("refresh").onclick = async () => {
    try { await api("/api/refresh", {method: "POST"}); logLine(t("refreshOk"), "ok"); }
    catch (e) { logLine(t("refreshFail") + e.message, "err"); }
  };
  $("login").onclick = async () => {
    try {
      await api("/api/login", {method: "POST"});
      logLine(t("loginOk"), "ok");
    } catch (e) { logLine(t("loginFail") + e.message, "err"); }
  };
});
