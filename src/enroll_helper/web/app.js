const $ = (id) => document.getElementById(id);
const REPO_URL = "https://github.com/WilloTwisper/SUSTech-CourseCat";
let lastEvent = 0;
let queueNames = [];
let enrolledN = 0;
let page = 1, size = 30;
let facetsLoaded = false;

const TABS = [
  ["yx", "已选"],
  ["bxxk", "通识必修选课"],
  ["xxxk", "通识选修选课"],
  ["kzyxk", "培养方案内课程"],
  ["zynknjxk", "非培养方案内课程"],
  ["cxxk", "重修选课"],
];
let activeTab = "xxxk";

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
  for (const [code, label] of TABS) {
    const b = document.createElement("button");
    b.className = "tab" + (code === activeTab ? " active" : "");
    b.textContent = code === "yx" ? `已选(${enrolledN})` : label;
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
      ? `<div><b>上课信息：</b>${r.sched_tags.map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</div>`
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
  btn.textContent = inQueue ? "已加入" : "选课";
  btn.disabled = !!inQueue;
  btn.onclick = async () => {
    try {
      await api("/api/queue", {method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({names: queueNames.concat([r.task])})});
      await refreshStatus();
    } catch (e) { logLine("加入失败: " + e.message, "err"); }
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
    fill("school", d.schools || [], "请选择");
    fill("cat2", d.categories || [], "课程类别");
  } catch (e) { /* 目录未就绪 */ }
}

function renderPager(total, pg, pages, sz) {
  const box = $("pager");
  box.innerHTML = "";
  const span = (t) => {
    const s = document.createElement("span"); s.textContent = t; box.appendChild(s);
  };
  span(`共 ${total} 条`);
  const btn = (t, p, dis, cur) => {
    const b = document.createElement("button");
    b.textContent = t; b.disabled = !!dis;
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
    o.value = n; o.textContent = `${n}条/页`; if (n === sz) o.selected = true;
    sel.appendChild(o);
  }
  sel.onchange = () => { size = parseInt(sel.value, 10); page = 1; refreshCourses(); };
  box.appendChild(sel);
  span("跳至");
  const inp = document.createElement("input");
  inp.value = pg;
  inp.onkeydown = (e) => {
    if (e.key === "Enter") { page = parseInt(inp.value, 10) || 1; refreshCourses(); }
  };
  box.appendChild(inp);
  span("页");
}

async function refreshCourses() {
  const body = $("course-body");
  try {
    if (activeTab === "yx") {
      const d = await api("/api/enrolled");
      body.innerHTML = "";
      if (!d.enrolled.length) {
        body.innerHTML = `<tr><td colspan="14" style="color:#808695">暂无已选课程（退课请去教务页面手动操作）</td></tr>`;
      }
      for (const e of d.enrolled) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td colspan="2">${esc(e.name)}</td>` +
          `<td colspan="11" class="mini">${esc((e.teachers || []).join("、"))} ${esc(e.schedule || "").slice(0, 120)}</td>` +
          `<td class="mini">${esc(e.id)}</td>`;
        body.appendChild(tr);
      }
      $("pager").innerHTML = `<span>共 ${d.enrolled.length} 门</span>`;
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
      body.innerHTML = `<tr><td colspan="14" style="color:#808695">目录为空：点“刷新目录”（首次约半分钟）</td></tr>`;
      $("pager").innerHTML = "";
      return;
    }
    body.innerHTML = "";
    for (const r of d.courses) body.appendChild(courseRow(r, queueNames.includes(r.task)));
    renderPager(d.total, d.page, d.pages, d.size);
    $("count").textContent = "";
  } catch (e) {
    body.innerHTML = `<tr><td colspan="14" style="color:#ED4014">查询失败: ${esc(e.message)}</td></tr>`;
  }
}

function queueRow(row) {
  const tr = document.createElement("tr");
  if (row.status && row.status !== "等待") tr.className = "qrow";
  tr.innerHTML = `<td>${row.index}</td><td>${esc(row.name)}</td><td>${esc(row.type)}</td>` +
    `<td>${esc(row.seats)}</td>` +
    `<td class="st-${esc(row.status)}">${esc(row.status)} ${esc(row.message).slice(0, 40)}</td>`;
  const td = document.createElement("td");
  const mk = (t, fn) => {
    const b = document.createElement("button");
    b.className = "btn"; b.style.padding = "2px 8px"; b.textContent = t;
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
    if (d.unknown && d.unknown.length) logLine("未找到: " + d.unknown.join("、"), "warn");
    await refreshStatus();
  } catch (e) { logLine("队列更新失败: " + e.message, "err"); }
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
    $("session-badge").textContent = "会话 " + (s.session ? "✓" : "✗（点重新登录）");
    $("semester-label").textContent = s.semester || "…";
    $("xnxq").textContent = s.semester_code || "…";
    queueNames = s.queue.map((r) => r.name);
    const qb = $("queue-body");
    qb.innerHTML = "";
    if (!s.queue.length) {
      qb.innerHTML = `<tr><td colspan="6" style="color:#808695">队列为空：在下方课程表点“选课”加入喵</td></tr>`;
    }
    for (const r of s.queue) qb.appendChild(queueRow(r));
    $("start").disabled = !!s.running;
    const banner = $("phase-text");
    if (s.running) banner.textContent = s.phase === "waiting"
      ? `等待开抢 ${s.target || ""} …（可点停止取消）`
      : "抢课进行中…（串行请求，间隔 ≥1500ms）";
    else if (s.phase === "done") banner.textContent = "本轮结束喵，详见日志。";
    else banner.textContent =
      `${s.semester || "未知学期"} · 待选 ${s.queue.length} 门 · 就绪`;
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
    logLine("状态同步失败: " + e.message, "err");
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
        if (e.status === "SUCCESS") { beep(); document.title = "✓ 选课成功 - 抢课助手"; }
      } else if (e.kind === "done") {
        const s = e.summary;
        logLine(`运行结束: 请求${s.total_requests} 成功${s.successes.length} 跳过${s.skipped.length}`, "ok");
        for (const c of s.successes) logLine("  成功: " + c, "good");
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
  renderTabs(0);
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
  $("star").onclick = () => window.open(REPO_URL, "_blank");
  $("disclaimer").onclick = () => { $("modal-mask").hidden = false; };
  $("modal-ok").onclick = () => { $("modal-mask").hidden = true; };
  $("modal-mask").onclick = (e) => { if (e.target.id === "modal-mask") e.target.hidden = true; };
  $("share").onclick = async () => {
    const data = {title: "抢课猫 CourseCat", text: "南科大 TIS 抢课助手，开源免费", url: REPO_URL};
    try {
      if (navigator.share) { await navigator.share(data); return; }
      throw new Error("no-share");
    } catch (e) {
      try {
        await navigator.clipboard.writeText(`${data.text} ${REPO_URL}`);
        logLine("推荐链接已复制，去发给同学吧", "ok");
      } catch (_) { prompt("复制这个链接发给同学：", REPO_URL); }
    }
  };
  $("ribbon").onclick = () => {
    const b = $("console-body");
    const hidden = b.style.display === "none";
    b.style.display = hidden ? "" : "none";
    $("ribbon").textContent = hidden ? "收起 ▴" : "展开 ▾";
  };
  $("start").onclick = async () => {
    const body = collectStart();
    if (body.mode === "at" && !body.at) { logLine("定时模式请填写开抢时间", "warn"); return; }
    try {
      await api("/api/start", {method: "POST",
        headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
      logLine("已启动…", "ok");
    } catch (e) { logLine("启动失败: " + e.message, "err"); }
  };
  $("stop").onclick = async () => {
    try { await api("/api/stop", {method: "POST"}); logLine("已请求停止…"); }
    catch (e) { logLine("停止失败: " + e.message, "err"); }
  };
  $("refresh").onclick = async () => {
    try { await api("/api/refresh", {method: "POST"}); logLine("开始下载目录（约半分钟）…", "ok"); }
    catch (e) { logLine("刷新失败: " + e.message, "err"); }
  };
  $("login").onclick = async () => {
    try {
      await api("/api/login", {method: "POST"});
      logLine("已打开浏览器，请完成统一身份认证登录…", "ok");
    } catch (e) { logLine("登录失败: " + e.message, "err"); }
  };
});
