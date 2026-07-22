# 谜案经纬

谜案经纬（Mystery Atlas）是一个以管理员维护的公共档案为主体、AI 辅助阅读与分析的硬核推理小说数据库。

产品以人物图谱为核心，把案件、线索、推论、事件、章节与原文证据组织成可追溯的数据网络；完整阅读器和私人数据是公共档案之上的辅助能力。

## 核心原则

- 公共数据库优先，管理员维护的正式档案是产品主体。
- AI 负责提取和推理，管理员负责核验和发布。
- 每条关系与推论都必须能追溯到证据，并标记确认状态。
- 所有视图遵守统一的信息截止章节，默认防止剧透。
- 人物图谱是单书页面的默认主视图，阅读器和分析面板均可收起。
- 用户导入的原书始终私有，不会自动进入公共数据库。

完整产品规格见 [docs/product-spec.md](docs/product-spec.md)。

## 当前实现

- `apps/web`：公共案件档案库、人物图谱工作区、登录、私人导入和管理员审核台
- `apps/api`：FastAPI 公共查询、账号会话、私人书籍解析、审核和数据库模型
- `workers/analyzer`：逐章阅读轨与全书真相轨任务骨架
- `infra/docker`：PostgreSQL、Redis 和 MinIO 本地基础设施

## 本地启动

项目的本地开发默认使用 SQLite，不要求先安装 Docker。首次运行：

```powershell
pnpm install
Copy-Item .env.example .env.local
pnpm dev:local
```

`pnpm dev:local` 会在后台同时启动前端与 API，并把日志写入 `.logs`。也可以另开一个终端手动启动 API：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e "apps/api[dev]"
$env:PYTHONPATH="apps/api/src"
.\.venv\Scripts\python.exe -m uvicorn mystery_atlas_api.main:app --reload --host 127.0.0.1 --port 8010
```

前端地址为 `http://127.0.0.1:3100`，API 文档为 `http://127.0.0.1:8010/docs`。开发环境中，第一个注册的账户会成为管理员；生产环境需要显式设置管理员角色和安全的 `MYSTERY_ATLAS_SESSION_SECRET`。

私人书库支持 EPUB、TXT 和含文本层的 PDF。上传文件保存在 `.data/uploads`，解析记录与账号数据保存在 `.data/mystery-atlas.db`，两者均已排除在 Git 之外。
