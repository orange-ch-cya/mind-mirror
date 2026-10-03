/* 心镜 · 患者端 API 封装（文档 2.1 统一响应约定） */
const API = {
  async request(method, path, body) {
    const opt = { method, headers: { "Content-Type": "application/json" } };
    try {
      const saved = JSON.parse(sessionStorage.getItem("mind_mirror_patient") || "null");
      if (saved?.sessionToken) opt.headers["X-Session-Token"] = saved.sessionToken;
    } catch (_) { /* 忽略损坏的本地会话 */ }
    if (body !== undefined) opt.body = JSON.stringify(body);
    const res = await fetch(path, opt);
    const data = await res.json().catch(() => ({ code: 9000, message: "网络异常，请稍后重试" }));
    if (data.code !== 0) {
      const err = new Error(data.message || "请求失败");
      err.code = data.code;
      throw err;
    }
    return data.data;
  },
  get(path) { return this.request("GET", path); },
  post(path, body) { return this.request("POST", path, body); },
};
