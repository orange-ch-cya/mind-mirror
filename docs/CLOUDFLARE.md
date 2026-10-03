# Cloudflare 免费托管

正式站点使用一个 Python Worker、Workers Assets 和 D1，不依赖原项目的服务器 SQLite 文件。配置在 `backend/wrangler.jsonc`，数据库 ID 绑定为此仓库当前 Cloudflare 账号的 `mind-mirror` D1。患者端为 `/`，医生端为 `/doctor`。

## 首次初始化

在 `backend` 的 Python 环境安装 `pyproject.toml` 所列依赖；本地生成资产和 D1 SQL：

```powershell
python scripts/prepare_assets.py
python scripts/export_d1.py ./.generated-d1
```

在 Cloudflare 创建免费的 D1 `mind-mirror`，将其 ID 填入 `wrangler.jsonc`。分别执行 `.generated-d1/schema.sql`、`.generated-d1/seed.sql`；种子 SQL 刻意不包含原项目公开的默认管理员账号，也不包含测评数据。然后在 Worker 上设置两个长度至少 32 字符的随机 Secret：`JWT_SECRET` 和 `PASSWORD_PEPPER`。两个值必须长期保存；更换前者会使现有登录和患者会话凭证失效，更换后者会使现有密码哈希无法验证。

设置与 Worker 相同的 `PASSWORD_PEPPER` 本地环境变量后，运行 `python scripts/make_admin_sql.py`，按提示输入随机初始密码，将输出的 INSERT 在 D1 中执行。管理员首次登录必须修改密码。不要运行 `backend/seed.py` 创建生产管理员：它使用公开的初始密码。

运行 `uv run pywrangler deploy`（工作目录为 `backend`）。若当前环境无法从 CLI 上传，可按 [Cloudflare 的直接上传说明](https://developers.cloudflare.com/workers/static-assets/direct-upload/)部署相同的 Worker 代码和 `public` 目录。启用 Worker 的 `workers.dev` 子域名。

## 免费额度与导出

Workers Free 每日有请求额度且每个 HTTP 请求有 10ms CPU 上限；D1 也有免费额度，具体数值以 [Cloudflare 当前定价](https://developers.cloudflare.com/workers/platform/pricing/)为准。完整量表的服务端 PDF/XLSX 生成会超过免费 Worker 的 CPU 上限，因此 Cloudflare 版本在医生报告页用浏览器打印/保存 PDF，并导出 Excel 可打开的 UTF-8 CSV；两者仍写审计日志。浏览器导出包含敏感数据，操作人员须在可信设备上保存和管理文件。

项目 `NOTICE.md` 标明若干量表文本的授权状态尚未核实。公开使用前需核实适用范围、版权与专业审定，特别是标为“种子数据近似值”的常模。站点不是临床诊断工具。

## 验证

`python -m pytest tests -q`（工作目录为 `backend`）检查原项目后端规则。上线后还需用合成数据验证登录和强制改密、邀请码、患者同意与答题、提交、医生报告、打印/CSV、患者凭证校验和 24 小时内撤回；撤回后在 D1 确认会话和作答记录物理删除。不要用真实患者资料做部署测试。
