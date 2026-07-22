# 谜案经纬

谜案经纬（Mystery Atlas）是一个由 AI 辅助生产、管理员审核维护的硬核推理小说公共数据库。

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

- `apps/web`：公共案件档案库、人物图谱工作区和管理员审核台
- `apps/api`：FastAPI 公共查询、审核、版本发布和数据库模型
- `workers/analyzer`：逐章阅读轨与全书真相轨任务骨架
- `infra/docker`：PostgreSQL、Redis 和 MinIO 本地基础设施

## 本地启动

```powershell
docker compose -f infra/docker/compose.yaml up -d
pnpm install
pnpm dev
```

另开一个终端启动 API：

```powershell
.\.venv\Scripts\python.exe -m uvicorn mystery_atlas_api.main:app --reload --port 8000
```

前端默认地址为 `http://localhost:3000`，API 文档为 `http://localhost:8000/docs`。
