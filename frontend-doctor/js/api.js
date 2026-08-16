/* 心镜 · 工作台 API 封装（含 token 管理） */
const Api = {
  token: localStorage.getItem("mm_token") || null,
  user: JSON.parse(localStorage.getItem("mm_user") || "null"),

  async request(method, path, body, raw = false) {
    const opt = { method, headers: {} };
    if (body !== undefined) opt.headers["Content-Type"] = "application/json";
    if (body !== undefined) opt.body = JSON.stringify(body);
    if (this.token) opt.headers["Authorization"] = `Bearer ${this.token}`;
    const res = await fetch(path, opt);
    if (raw) {
      if (!res.ok) throw new Error("下载失败");
      return await res.blob();
    }
    const data = await res.json().catch(() => ({ code: 9000, message: "网络异常" }));
    if (data.code !== 0) {
      const err = new Error(data.message || "请求失败");
      err.code = data.code;
      throw err;
    }
    return data.data;
  },
  get(path, raw = false) { return this.request("GET", path, undefined, raw); },
  post(path, body) { return this.request("POST", path, body); },
  put(path, body) { return this.request("PUT", path, body); },
  patch(path, body) { return this.request("PATCH", path, body); },
  del(path) { return this.request("DELETE", path); },

  saveAuth(token, user) {
    this.token = token;
    this.user = user;
    localStorage.setItem("mm_token", token);
    localStorage.setItem("mm_user", JSON.stringify(user));
  },
  clearAuth() {
    this.token = null;
    this.user = null;
    localStorage.removeItem("mm_token");
    localStorage.removeItem("mm_user");
  },
};
