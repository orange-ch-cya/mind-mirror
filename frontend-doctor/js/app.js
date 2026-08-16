/* 心镜 · 医生/家长/管理端 SPA（文档第四、五章）
   路由：#/invites 邀请码 | #/reports 报告 | #/report/:id 报告详情
        #/scales 量表库 | #/scale/:id 量表编辑 | #/rules 分科规则
        #/push-rules 推送规则 | #/users 账号 | #/configs 配置 | #/logs 日志
   分步展示（文档 10.3）：报告先看状态描述，主动点击后才展开分科参考建议。 */

(() => {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (iso) => (iso ? iso.replace("T", " ").slice(0, 19) : "—");

  const STATUS_LABEL = {
    unused: "未使用", used: "已填", viewed: "已阅", revoked: "已撤回",
    cancelled: "已作废", expired: "已过期",
    active: "启用", inactive: "停用", disabled: "停用",
  };
  const badge = (s) => `<span class="badge ${esc(s)}">${STATUS_LABEL[s] || s}</span>`;

  // ---------- 弹层 ----------
  const openModal = (html) => {
    $("#modal-box").innerHTML = html;
    $("#modal").classList.remove("hidden");
  };
  const closeModal = () => $("#modal").classList.add("hidden");
  $("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });

  // ---------- 认证 ----------
  let lastLoginPassword = "";   // 用于首次改密时校验旧密码
  const showAuth = (user) => {
    $("#view-login").classList.add("hidden");
    $("#view-force-pwd").classList.add("hidden");
    $("#view-app").classList.remove("hidden");
    $("#side-user-name").textContent = `${user.display_name || user.username}（${user.role}）`;
    renderNav();
    route();
  };

  const requireAuth = async () => {
    if (!Api.token) { $("#view-app").classList.add("hidden"); $("#view-login").classList.remove("hidden"); return; }
    try {
      const me = await Api.get("/api/v1/auth/me");
      Api.user = me;
      localStorage.setItem("mm_user", JSON.stringify(me));
      if (me.must_change_password) {
        $("#view-login").classList.add("hidden");
        $("#view-app").classList.add("hidden");
        $("#view-force-pwd").classList.remove("hidden");
        return;
      }
      showAuth(me);
    } catch (e) {
      if (e.code === 4007) {
        $("#view-login").classList.add("hidden");
        $("#view-app").classList.add("hidden");
        $("#view-force-pwd").classList.remove("hidden");
        return;
      }
      Api.clearAuth();
      $("#view-app").classList.add("hidden");
      $("#view-login").classList.remove("hidden");
    }
  };

  $("#login-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    $("#login-error").textContent = "";
    try {
      const data = await Api.post("/api/v1/auth/login", {
        username: $("#login-username").value.trim(),
        password: $("#login-password").value,
      });
      lastLoginPassword = $("#login-password").value;
      Api.saveAuth(data.token, data.user);
      if (data.must_change_password) {
        $("#view-login").classList.add("hidden");
        $("#view-force-pwd").classList.remove("hidden");
      } else {
        showAuth(data.user);
      }
    } catch (e) {
      $("#login-error").textContent = e.message;
    }
  });

  $("#force-pwd-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    $("#force-error").textContent = "";
    const n1 = $("#force-new").value, n2 = $("#force-new2").value;
    if (n1 !== n2) { $("#force-error").textContent = "两次输入的新密码不一致"; return; }
    try {
      await Api.post("/api/v1/auth/change-password", {
        old_password: lastLoginPassword, new_password: n1 });
      Api.clearAuth();
      lastLoginPassword = "";
      $("#view-force-pwd").classList.add("hidden");
      $("#view-login").classList.remove("hidden");
      $("#login-error").textContent = "密码已修改，请使用新密码登录";
    } catch (e) {
      $("#force-error").textContent = e.message;
    }
  });

  $("#btn-logout").addEventListener("click", () => {
    Api.clearAuth();
    location.hash = "";
    $("#view-app").classList.add("hidden");
    $("#view-login").classList.remove("hidden");
  });

  // ---------- 导航 ----------
  const NAV = [
    { hash: "#/invites", label: "邀请码管理", roles: ["doctor", "parent"] },
    { hash: "#/reports", label: "报告列表", roles: ["doctor", "parent"] },
    { hash: "#/scales", label: "量表库", roles: ["admin"] },
    { hash: "#/rules", label: "分科规则", roles: ["admin"] },
    { hash: "#/push-rules", label: "推送规则", roles: ["admin"] },
    { hash: "#/users", label: "账号管理", roles: ["admin"] },
    { hash: "#/configs", label: "系统配置", roles: ["admin"] },
    { hash: "#/logs", label: "操作日志", roles: ["admin"] },
  ];

  const renderNav = () => {
    const role = Api.user && Api.user.role;
    $("#side-nav").innerHTML = NAV
      .filter((n) => n.roles.includes(role))
      .map((n) => `<button data-hash="${n.hash}">${n.label}</button>`).join("");
    $$("#side-nav button").forEach((b) =>
      b.addEventListener("click", () => { location.hash = b.dataset.hash; }));
  };

  const setActiveNav = () => {
    $$("#side-nav button").forEach((b) =>
      b.classList.toggle("active", location.hash.startsWith(b.dataset.hash)));
  };

  // ---------- 路由 ----------
  const PAGES = {
    "#/invites": invitesPage,
    "#/reports": reportsPage,
    "#/scales": scalesPage,
    "#/rules": rulesPage,
    "#/push-rules": pushRulesPage,
    "#/users": usersPage,
    "#/configs": configsPage,
    "#/logs": logsPage,
  };

  const route = async () => {
    if (!Api.user) return;
    setActiveNav();
    const body = $("#page-body");
    const title = $("#page-title");
    $("#page-actions").innerHTML = "";
    const hash = location.hash || "";
    const defaultHash = Api.user.role === "admin" ? "#/scales" : "#/reports";
    try {
      if (hash.startsWith("#/report/")) {
        const id = Number(hash.split("/")[2]);
        title.textContent = "报告详情";
        await reportPage(body, id);
      } else if (hash.startsWith("#/scale/")) {
        const id = Number(hash.split("/")[2]);
        title.textContent = "量表编辑";
        await scalePage(body, id);
      } else if (PAGES[hash]) {
        title.textContent = PAGES[hash].title || "";
        await PAGES[hash].render(body);
      } else {
        location.hash = defaultHash;
      }
    } catch (e) {
      body.innerHTML = `<div class="card"><p class="tip-err">${esc(e.message)}</p></div>`;
    }
  };
  window.addEventListener("hashchange", route);

  // ---------- 邀请码管理（文档 4.2） ----------
  const invitesPage = {
    title: "邀请码管理",
    state: { status: "", page: 1, search: "" },
    async render(body) {
      const s = this.state;
      body.innerHTML = `
        <div class="filter-bar">
          ${["", "unused", "used", "viewed", "revoked", "cancelled"].map((st) =>
            `<button class="chip ${s.status === st ? "active" : ""}" data-status="${st}">
               ${st ? STATUS_LABEL[st] : "全部"}</button>`).join("")}
          <input id="inv-search" placeholder="搜索邀请码/备注" value="${esc(s.search)}">
        </div>
        <div class="card">
          <table class="tbl">
            <thead><tr><th>邀请码</th><th>状态</th><th>备注</th><th>生成时间</th><th>操作</th></tr></thead>
            <tbody id="inv-tbody"><tr><td colspan="5">加载中...</td></tr></tbody>
          </table>
          <div class="pager" id="inv-pager"></div>
        </div>`;
      $$(".chip").forEach((c) => c.addEventListener("click", () => {
        s.status = c.dataset.status; s.page = 1; this.render(body);
      }));
      $("#inv-search").addEventListener("input", (e) => {
        s.search = e.target.value.trim(); s.page = 1;
        clearTimeout(this._t);
        this._t = setTimeout(() => this.load(body), 300);
      });
      await this.load(body);
    },
    async load(body) {
      const s = this.state;
      const q = new URLSearchParams({ page: s.page, size: 20 });
      if (s.status) q.set("status", s.status);
      if (s.search) q.set("search", s.search);
      const data = await Api.get(`/api/v1/doctor/invite-codes?${q}`);
      $("#inv-tbody").innerHTML = data.items.length ? data.items.map((it) => `
        <tr>
          <td><b>${it.code}</b><br><span class="summary-note">/patient?code=${it.code}</span></td>
          <td>${badge(it.status)}</td>
          <td>${esc(it.remark || "—")}</td>
          <td>${fmt(it.generated_at)}</td>
          <td>
            <button class="btn-sm ghost" data-copy="${it.code}">复制链接</button>
            ${it.status === "unused" ? `<button class="btn-sm danger" data-cancel="${it.id}">作废</button>` : ""}
          </td>
        </tr>`).join("") : `<tr><td colspan="5">暂无数据</td></tr>`;
      $("#inv-pager").innerHTML = `
        <button ${s.page <= 1 ? "disabled" : ""} data-pg="prev">上一页</button>
        <span>第 ${data.page} / ${Math.max(1, Math.ceil(data.total / data.size))} 页（共 ${data.total} 条）</span>
        <button ${data.page * data.size >= data.total ? "disabled" : ""} data-pg="next">下一页</button>`;
      $$("#inv-pager button").forEach((b) => b.addEventListener("click", () => {
        s.page += b.dataset.pg === "prev" ? -1 : 1; this.load(body);
      }));
      $$("[data-copy]").forEach((b) => b.addEventListener("click", () => {
        navigator.clipboard.writeText(`${location.origin}/patient?code=${b.dataset.copy}`);
        alert("患者链接已复制");
      }));
      $$("[data-cancel]").forEach((b) => b.addEventListener("click", async () => {
        if (!confirm("确定作废该邀请码？")) return;
        await Api.patch(`/api/v1/doctor/invite-codes/${b.dataset.cancel}`, { action: "cancel" });
        this.load(body);
      }));
    },
  };

  // ---------- 报告列表（文档 4.3） ----------
  const reportsPage = {
    title: "报告列表",
    state: { status: "", page: 1 },
    async render(body) {
      const s = this.state;
      body.innerHTML = `
        <div class="filter-bar">
          ${["", "used", "viewed", "revoked"].map((st) =>
            `<button class="chip ${s.status === st ? "active" : ""}" data-status="${st}">
               ${st ? STATUS_LABEL[st] : "全部"}</button>`).join("")}
        </div>
        <div class="card">
          <table class="tbl">
            <thead><tr><th>邀请码</th><th>备注</th><th>组合包</th><th>完成时间</th><th>状态</th><th></th></tr></thead>
            <tbody id="rep-tbody"><tr><td colspan="6">加载中...</td></tr></tbody>
          </table>
          <div class="pager" id="rep-pager"></div>
        </div>`;
      $$(".chip").forEach((c) => c.addEventListener("click", () => {
        s.status = c.dataset.status; s.page = 1; this.render(body);
      }));
      await this.load(body);
    },
    async load(body) {
      const s = this.state;
      const q = new URLSearchParams({ page: s.page, size: 20 });
      if (s.status) q.set("status", s.status);
      const data = await Api.get(`/api/v1/doctor/reports?${q}`);
      $("#rep-tbody").innerHTML = data.items.length ? data.items.map((it) => `
        <tr>
          <td><b>${it.invite_code}</b></td>
          <td>${esc(it.remark || "—")}</td>
          <td>${esc(it.package_name || "—")}</td>
          <td>${fmt(it.completed_at)}</td>
          <td>${badge(it.invite_status)}</td>
          <td>${it.invite_status !== "revoked"
            ? `<a class="btn-sm primary" href="#/report/${it.session_id}">查看报告</a>`
            : `<span class="summary-note">已撤回</span>`}</td>
        </tr>`).join("") : `<tr><td colspan="6">暂无数据</td></tr>`;
      $("#rep-pager").innerHTML = `
        <button ${s.page <= 1 ? "disabled" : ""} data-pg="prev">上一页</button>
        <span>第 ${data.page} / ${Math.max(1, Math.ceil(data.total / data.size))} 页（共 ${data.total} 条）</span>
        <button ${data.page * data.size >= data.total ? "disabled" : ""} data-pg="next">下一页</button>`;
      $$("#rep-pager button").forEach((b) => b.addEventListener("click", () => {
        s.page += b.dataset.pg === "prev" ? -1 : 1; this.load(body);
      }));
    },
  };

  // ---------- 报告详情（文档 4.3 / 10.3） ----------
  const reportPage = async (body, sessionId) => {
    const rep = await Api.get(`/api/v1/doctor/reports/${sessionId}`);
    const ov = rep.overview;

    const dimBars = (dims) => Object.entries(dims || {}).map(([d, e]) => `
      <div class="dim-row">
        <span style="width:110px">${esc(d)}</span>
        <div class="dim-bar"><i style="width:${Math.min(100, (e.score / Math.max(1, e.max)) * 100)}%"></i></div>
        <span>${e.score} / ${e.max}</span>
      </div>`).join("");

    const scaleBlocks = rep.scales.map((s) => {
      const labels = (rep.per_scale_labels || {})[s.scale_id] || [];
      return `
      <div class="report-block">
        <h3>${esc(s.name_zh)}（${esc(s.abbreviation || "")}）</h3>
        <p class="report-meta">${esc(s.source || "")}</p>
        ${s.description ? `<p style="margin:6px 0">${esc(s.description)}</p>` : ""}
        <div class="card">
          <b>总分 ${s.score.total_score} / ${s.score.max_score}</b>
          <div class="summary-note">${esc((s.norm && s.norm.mean != null)
            ? normText(s.score.total_score, s.norm) : "暂无适用常模数据")}</div>
          ${dimBars(s.score.dimension_scores)}
        </div>
        ${labels.length ? `<div class="card"><h3>分科参考标签</h3>${labels.map((l) =>
          `<div class="referral-card ${esc(l.style)}">${esc(l.label)}</div>`).join("")}</div>` : ""}
        <div class="card">
          <h3>逐题作答记录</h3>
          <table class="tbl">
            <thead><tr><th>题号</th><th>题目</th><th>患者选择</th><th>得分</th></tr></thead>
            <tbody>${s.items.map((it) => `
              <tr><td>${it.item_number}</td><td>${esc(it.item_text)}</td>
              <td><b>${esc(it.chosen_text || "—")}</b></td>
              <td>${it.final_score ?? it.raw_score}</td></tr>`).join("")}
            </tbody>
          </table>
        </div>
      </div>`;
    }).join("");

    body.innerHTML = `
      <div class="card">
        <h3>报告概览</h3>
        <p>邀请码：<b>${ov.invite_code}</b>　备注：${esc(ov.remark || "—")}</p>
        <p>测评完成时间：${fmt(ov.completed_at)}　组合包：${esc(ov.package_name || "—")}</p>
        <p>知情同意：${ov.consent.given ? `已签署（${fmt(ov.consent.at)}）` : "未签署"}
          <span class="summary-note">（知情同意为数据归属追溯凭证，不可篡改）</span></p>
        <table class="tbl" style="margin-top:10px">
          <thead><tr><th>量表</th><th>缩写</th><th>总分</th><th>满分</th></tr></thead>
          <tbody>${(ov.summary || []).map((r) => `
            <tr><td>${esc(r.name_zh)}</td><td>${esc(r.abbreviation || "")}</td>
            <td><b>${r.total_score}</b></td><td>${r.max_score}</td></tr>`).join("")}</tbody>
        </table>
      </div>
      ${scaleBlocks}
      <div class="card">
        <h3>综合分科参考建议</h3>
        <p class="summary-note">以下建议基于量表得分组合生成，仅供专业人士参考，请结合临床面诊综合判断。</p>
        <div id="staged-labels" class="hidden">
          ${rep.referral_labels.length
            ? rep.referral_labels.map((l) =>
                `<div class="referral-card ${esc(l.style)}">
                   <b>${esc(l.rule_name)}</b><br>${esc(l.label)}
                   ${l.tags.length ? `<div class="summary-note">场景标签：${esc(l.tags.join("、"))}</div>` : ""}
                 </div>`).join("")
            : "<p class='summary-note'>当前得分组合未触发分科建议。</p>"}
        </div>
        <button class="btn-ghost btn-sm staged-btn" id="btn-staged">查看分科参考建议</button>
      </div>
      <div class="card">
        <h3>报告尾部</h3>
        <p class="report-meta">${esc(rep.disclaimer)}</p>
        <p class="report-meta">报告生成时间：${fmt(rep.generated_at)}</p>
        <p class="report-meta">${esc(rep.copyright)}</p>
      </div>
      <div style="display:flex;gap:10px">
        <button class="btn-primary" style="width:auto" data-export="pdf">导出 PDF</button>
        <button class="btn-ghost" style="width:auto" data-export="excel">导出 Excel</button>
        <button class="btn-ghost" style="width:auto" onclick="location.hash='#/reports'">返回列表</button>
      </div>`;

    $("#btn-staged").addEventListener("click", () => {
      $("#staged-labels").classList.remove("hidden");
      $("#btn-staged").classList.add("hidden");
    });
    $$("[data-export]").forEach((b) => b.addEventListener("click", async () => {
      b.disabled = true;
      try {
        const blob = await Api.get(
          `/api/v1/doctor/reports/${sessionId}/export/${b.dataset.export}`, true);
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `心镜报告-${ov.invite_code}.${b.dataset.export === "pdf" ? "pdf" : "xlsx"}`;
        a.click();
      } catch (e) { alert(e.message); }
      b.disabled = false;
    }));
  };

  const normText = (score, norm) => {
    const z = (score - norm.mean) / (norm.std_dev || 1);
    if (z <= -0.5) return "低于常见人群平均水平";
    if (z <= 0.5) return "处于常见人群平均水平范围";
    if (z <= 1.0) return "处于中等偏高水平";
    if (z <= 1.5) return "处于偏高水平，值得关注";
    return "处于显著偏高水平，建议优先关注";
  };

  // ---------- 量表库（文档 5.2） ----------
  const scalesPage = {
    title: "量表库管理",
    state: { search: "", status: "", page: 1 },
    async render(body) {
      const s = this.state;
      body.innerHTML = `
        <div class="filter-bar">
          <input id="sc-search" placeholder="搜索名称/缩写" value="${esc(s.search)}">
          <select id="sc-status">
            <option value="">全部状态</option>
            <option value="active" ${s.status === "active" ? "selected" : ""}>启用</option>
            <option value="inactive" ${s.status === "inactive" ? "selected" : ""}>停用</option>
          </select>
          <button class="btn-primary" id="btn-new-scale" style="width:auto">+ 新增量表</button>
        </div>
        <div class="card">
          <table class="tbl">
            <thead><tr><th>ID</th><th>中文名称</th><th>缩写</th><th>题数</th><th>状态</th><th>操作</th></tr></thead>
            <tbody id="sc-tbody"><tr><td colspan="6">加载中...</td></tr></tbody>
          </table>
          <div class="pager" id="sc-pager"></div>
        </div>`;
      $("#btn-new-scale").addEventListener("click", () => scaleFormModal(null, () => this.render(body)));
      $("#sc-search").addEventListener("input", (e) => {
        s.search = e.target.value.trim(); s.page = 1;
        clearTimeout(this._t); this._t = setTimeout(() => this.render(body), 300);
      });
      $("#sc-status").addEventListener("change", (e) => { s.status = e.target.value; s.page = 1; this.render(body); });
      await this.load(body);
    },
    async load(body) {
      const s = this.state;
      const q = new URLSearchParams({ page: s.page, size: 20 });
      if (s.search) q.set("search", s.search);
      if (s.status) q.set("status", s.status);
      const data = await Api.get(`/api/v1/admin/scales?${q}`);
      $("#sc-tbody").innerHTML = data.items.length ? data.items.map((it) => `
        <tr>
          <td>${it.id}</td><td><a href="#/scale/${it.id}">${esc(it.name_zh)}</a></td>
          <td>${esc(it.abbreviation || "—")}</td><td>${it.item_count}</td>
          <td>${badge(it.status)}</td>
          <td>
            <a class="btn-sm ghost" href="#/scale/${it.id}">编辑/条目</a>
            <button class="btn-sm ghost" data-edit="${it.id}">基本信息</button>
            <button class="btn-sm ${it.status === "active" ? "danger" : "success"}" data-toggle="${it.id}">
              ${it.status === "active" ? "停用" : "启用"}</button>
          </td>
        </tr>`).join("") : `<tr><td colspan="6">暂无数据</td></tr>`;
      $$("[data-edit]").forEach((b) => b.addEventListener("click", () => {
        const it = data.items.find((x) => x.id == b.dataset.edit);
        scaleFormModal(it, () => this.render(body));
      }));
      $$("[data-toggle]").forEach((b) => b.addEventListener("click", async () => {
        await Api.put(`/api/v1/admin/scales/${b.dataset.toggle}`, { status: "inactive" });
        this.render(body);
      }));
      $("#sc-pager").innerHTML = `
        <button ${s.page <= 1 ? "disabled" : ""} data-pg="prev">上一页</button>
        <span>第 ${data.page} 页 / 共 ${data.total} 条</span>
        <button ${data.page * data.size >= data.total ? "disabled" : ""} data-pg="next">下一页</button>`;
      $$("#sc-pager button").forEach((b) => b.addEventListener("click", () => {
        s.page += b.dataset.pg === "prev" ? -1 : 1; this.load(body);
      }));
    },
  };

  const scaleFormModal = (scale, onDone) => {
    openModal(`
      <h3>${scale ? "编辑量表基本信息" : "新增量表"}</h3>
      <div class="form-grid">
        <label class="fld">中文名称 *<input id="f-name" value="${esc(scale?.name_zh || "")}"></label>
        <label class="fld">英文缩写<input id="f-abbr" value="${esc(scale?.abbreviation || "")}"></label>
        <label class="fld">英文名称<input id="f-nameen" value="${esc(scale?.name_en || "")}"></label>
        <label class="fld">预计用时(分钟)<input id="f-min" type="number" value="${scale?.estimated_minutes ?? ""}"></label>
        <label class="fld full">来源与版权<textarea id="f-source">${esc(scale?.source || "")}</textarea></label>
        <label class="fld full">量表简介（报告中展示）<textarea id="f-desc">${esc(scale?.description || "")}</textarea></label>
        <label class="fld full">适用人群（逗号分隔）<input id="f-pop" value="${esc(scale?.target_population || "")}"></label>
      </div>
      <div style="display:flex;gap:10px;margin-top:16px">
        <button class="btn-primary" id="f-save">保存</button>
        <button class="btn-ghost" id="f-cancel">取消</button>
      </div>`);
    $("#f-cancel").addEventListener("click", closeModal);
    $("#f-save").addEventListener("click", async () => {
      const payload = {
        name_zh: $("#f-name").value.trim(),
        abbreviation: $("#f-abbr").value.trim(),
        name_en: $("#f-nameen").value.trim() || null,
        estimated_minutes: parseInt($("#f-min").value) || null,
        source: $("#f-source").value,
        description: $("#f-desc").value,
        target_population: $("#f-pop").value.trim() || null,
      };
      if (!payload.name_zh) { alert("中文名称为必填"); return; }
      try {
        if (scale) await Api.put(`/api/v1/admin/scales/${scale.id}`, payload);
        else await Api.post("/api/v1/admin/scales", payload);
        closeModal(); onDone();
      } catch (e) { alert(e.message); }
    });
  };

  // ---------- 量表编辑页（条目管理，文档 5.2） ----------
  const scalePage = async (body, scaleId) => {
    const data = await Api.get(`/api/v1/admin/scales/${scaleId}/items`);
    const scale = data.scale;
    body.innerHTML = `
      <div class="card">
        <h3>${esc(scale.name_zh)}（${esc(scale.abbreviation || "")}）· 共 ${data.items.length} 题</h3>
        <p class="report-meta">${esc(scale.source || "")}</p>
        <button class="btn-primary" id="btn-add-item" style="width:auto;margin-top:8px">+ 添加条目</button>
      </div>
      <div class="card">
        <table class="tbl">
          <thead><tr><th>题号</th><th>题目</th><th>选项</th><th>维度</th><th>反向</th><th>操作</th></tr></thead>
          <tbody>${data.items.map((it) => `
            <tr>
              <td>${it.item_number}</td>
              <td>${esc(it.item_text)}</td>
              <td><span class="summary-note">${esc(it.options.map((o) => `${o.text}(${o.score})`).join(" / "))}</span></td>
              <td>${esc(it.dimension || "—")}</td>
              <td>${it.is_reversed ? "是" : ""}</td>
              <td>
                <button class="btn-sm ghost" data-edit-item="${it.id}">编辑</button>
                <button class="btn-sm danger" data-del-item="${it.id}">删除</button>
              </td>
            </tr>`).join("")}
          </tbody>
        </table>
        <button class="btn-ghost" style="margin-top:12px" onclick="location.hash='#/scales'">返回量表库</button>
      </div>`;

    $("#btn-add-item").addEventListener("click", () => itemFormModal(scaleId, null, () => scalePage(body, scaleId)));
    $$("[data-edit-item]").forEach((b) => b.addEventListener("click", () => {
      const it = data.items.find((x) => x.id == b.dataset.editItem);
      itemFormModal(scaleId, it, () => scalePage(body, scaleId));
    }));
    $$("[data-del-item]").forEach((b) => b.addEventListener("click", async () => {
      if (!confirm("确定删除该条目？")) return;
      await Api.del(`/api/v1/admin/scales/${scaleId}/items/${b.dataset.delItem}`);
      scalePage(body, scaleId);
    }));
  };

  const itemFormModal = (scaleId, item, onDone) => {
    openModal(`
      <h3>${item ? `编辑第 ${item.item_number} 题` : "新增条目"}</h3>
      <div class="form-grid">
        <label class="fld">题号<input id="it-no" type="number" value="${item?.item_number ?? ""}"></label>
        <label class="fld">维度<input id="it-dim" value="${esc(item?.dimension || "")}"></label>
        <label class="fld full">题目文本<textarea id="it-text">${esc(item?.item_text || "")}</textarea></label>
        <label class="fld full">选项（每行一个：文本=分值，如 完全没有=0）<textarea id="it-options">${
          (item?.options || [{ text: "", score: 0 }]).map((o) => `${o.text}=${o.score}`).join("\n")}</textarea></label>
        <label class="fld full"><input type="checkbox" id="it-rev" ${item?.is_reversed ? "checked" : ""}> 反向计分</label>
      </div>
      <div style="display:flex;gap:10px;margin-top:16px">
        <button class="btn-primary" id="it-save">保存</button>
        <button class="btn-ghost" id="it-cancel">取消</button>
      </div>`);
    $("#it-cancel").addEventListener("click", closeModal);
    $("#it-save").addEventListener("click", async () => {
      const options = $("#it-options").value.split("\n").map((l) => l.trim())
        .filter(Boolean).map((l) => {
          const m = l.match(/^(.*)=(-?\d+)$/);
          return m ? { text: m[1].trim(), score: Number(m[2]) } : null;
        }).filter(Boolean);
      if (!options.length) { alert("选项格式错误，请按 文本=分值 填写"); return; }
      const payload = {
        item_number: parseInt($("#it-no").value),
        item_text: $("#it-text").value.trim(),
        options, is_reversed: $("#it-rev").checked,
        dimension: $("#it-dim").value.trim() || null,
      };
      try {
        if (item) await Api.put(`/api/v1/admin/scales/${scaleId}/items/${item.id}`, payload);
        else await Api.post(`/api/v1/admin/scales/${scaleId}/items`, payload);
        closeModal(); onDone();
      } catch (e) { alert(e.message); }
    });
  };

  // ---------- 分科规则（文档 5.4） ----------
  const rulesPage = {
    title: "分科规则",
    async render(body) {
      const data = await Api.get("/api/v1/admin/rules");
      body.innerHTML = `
        <div style="margin-bottom:12px"><button class="btn-primary" id="btn-new-rule" style="width:auto">+ 新增规则</button></div>
        <div class="card">
          <table class="tbl">
            <thead><tr><th>优先级</th><th>规则名称</th><th>条件</th><th>医生版标签</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>${data.items.map((r) => `
              <tr>
                <td>${r.priority}</td><td>${esc(r.name)}</td>
                <td><span class="summary-note">${esc(r.condition_json)}</span></td>
                <td>${esc(r.output_label_doctor)}</td>
                <td>${badge(r.status)}</td>
                <td>
                  <button class="btn-sm ghost" data-edit-rule="${r.id}">编辑</button>
                  <button class="btn-sm ghost" data-test-rule>测试</button>
                  <button class="btn-sm ${r.status === "active" ? "danger" : "success"}" data-toggle-rule="${r.id}">
                    ${r.status === "active" ? "停用" : "启用"}</button>
                </td>
              </tr>`).join("")}
            </tbody>
          </table>
        </div>`;
      $("#btn-new-rule").addEventListener("click", () => ruleFormModal(null, () => this.render(body)));
      $$("[data-edit-rule]").forEach((b) => b.addEventListener("click", () => {
        const r = data.items.find((x) => x.id == b.dataset.editRule);
        ruleFormModal(r, () => this.render(body));
      }));
      $$("[data-test-rule]").forEach((b) => b.addEventListener("click", () => ruleTestModal(data.items)));
      $$("[data-toggle-rule]").forEach((b) => b.addEventListener("click", async () => {
        const r = data.items.find((x) => x.id == b.dataset.toggleRule);
        await Api.put(`/api/v1/admin/rules/${r.id}`, { status: r.status === "active" ? "inactive" : "active" });
        this.render(body);
      }));
    },
  };

  const ruleFormModal = (rule, onDone) => {
    openModal(`
      <h3>${rule ? "编辑分科规则" : "新增分科规则"}</h3>
      <div class="form-grid">
        <label class="fld">规则名称 *<input id="r-name" value="${esc(rule?.name || "")}"></label>
        <label class="fld">优先级（小优先）<input id="r-pri" type="number" value="${rule?.priority ?? 100}"></label>
        <label class="fld">样式
          <select id="r-style">
            ${["info", "warning", "alert"].map((s) =>
              `<option value="${s}" ${rule?.output_style === s ? "selected" : ""}>${s}</option>`).join("")}
          </select></label>
        <label class="fld">场景标签（逗号分隔）<input id="r-tags" value="${esc(rule?.output_tags || "")}"></label>
        <label class="fld full">触发条件 JSON *<textarea id="r-cond">${esc(rule?.condition_json || "")}</textarea></label>
        <label class="fld full">医生版标签（简洁专业）*<textarea id="r-doc">${esc(rule?.output_label_doctor || "")}</textarea></label>
        <label class="fld full">家长版标签（详细易懂）<textarea id="r-par">${esc(rule?.output_label_parent || "")}</textarea></label>
      </div>
      <p class="summary-note">条件示例：[{"scale_id":3,"dimension":"total","op":"gte","value":15}]
        （op 支持 gt/gte/lt/lte/eq/between）</p>
      <div style="display:flex;gap:10px;margin-top:12px">
        <button class="btn-primary" id="r-save">保存</button>
        <button class="btn-ghost" id="r-cancel">取消</button>
      </div>`);
    $("#r-cancel").addEventListener("click", closeModal);
    $("#r-save").addEventListener("click", async () => {
      try {
        JSON.parse($("#r-cond").value);
      } catch { alert("触发条件不是合法的 JSON"); return; }
      const payload = {
        name: $("#r-name").value.trim(),
        priority: parseInt($("#r-pri").value) || 100,
        style: $("#r-style").value,
        output_tags: $("#r-tags").value.trim() || null,
        condition_json: $("#r-cond").value.trim(),
        output_label_doctor: $("#r-doc").value.trim(),
        output_label_parent: $("#r-par").value.trim() || null,
      };
      try {
        if (rule) await Api.put(`/api/v1/admin/rules/${rule.id}`, payload);
        else await Api.post("/api/v1/admin/rules", payload);
        closeModal(); onDone();
      } catch (e) { alert(e.message); }
    });
  };

  const ruleTestModal = (rules) => {
    openModal(`
      <h3>规则测试</h3>
      <label class="fld full">模拟分数 JSON<textarea id="rt-scores">{"3":{"total":16,"dimension_scores":{}}}</textarea></label>
      <p class="summary-note">格式：{"量表ID":{"total":总分,"dimension_scores":{"维度":分值}}}</p>
      <div id="rt-result" class="hidden"></div>
      <div style="display:flex;gap:10px;margin-top:12px">
        <button class="btn-primary" id="rt-run" style="width:auto">运行测试</button>
        <button class="btn-ghost" id="rt-close">关闭</button>
      </div>`);
    $("#rt-close").addEventListener("click", closeModal);
    $("#rt-run").addEventListener("click", async () => {
      try {
        const scores = JSON.parse($("#rt-scores").value);
        const res = await Api.post("/api/v1/admin/rules/test", { scores });
        $("#rt-result").classList.remove("hidden");
        $("#rt-result").innerHTML = res.labels.length
          ? res.labels.map((l) => `<div class="referral-card ${esc(l.style)}">${esc(l.rule_name)}：${esc(l.label)}</div>`).join("")
          : "<p class='summary-note'>未触发任何规则</p>";
      } catch (e) { alert(e.message); }
    });
  };

  // ---------- 推送规则（文档 6.1） ----------
  const pushRulesPage = {
    title: "推送规则",
    async render(body) {
      const data = await Api.get("/api/v1/admin/push-rules");
      body.innerHTML = `
        <div style="margin-bottom:12px"><button class="btn-primary" id="btn-new-push" style="width:auto">+ 新增推送规则</button></div>
        <div class="card">
          <table class="tbl">
            <thead><tr><th>优先级</th><th>规则名称</th><th>条件</th><th>组合包ID</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>${data.items.map((r) => `
              <tr>
                <td>${r.priority}</td><td>${esc(r.name)}</td>
                <td><span class="summary-note">${esc(r.condition_json)}</span></td>
                <td>${r.package_id}</td><td>${badge(r.status)}</td>
                <td><button class="btn-sm ghost" data-edit-push="${r.id}">编辑</button></td>
              </tr>`).join("")}
            </tbody>
          </table>
        </div>`;
      $("#btn-new-push").addEventListener("click", () => pushRuleFormModal(null, () => this.render(body)));
      $$("[data-edit-push]").forEach((b) => b.addEventListener("click", () => {
        const r = data.items.find((x) => x.id == b.dataset.editPush);
        pushRuleFormModal(r, () => this.render(body));
      }));
    },
  };

  const pushRuleFormModal = (rule, onDone) => {
    openModal(`
      <h3>${rule ? "编辑推送规则" : "新增推送规则"}</h3>
      <div class="form-grid">
        <label class="fld">规则名称 *<input id="p-name" value="${esc(rule?.name || "")}"></label>
        <label class="fld">优先级（小优先）<input id="p-pri" type="number" value="${rule?.priority ?? 100}"></label>
        <label class="fld">组合包 ID *<input id="p-pkg" type="number" value="${rule?.package_id ?? ""}"></label>
        <label class="fld full">触发条件 JSON *<textarea id="p-cond">${esc(rule?.condition_json || "")}</textarea></label>
      </div>
      <p class="summary-note">条件示例（phq4 维度 anxiety/depression/total；补充题 supplement 维度 sleep/stress）：
        [{"source":"phq4","dimension":"anxiety","op":"gte","value":4}]</p>
      <div style="display:flex;gap:10px;margin-top:12px">
        <button class="btn-primary" id="p-save">保存</button>
        <button class="btn-ghost" id="p-cancel">取消</button>
      </div>`);
    $("#p-cancel").addEventListener("click", closeModal);
    $("#p-save").addEventListener("click", async () => {
      try { JSON.parse($("#p-cond").value); } catch { alert("触发条件不是合法的 JSON"); return; }
      const payload = {
        name: $("#p-name").value.trim(),
        priority: parseInt($("#p-pri").value) || 100,
        package_id: parseInt($("#p-pkg").value),
        condition_json: $("#p-cond").value.trim(),
      };
      try {
        if (rule) await Api.put(`/api/v1/admin/push-rules/${rule.id}`, payload);
        else await Api.post("/api/v1/admin/push-rules", payload);
        closeModal(); onDone();
      } catch (e) { alert(e.message); }
    });
  };

  // ---------- 账号管理（文档 5.5） ----------
  const usersPage = {
    title: "账号管理",
    state: { page: 1 },
    async render(body) {
      const s = this.state;
      body.innerHTML = `
        <div style="margin-bottom:12px"><button class="btn-primary" id="btn-new-user" style="width:auto">+ 创建账号</button></div>
        <div class="card">
          <table class="tbl">
            <thead><tr><th>用户名</th><th>姓名/机构</th><th>角色</th><th>状态</th><th>最后登录</th><th>操作</th></tr></thead>
            <tbody id="u-tbody"><tr><td colspan="6">加载中...</td></tr></tbody>
          </table>
          <div class="pager" id="u-pager"></div>
        </div>`;
      $("#btn-new-user").addEventListener("click", () => userFormModal(null, () => this.render(body)));
      await this.load(body);
    },
    async load(body) {
      const s = this.state;
      const data = await Api.get(`/api/v1/admin/users?page=${s.page}&size=20`);
      const roleLabel = { doctor: "医生", parent: "家长", admin: "管理员" };
      $("#u-tbody").innerHTML = data.items.map((u) => `
        <tr>
          <td>${esc(u.username)}</td><td>${esc(u.display_name || "—")}</td>
          <td>${roleLabel[u.role] || u.role}</td><td>${badge(u.status)}</td>
          <td>${fmt(u.last_login_at)}</td>
          <td>
            ${u.role !== "admin" ? `<button class="btn-sm ghost" data-reset="${u.id}">重置密码</button>
              <button class="btn-sm ${u.status === "active" ? "danger" : "success"}" data-toggle-u="${u.id}">
                ${u.status === "active" ? "停用" : "启用"}</button>` : ""}
          </td>
        </tr>`).join("");
      $("#u-pager").innerHTML = `
        <button ${s.page <= 1 ? "disabled" : ""} data-pg="prev">上一页</button>
        <span>第 ${data.page} 页 / 共 ${data.total} 条</span>
        <button ${data.page * data.size >= data.total ? "disabled" : ""} data-pg="next">下一页</button>`;
      $$("#u-pager button").forEach((b) => b.addEventListener("click", () => {
        s.page += b.dataset.pg === "prev" ? -1 : 1; this.load(body);
      }));
      $$("[data-reset]").forEach((b) => b.addEventListener("click", async () => {
        const r = await Api.post(`/api/v1/admin/users/${b.dataset.reset}/reset-password`, {});
        openModal(`<h3>密码已重置</h3>
          <p>新密码（仅显示一次，请安全告知使用者）：</p>
          <p style="font-size:20px;font-weight:700;padding:10px;background:#F7F9FA;border-radius:8px;text-align:center">${esc(r.new_password)}</p>
          <button class="btn-primary" data-close>知道了</button>`);
        $("#modal [data-close]").addEventListener("click", closeModal);
      }));
      $$("[data-toggle-u]").forEach((b) => b.addEventListener("click", async () => {
        const u = data.items.find((x) => x.id == b.dataset.toggleU);
        await Api.put(`/api/v1/admin/users/${u.id}`, { status: u.status === "active" ? "disabled" : "active" });
        this.render(body);
      }));
    },
  };

  const userFormModal = (user, onDone) => {
    openModal(`
      <h3>创建账号</h3>
      <div class="form-grid">
        <label class="fld">用户名 *<input id="u-name" value="${esc(user?.username || "")}"></label>
        <label class="fld">初始密码 *<input id="u-pwd" value=""></label>
        <label class="fld">姓名/机构<input id="u-display" value="${esc(user?.display_name || "")}"></label>
        <label class="fld">角色
          <select id="u-role"><option value="doctor">医生</option><option value="parent">家长</option></select></label>
      </div>
      <p class="summary-note">初始密码仅本次创建时有效，用户首次登录须修改。</p>
      <div style="display:flex;gap:10px;margin-top:12px">
        <button class="btn-primary" id="u-save">创建</button>
        <button class="btn-ghost" id="u-cancel">取消</button>
      </div>`);
    $("#u-cancel").addEventListener("click", closeModal);
    $("#u-save").addEventListener("click", async () => {
      try {
        await Api.post("/api/v1/admin/users", {
          username: $("#u-name").value.trim(),
          initial_password: $("#u-pwd").value,
          display_name: $("#u-display").value.trim() || null,
          role: $("#u-role").value,
        });
        closeModal(); onDone();
      } catch (e) { alert(e.message); }
    });
  };

  // ---------- 系统配置（文档 5.6） ----------
  const configsPage = {
    title: "系统配置",
    async render(body) {
      const data = await Api.get("/api/v1/admin/configs");
      body.innerHTML = `
        <div class="card">
          <table class="tbl">
            <thead><tr><th>配置项</th><th>值</th><th>类型</th><th>说明</th><th></th></tr></thead>
            <tbody>${data.items.map((c) => `
              <tr>
                <td><b>${esc(c.key)}</b></td>
                <td><span class="summary-note">${esc(c.value)}</span></td>
                <td>${esc(c.value_type)}</td><td>${esc(c.description || "")}</td>
                <td><button class="btn-sm ghost" data-edit-cfg="${esc(c.key)}">编辑</button></td>
              </tr>`).join("")}
            </tbody>
          </table>
        </div>`;
      $$("[data-edit-cfg]").forEach((b) => b.addEventListener("click", () => {
        const c = data.items.find((x) => x.key === b.dataset.editCfg);
        openModal(`
          <h3>编辑配置：${esc(c.key)}</h3>
          <label class="fld">值<textarea id="c-value">${esc(c.value)}</textarea></label>
          <p class="summary-note">JSON/数字/字符串均可，保存后立即生效。</p>
          <div style="display:flex;gap:10px;margin-top:12px">
            <button class="btn-primary" id="c-save">保存</button>
            <button class="btn-ghost" id="c-cancel">取消</button>
          </div>`);
        $("#c-cancel").addEventListener("click", closeModal);
        $("#c-save").addEventListener("click", async () => {
          await Api.put("/api/v1/admin/configs", {
            configs: [{ key: c.key, value: $("#c-value").value }],
          });
          closeModal(); this.render(body);
        });
      }));
    },
  };

  // ---------- 操作日志（文档 7.4） ----------
  const logsPage = {
    title: "操作日志",
    state: { page: 1, action: "" },
    async render(body) {
      const s = this.state;
      body.innerHTML = `
        <div class="filter-bar">
          <select id="log-action">
            <option value="">全部操作</option>
            ${["invite_generate", "invite_cancel", "assessment_submit", "patient_revoke",
               "doctor_view_report", "doctor_export_pdf", "doctor_export_excel",
               "scale_create", "scale_update", "scale_deactivate", "rule_create",
               "user_create", "user_reset_password", "config_update", "norm_create"].map((a) =>
              `<option value="${a}" ${s.action === a ? "selected" : ""}>${a}</option>`).join("")}
          </select>
        </div>
        <div class="card">
          <table class="tbl">
            <thead><tr><th>ID</th><th>操作</th><th>对象</th><th>详情</th><th>时间</th></tr></thead>
            <tbody id="l-tbody"><tr><td colspan="5">加载中...</td></tr></tbody>
          </table>
          <div class="pager" id="l-pager"></div>
        </div>`;
      $("#log-action").addEventListener("change", (e) => { s.action = e.target.value; s.page = 1; this.render(body); });
      await this.load(body);
    },
    async load(body) {
      const s = this.state;
      const q = new URLSearchParams({ page: s.page, size: 20 });
      if (s.action) q.set("action", s.action);
      const data = await Api.get(`/api/v1/admin/logs?${q}`);
      $("#l-tbody").innerHTML = data.items.map((l) => `
        <tr>
          <td>${l.id}</td><td>${esc(l.action)}</td>
          <td>${esc(l.target_type || "")}${l.target_id ? `#${l.target_id}` : ""}</td>
          <td><span class="summary-note">${esc(l.detail || "")}</span></td>
          <td>${fmt(l.created_at)}</td>
        </tr>`).join("");
      $("#l-pager").innerHTML = `
        <button ${s.page <= 1 ? "disabled" : ""} data-pg="prev">上一页</button>
        <span>第 ${data.page} 页 / 共 ${data.total} 条</span>
        <button ${data.page * data.size >= data.total ? "disabled" : ""} data-pg="next">下一页</button>`;
      $$("#l-pager button").forEach((b) => b.addEventListener("click", () => {
        s.page += b.dataset.pg === "prev" ? -1 : 1; this.load(body);
      }));
    },
  };

  // ---------- 启动 ----------
  requireAuth();
})();
