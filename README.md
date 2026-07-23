# 谜案经纬

谜案经纬（Mystery Atlas）是一个面向推理小说的结构化档案库。它把作品、版本、人物、案件、关系、线索、推论、章节和原文证据组织为可追溯的数据网络，站内阅读器是档案分析的辅助能力。

## 产品结构

- **公共档案**：用户公开上传的作品和版本，基础解析完成后直接发布，由上传者负责维护。
- **私人档案**：用户私密上传的书籍，以及阅读公共书籍时自动生成的个人阅读记录。
- **作品与版本**：同一作品只保留一份公共结构化档案，不同译者、出版社和 ISBN 作为版本挂载。
- **维护与反馈**：人物、关系、案件、线索等对象都可反馈；维护者直接修正，系统保留版本记录。
- **统一防剧透**：阅读进度控制人物图谱、案件、线索、推论、搜索和助手的可见范围。

完整产品规格见 [docs/product-spec.md](docs/product-spec.md)。

## 当前代码结构

- `apps/web`：档案库、阅读工作台、账户、上传与维护界面。
- `apps/api`：FastAPI 账户、上传解析、作品版本、阅读记录、反馈和治理 API。
- `workers/analyzer`：分阶段 AI 分析任务骨架。
- `infra/docker`：PostgreSQL、Redis 和 MinIO 本地基础设施。

## 本地启动

本地开发默认使用 SQLite，不要求先安装 Docker：

```powershell
pnpm install
Copy-Item .env.example .env.local
pnpm dev:local
```

前端地址为 `http://127.0.0.1:3100`，API 文档为 `http://127.0.0.1:8010/docs`。

也可以单独启动 API：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e "apps/api[dev]"
$env:PYTHONPATH="apps/api/src"
.\.venv\Scripts\python.exe -m uvicorn mystery_atlas_api.main:app --reload --host 127.0.0.1 --port 8010
```

开发环境中的第一个注册账户会成为超级管理员。正式环境必须设置安全的 `MYSTERY_ATLAS_SESSION_SECRET`，并显式配置超级管理员。

上传文件保存在 `.data/uploads`，解析记录和账户数据保存在 `.data/mystery-atlas.db`；两者均已排除在 Git 之外。
