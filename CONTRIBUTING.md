# 参与贡献指南（CONTRIBUTING）

感谢您对「心镜」的关注。这是一个面向心理健康场景的敏感项目，参与贡献前请先阅读
本指南与核心设计理念（`docs/00`、`docs/02`）。

## 核心理念红线

1. **不伤害、不标签、不引导自我诊断**：任何新增文案、功能或规则不得让患者产生
   「我被诊断为 XX」的联想；自动生成的文本必须经过禁用词过滤（`app/utils/sanitize.py`）。
2. **以患者为中心**：患者端永远不显示分数、量表名称、倾向性词汇。
3. **简约可拓展**：新增量表/规则/配置优先走数据库配置，而不是硬编码。

## 环境准备

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python seed.py          # 初始化数据库 + 种子数据
.venv/bin/python run.py           # http://127.0.0.1:8000
```

## 代码规范

- 后端遵循 PEP 8；提交前请运行 `python -m pytest tests/ -q`（全部通过）。
- 前端保持原生 JS 的简洁风格，函数有注释说明用途。
- 关键业务逻辑（计分、推送、规则引擎）必须有对应测试。

## 提交 PR 的流程

1. Fork 本仓库并创建特性分支（`feat/xxx` 或 `fix/xxx`）。
2. 提交信息使用中文或英文，说明改动动机与影响面。
3. 新功能需包含测试（`backend/tests/`）与必要的文档更新（`docs/`）。
4. 涉及患者端文案或结果呈现的改动，请说明如何满足「不标签化」底线。
5. 创建 Pull Request，描述改动内容、验证方式与测试结果。

## 测试要求

- 后端：`cd backend && .venv/bin/python -m pytest tests/ -q`
- 冒烟（需全新种子库）：
  ```bash
  rm -f mind_mirror_dev.db && .venv/bin/python seed.py
  .venv/bin/python scripts/smoke_flow.py
  .venv/bin/python scripts/smoke_patient_ui.py
  ```

## 版权提醒

- 不要向 `backend/seed_data/` 添加未经确认可公开使用的量表条目文本；
  新增量表前阅读 `NOTICE.md`。
- 不要提交任何真实患者数据、个人信息或密钥（`.env`、`*.db`、日志均已 gitignore）。

## 行为准则

所有参与者须遵守 `CODE_OF_CONDUCT.md`：对心理困扰相关话题保持尊重，
避免标签化与污名化表达。
