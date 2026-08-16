/* 心镜 · 患者端流程控制（文档第三章）
   视图流：首页 → 知情同意 → 快筛(含补充题) → 过渡 → 深度包说明 → 休息页 →
   逐题作答 → 量表确认 → 最终确认 → 结果页（可撤回）。
   断点续答：sessionStorage 保存 {code, sessionId}，刷新后提示继续。 */

(() => {
  "use strict";

  // ---------- 常量：PHQ-4 与补充筛查题（与种子数据一致） ----------
  const PHQ4 = [
    { text: "在过去两周中，您是否经常感到紧张、焦虑或不安？" },
    { text: "在过去两周中，您是否经常无法停止或控制担忧？" },
    { text: "在过去两周中，您是否经常对事情缺乏兴趣或乐趣？" },
    { text: "在过去两周中，您是否经常感到情绪低落、沮丧或绝望？" },
  ];
  const PHQ4_OPTIONS = [
    { text: "完全没有", sub: "从未出现", score: 0 },
    { text: "有几天", sub: "偶尔出现，但不多", score: 1 },
    { text: "一半以上天数", sub: "经常出现，多数日子都有", score: 2 },
    { text: "几乎每天", sub: "几乎每天都出现", score: 3 },
  ];
  const SLEEP_Q = { text: "在过去两周中，您是否经常遇到睡眠问题（如入睡困难、睡眠浅、早醒等）？" };
  const STRESS_Q = { text: "在过去一个月中，您是否经历了重大压力事件（如工作/学业压力、人际关系冲突、重大变故等）？" };
  const STRESS_OPTIONS = [
    { text: "没有", score: 0 },
    { text: "有", score: 1 },
  ];

  const STORE_KEY = "mind_mirror_patient";

  // ---------- 全局状态 ----------
  const state = {
    code: "",
    sessionId: null,
    anonymous: false,         // 匿名自测（无邀请码）
    phq4Answers: [],
    sleepFlag: false,
    stressFlag: false,
    package: null,            // 组合包题目
    answers: {},              // {scale_id: {item_number: score}}
    scaleIndex: 0,            // 当前量表在 package.scales 中的下标
    itemIndex: 0,             // 当前题目在量表 items 中的下标
    editing: false,
    revokeAvailable: false,
  };

  // ---------- 工具 ----------
  const $ = (sel) => document.querySelector(sel);
  const show = (id) => {
    document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
    $(`#view-${id}`).classList.remove("hidden");
    window.scrollTo(0, 0);
  };
  const pick = (arr, n) => {
    const copy = arr.slice();
    const out = [];
    while (copy.length && out.length < n) {
      out.push(copy.splice(Math.floor(Math.random() * copy.length), 1)[0]);
    }
    return out;
  };
  const saveStore = () => {
    sessionStorage.setItem(STORE_KEY, JSON.stringify({
      code: state.code, sessionId: state.sessionId, anonymous: state.anonymous }));
  };
  const clearStore = () => sessionStorage.removeItem(STORE_KEY);

  // 定时器（30 分钟无操作提示，文档 3.5）
  let idleTimer = null;
  const resetIdle = () => {
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = setTimeout(() => {
      $("#modal-timeout").classList.remove("hidden");
    }, 30 * 60 * 1000);
  };
  ["click", "keydown", "touchstart"].forEach((ev) =>
    document.addEventListener(ev, resetIdle, { passive: true }));
  resetIdle();

  // ---------- 首页 ----------
  const initHome = () => {
    const params = new URLSearchParams(location.search);
    const codeParam = (params.get("code") || "").toUpperCase();
    if (codeParam) $("#input-code").value = codeParam;
    const saved = sessionStorage.getItem(STORE_KEY);
    if (saved) {
      try {
        const s = JSON.parse(saved);
        if (s.sessionId) {
          state.code = s.code || "";
          state.sessionId = s.sessionId;
          state.anonymous = !!s.anonymous;
          if (state.anonymous) {
            if (confirm("检测到您有未完成的匿名自测，是否继续上次的进度？")) {
              resumeAnonymous();
              return;
            }
          } else if (s.code) {
            $("#input-code").value = s.code;
            if (confirm("检测到您有未完成的测评，是否继续上次的进度？")) {
              resumeFlow();
              return;
            }
          }
          clearStore();
        }
      } catch (e) { /* 忽略损坏的存储 */ }
    }
    show("home");
  };

  // 匿名自测断点续答
  const resumeAnonymous = async () => {
    try {
      const info = await API.get(`/api/v1/patient/anon-status/${state.sessionId}`);
      if (!info.exists) {
        clearStore();
        show("home");
        return;
      }
      if (info.status === "completed") {
        clearStore();
        await loadResult();
        return;
      }
      if (info.status === "revoked") {
        clearStore();
        show("home");
        return;
      }
      if (!info.resume_available) {
        alert("该匿名自测已超时，需要重新开始。");
        clearStore();
        show("home");
        return;
      }
      if (info.consent_given) {
        await startAssessment();
      } else {
        showConsent();
      }
    } catch (e) {
      alert(e.message);
      clearStore();
      show("home");
    }
  };

  const showConsent = () => {
    $("#anon-consent-note").classList.toggle("hidden", !state.anonymous);
    show("consent");
  };

  const resumeFlow = async () => {
    try {
      const info = await API.post("/api/v1/patient/verify-code", { code: state.code });
      if (!info.resume_available) {
        alert("该测评已超时，需要重新开始。");
        clearStore();
        show("home");
        return;
      }
      state.sessionId = info.session_id;
      saveStore();
      if (info.consent_given) {
        await startAssessment();
      } else {
        showConsent();
      }
    } catch (e) {
      alert(e.message);
      clearStore();
      show("home");
    }
  };

  $("#input-code").addEventListener("input", (e) => {
    const v = e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, "");
    e.target.value = v;
    $("#btn-start").disabled = v.length !== 8;
    $("#code-tip").classList.add("hidden");
  });

  $("#btn-start").addEventListener("click", async () => {
    state.code = $("#input-code").value;
    $("#btn-start").disabled = true;
    try {
      const info = await API.post("/api/v1/patient/verify-code", { code: state.code });
      if (info.has_in_progress_session && info.resume_available) {
        if (confirm("检测到您有未完成的测评，是否继续上次的进度？")) {
          state.sessionId = info.session_id;
          saveStore();
          if (info.consent_given) {
            await startAssessment();
          } else {
            show("consent");
          }
          return;
        }
        // 不续答则继续新流程（重新开始：覆盖会话）
        clearStore();
      }
      state.sessionId = info.session_id;
      saveStore();
      showConsent();
    } catch (e) {
      $("#code-tip").textContent = e.message;
      $("#code-tip").classList.remove("hidden");
    } finally {
      $("#btn-start").disabled = $("#input-code").value.length !== 8;
    }
  });

  // 了解更多
  $("#btn-more-info").addEventListener("click", () => {
    $("#more-info").classList.toggle("hidden");
    $("#btn-more-info").textContent =
      $("#more-info").classList.contains("hidden") ? "了解更多" : "收起";
  });

  // ---------- 匿名自测（文档 3.1/3.2：开放自测，同样须经知情同意） ----------
  $("#btn-anon").addEventListener("click", () => {
    $("#modal-anon").classList.remove("hidden");
  });
  document.querySelectorAll("[data-close-modal]").forEach((b) =>
    b.addEventListener("click", () => b.closest(".modal").classList.add("hidden")));

  $("#btn-anon-start").addEventListener("click", async () => {
    $("#modal-anon").classList.add("hidden");
    try {
      const data = await API.post("/api/v1/patient/anonymous-start", {});
      state.sessionId = data.session_id;
      state.anonymous = true;
      state.code = "";
      saveStore();
      showConsent();
    } catch (e) {
      alert(e.message);
    }
  });

  // ---------- 知情同意 ----------
  $("#consent-check").addEventListener("change", (e) => {
    $("#btn-consent-start").disabled = !e.target.checked;
  });

  $("#btn-consent-start").addEventListener("click", async () => {
    try {
      if (state.anonymous) {
        await API.post("/api/v1/patient/consent", {
          session_id: state.sessionId, anonymous: true, consent: true });
      } else {
        await API.post("/api/v1/patient/consent", { code: state.code, consent: true });
      }
      startScreening();
    } catch (e) {
      alert(e.message);
    }
  });

  // 通用返回链接
  document.querySelectorAll("[data-go]").forEach((b) =>
    b.addEventListener("click", () => {
      location.hash = b.dataset.go;
      const id = b.dataset.go.replace("#", "");
      show(id);
    }));

  // ---------- 快速筛查 ----------
  const SCREEN_TOTAL = PHQ4.length + 2; // 4 题 + 睡眠/压力补充题
  let screenStep = 0;                   // 0..5
  let screenFlag = false;               // 是否已进入补充题

  const startScreening = () => {
    screenStep = 0;
    screenFlag = false;
    state.phq4Answers = [];
    state.sleepFlag = false;
    state.stressFlag = false;
    show("screening");
    renderScreeningStep();
  };

  const renderScreeningStep = () => {
    if (screenStep < PHQ4.length) {
      $("#screen-question").textContent = PHQ4[screenStep].text;
      renderOptions("#screen-options", PHQ4_OPTIONS, onScreeningPick);
    } else if (screenStep === PHQ4.length) {
      $("#screen-question").textContent = SLEEP_Q.text;
      renderOptions("#screen-options", PHQ4_OPTIONS, onScreeningPick);
    } else {
      $("#screen-question").textContent = STRESS_Q.text;
      renderOptions("#screen-options", STRESS_OPTIONS, onScreeningPick);
    }
    $("#screen-no").textContent = String(screenStep + 1);
    $("#screen-total").textContent = String(SCREEN_TOTAL);
    $("#screen-bar").style.width = `${((screenStep + 1) / SCREEN_TOTAL) * 100}%`;
  };

  const onScreeningPick = (opt) => {
    if (screenStep < PHQ4.length) {
      state.phq4Answers.push(opt.score);
    } else if (screenStep === PHQ4.length) {
      state.sleepFlag = opt.score >= 2;   // 一半以上天数/几乎每天 → 触发
    } else {
      state.stressFlag = opt.score === 1; // 肯定回答 → 触发
    }
    screenStep += 1;
    if (screenStep >= SCREEN_TOTAL) {
      setTimeout(() => show("transition"), 320);
      setTimeout(submitPhq4, 2600);       // 过渡动画约 2-3 秒（文档 3.4）
    } else {
      setTimeout(renderScreeningStep, 300); // 300ms 确认延迟后自动推进（文档 3.3）
    }
  };

  const submitPhq4 = async () => {
    try {
      const result = await API.post("/api/v1/patient/phq4-submit", {
        session_id: state.sessionId,
        answers: state.phq4Answers,
        sleep_flag: state.sleepFlag,
        stress_flag: state.stressFlag,
      });
      if (result.need_deep_assessment) {
        state.package = await API.get(
          `/api/v1/patient/package-detail/${state.sessionId}`);
        renderIntro();
        show("intro");
      } else {
        await loadResult();
      }
    } catch (e) {
      alert(e.message);
      show("home");
    }
  };

  const renderIntro = () => {
    const pkg = state.package;
    const minutes = pkg.scales.reduce((s, x) => s + (x.estimated_minutes || 2), 0);
    $("#intro-text").textContent =
      `根据您刚才的快速筛查，系统为您准备了一套更详细的问卷，大约需要 ${minutes} 分钟完成。` +
      `这将帮助邀请您的人士更全面地了解您的情况。请认真作答，您的每一道回答都很重要。`;
    $("#intro-scales").innerHTML = pkg.scales
      .map((s) => `<li>${s.name_zh}（${s.item_count} 题）</li>`).join("");
  };

  $("#btn-intro-start").addEventListener("click", () => startAssessment());

  // ---------- 深度作答 ----------
  const startAssessment = async () => {
    if (!state.package) {
      state.package = await API.get(
        `/api/v1/patient/package-detail/${state.sessionId}`);
    }
    // 恢复已作答
    const saved = await API.get(`/api/v1/patient/session-answers/${state.sessionId}`);
    state.answers = saved || {};

    // 找到第一个未完成的量表
    state.scaleIndex = 0;
    while (state.scaleIndex < state.package.scales.length) {
      const scale = state.package.scales[state.scaleIndex];
      const answered = Object.keys(state.answers[scale.scale_id] || {}).length;
      if (answered < scale.item_count) break;
      state.scaleIndex += 1;
    }
    if (state.scaleIndex >= state.package.scales.length) {
      renderFinalConfirm();
      show("final-confirm");
      return;
    }
    showScaleBreak(state.scaleIndex);
  };

  const showScaleBreak = (index) => {
    const scale = state.package.scales[index];
    if (index === 0) {
      // 首个量表：直接作答（说明页已在 intro 完成）
      enterScale(index);
      return;
    }
    const prev = state.package.scales[index - 1];
    $("#break-title").textContent = `您已完成「${prev.name_zh}」的作答`;
    $("#break-sub").textContent =
      `接下来是「${scale.name_zh}」，预计需要 ${scale.estimated_minutes || 2} 分钟。` +
      "请稍作休息，准备好后点击继续。";
    show("break");
  };

  $("#btn-break-continue").addEventListener("click", () => {
    enterScale(state.scaleIndex);
  });

  const enterScale = (index) => {
    state.scaleIndex = index;
    const scale = state.package.scales[index];
    const savedMap = state.answers[scale.scale_id] || {};
    // 跳到第一个未答题目
    let i = 0;
    while (i < scale.items.length && savedMap[scale.items[i].item_number] !== undefined) {
      i += 1;
    }
    state.itemIndex = i;
    renderAssessmentItem();
    show("assessment");   // 关键：进入作答视图（此前缺失导致点击"开始答题"无反应）
  };

  const renderAssessmentItem = () => {
    const scale = state.package.scales[state.scaleIndex];
    const item = scale.items[state.itemIndex];
    $("#assess-scale-name").textContent = scale.name_zh;
    $("#assess-count").textContent =
      `第 ${state.itemIndex + 1} 题 / 共 ${scale.item_count} 题`;
    $("#assess-question").textContent = item.item_text;
    renderOptions("#assess-options", item.options, onAssessPick, false);
    // 进度条：整个组合包总进度
    const totalItems = state.package.scales.reduce((s, x) => s + x.item_count, 0);
    let answered = 0;
    for (const sid in state.answers) {
      answered += Object.keys(state.answers[sid]).length;
    }
    const scaleStart = state.package.scales
      .slice(0, state.scaleIndex).reduce((s, x) => s + x.item_count, 0);
    const cur = scaleStart + state.itemIndex + 1;
    $("#assess-bar").style.width = `${(cur / totalItems) * 100}%`;
  };

  const onAssessPick = async (opt, btn) => {
    // 防连点
    const optionsBox = $("#assess-options");
    optionsBox.querySelectorAll("button").forEach((b) => (b.disabled = true));

    const scale = state.package.scales[state.scaleIndex];
    const item = scale.items[state.itemIndex];
    state.answers[scale.scale_id] = state.answers[scale.scale_id] || {};
    // 记录选项下标（患者端不接触分值）
    state.answers[scale.scale_id][item.item_number] = opt.idx;

    // 异步暂存（文档 3.5：每题作答即时保存；传 option_index 由后端映射分值）
    API.post("/api/v1/patient/response", {
      session_id: state.sessionId,
      scale_id: scale.scale_id,
      item_number: item.item_number,
      option_index: opt.idx,
    }).catch(() => { /* 暂存失败由下一次作答/提交兜底 */ });

    setTimeout(() => {
      if (state.itemIndex + 1 >= scale.item_count) {
        renderScaleConfirm();
        show("scale-confirm");
      } else {
        state.itemIndex += 1;
        renderAssessmentItem();
      }
    }, 300); // 300ms 确认延迟（文档 3.3）
  };

  const renderScaleConfirm = () => {
    const scale = state.package.scales[state.scaleIndex];
    $("#scale-confirm-title").textContent = `「${scale.name_zh}」作答确认`;
    const saved = state.answers[scale.scale_id] || {};
    const rows = scale.items.map((item) => {
      const idx = saved[item.item_number];
      const chosen = idx !== undefined ? (item.options[idx]?.text || "已作答") : "未作答";
      return `<div class="answer-row">
        <span class="q-no">第 ${item.item_number} 题</span>
        <button data-jump="${item.item_number}">修改</button>
        <span class="a-text">${chosen}</span>
      </div>`;
    }).join("");
    $("#scale-confirm-list").innerHTML = rows;
    $("#scale-confirm-list").querySelectorAll("[data-jump]").forEach((b) =>
      b.addEventListener("click", () => {
        const num = Number(b.dataset.jump);
        const idx = scale.items.findIndex((it) => it.item_number === num);
        state.itemIndex = idx;
        renderAssessmentItem();
        show("assessment");
      }));
    const isLast = state.scaleIndex >= state.package.scales.length - 1;
    $("#btn-scale-confirm-next").textContent = isLast ? "查看全部完成确认" : "继续下一部分";
  };

  $("#btn-scale-confirm-next").addEventListener("click", () => {
    if (state.scaleIndex + 1 >= state.package.scales.length) {
      renderFinalConfirm();
      show("final-confirm");
    } else {
      state.scaleIndex += 1;
      showScaleBreak(state.scaleIndex);
    }
  });

  const renderFinalConfirm = () => {
    $("#final-confirm-text").textContent =
      "您已完成所有题目。点击提交后，您的答题数据将发送给邀请您的人士。" +
      "提交后 24 小时内您可以撤回数据。请确认您的作答是认真和真实的。";
    $("#final-confirm-list").innerHTML = state.package.scales
      .map((s) => `<li>${s.name_zh}（${s.item_count} 题）</li>`).join("");
  };

  $("#btn-final-submit").addEventListener("click", async () => {
    const btn = $("#btn-final-submit");
    btn.disabled = true;
    btn.textContent = "提交中...";
    try {
      await API.post("/api/v1/patient/submit", { session_id: state.sessionId });
      await loadResult();
    } catch (e) {
      alert(e.message);
      btn.disabled = false;
      btn.textContent = "确认提交";
    }
  });

  // ---------- 结果页 ----------
  const loadResult = async () => {
    const data = await API.get(`/api/v1/patient/result/${state.sessionId}`);
    if (data.status === "in_progress") {
      alert(data.message);
      show("home");
      return;
    }
    if (data.status === "revoked") {
      renderRevoked(data.message);
      return;
    }
    $("#result-closing").textContent = data.closing_message;
    const encouragements = pick(data.encouragements, 2);
    $("#result-encouragements").innerHTML =
      encouragements.map((t) => `<p>${t}</p>`).join("");
    const tips = pick(data.tips, 3);
    $("#result-tips").innerHTML = tips.map((t) => `<li>${t}</li>`).join("");
    $("#result-disclaimer").innerHTML =
      data.disclaimer.map((t) => `<p>${t}</p>`).join("");
    $("#result-contact").textContent = data.contact_hint;
    state.revokeAvailable = data.revoke_available;
    $("#result-revoke").classList.toggle("hidden", !data.revoke_available);
    clearStore();
    show("result");
  };

  // ---------- 撤回（文档 3.7；匿名自测同样适用） ----------
  $("#revoke-input").addEventListener("input", (e) => {
    $("#btn-revoke").disabled = e.target.value.trim() !== "确认撤回";
  });

  // 进入撤回页时按模式调整告知文案
  const showRevoke = () => {
    if (state.anonymous) {
      $("#revoke-consequence").innerHTML =
        "<b>撤回后果：</b>撤回后，您的所有匿名自测数据将被从系统中彻底删除，无法恢复。";
    }
    show("revoke");
  };

  $("#btn-revoke").addEventListener("click", async () => {
    try {
      const body = { confirm_text: "确认撤回" };
      if (!state.anonymous) body.invite_code = state.code;
      await API.post(`/api/v1/patient/revoke/${state.sessionId}`, body);
      renderRevoked(state.anonymous
        ? "您的匿名自测数据已成功撤回并删除。感谢您的参与，祝您一切安好。"
        : "您的数据已成功撤回并删除。邀请码已作废。如需重新测评，请联系邀请您的人士获取新的邀请码。感谢您的参与，祝您一切安好。");
    } catch (e) {
      $("#revoke-tip").textContent = e.message;
    }
  });

  const renderRevoked = (message) => {
    $("#revoke-tip").textContent = "";
    $("#revoke-input").classList.add("hidden");
    $("#btn-revoke").classList.add("hidden");
    $("#revoke-tip").textContent = message;
    $("#revoke-tip").classList.remove("hidden");
  };

  // ---------- 通用选项渲染 ----------
  const renderOptions = (containerSel, options, onPick, showSub = true) => {
    const box = $(containerSel);
    box.innerHTML = "";
    options.forEach((opt, idx) => {
      const btn = document.createElement("button");
      btn.className = "option-btn";
      btn.innerHTML = showSub && opt.sub
        ? `${opt.text}<small>${opt.sub}</small>`
        : opt.text;
      btn.addEventListener("click", () => {
        box.querySelectorAll("button").forEach((b) => b.classList.remove("selected"));
        btn.classList.add("selected");
        onPick({ ...opt, idx }, btn);
      });
      box.appendChild(btn);
    });
  };

  // ---------- 超时弹层 ----------
  $("#btn-timeout-continue").addEventListener("click", () => {
    $("#modal-timeout").classList.add("hidden");
    resetIdle();
  });
  document.querySelector("#modal-timeout [data-go]").addEventListener("click", () => {
    alert("作答已暂停，您可以在 24 小时内使用相同的邀请码继续完成测评。超时未完成的数据将被清除。");
    $("#modal-timeout").classList.add("hidden");
    clearStore();
    show("home");
  });

  // hash 变化时兜底显示对应视图
  window.addEventListener("hashchange", () => {
    const id = location.hash.replace("#", "");
    if (["home", "consent", "screening", "intro", "break", "assessment",
         "scale-confirm", "final-confirm", "result", "revoke"].includes(id)) {
      if (id === "revoke") {
        showRevoke();
      } else {
        show(id);
      }
    }
  });

  // 启动
  initHome();
})();
