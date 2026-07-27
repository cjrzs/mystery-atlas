# 整书 AI 分析流水线

本文档对应当前可执行实现，不是产品设想。

## 代码入口

- 深模块接口：`workers/analyzer/src/mystery_atlas_analyzer/pipeline.py::analyze_book`
- 输入输出契约：`workers/analyzer/src/mystery_atlas_analyzer/contracts.py`
- OpenAI-compatible 模型适配器：`workers/analyzer/src/mystery_atlas_analyzer/model_adapters.py`
- 数据库适配器：`workers/analyzer/src/mystery_atlas_analyzer/repository.py`
- 单任务运行器：`workers/analyzer/src/mystery_atlas_analyzer/runner.py::run_analysis_job`
- Celery 入口：`workers/analyzer/src/mystery_atlas_analyzer/tasks.py`
- API 自动派发：`apps/api/src/mystery_atlas_api/analysis_dispatch.py`

外部调用者只需要提供 `job_id`：

```python
from mystery_atlas_analyzer.runner import run_analysis_job

result = run_analysis_job(job_id)
```

## 执行阶段

1. `source_validation`：检查章节非空、章节号唯一。
2. `segment_analysis`：按语义边界切分超长章节，保留重叠上下文；逐段提取人物、关系、事件、证据和观点。
3. `chapter_synthesis`：合并同一章节的多个分段结果，去重并保留原文引文。
4. `book_synthesis`：先按连续章节生成部分综合，并保存逐批检查点。
5. `evidence_verification`：在全书结论形成前，把章节与部分综合中的每条引文重新定位到原文；记录字符区间，PDF 同时记录页码。无法定位的引文不会进入全书事实层。
6. `full_book_reconciliation`：基于已验证证据分批合并观点；时间线由程序确定性合并；编辑型 AI 只生成结构、主题、人物弧线、谜题、矛盾和伏笔；最后对观点执行一次分批证据审计。
7. `persistence`：保存完整报告和结构化人物、关系、证据、观点、章节快照。

## 正文与章节边界

- 章节边界只来自 EPUB 导航、spine 和标题，或 TXT/PDF 中的源文标题标记；AI 不负责切分章节。
- 封面、目录、推荐、作者介绍、年表、序言、前言、献词、楔子、后记等非正文部分不进入分析。
- 源文已有明确标题时原样保留；只有序号的章节由 AI 补充简短副标题，并保留原章节序号。

## 分层策略

- 默认单段上限为 12,000 字符，重叠 500 字符。
- 章节超过上限时先做段级分析，再做章节合并。
- 默认每 6 章形成一个部分综合。
- 全书观点合并与最终观点审计按请求字符数自适应二分，并可在同一本书内并发执行；默认每批输入上限为 40,000 字符。
- 时间线只合并已验证事件，不再交给 AI 重写；编辑任务不接收原始证据正文，不能新增事实。
- 编辑任务被服务端截断或持续无内容时，会拆成结构、解读、谜题三个独立任务。
- 参数可通过环境变量调整。

## 证据与原文回溯

模型必须为事实性结果提供短原文引文。程序随后执行确定性验证：

- 精确匹配优先。
- 精确匹配失败时，忽略空白字符再次匹配。
- 匹配成功后写入章节内 `start_char`、`end_char`。
- PDF 解析阶段保留页边界，因此可以写入 `page`。
- EPUB 保存资源路径；TXT 保存全书字符范围。
- 未匹配引文会进入 `audit.warnings`，不会伪装为有效证据。

完整审计信息位于：

```text
AnalysisJob.result_summary.audit
```

## 自动触发

用户确认书籍入库后，API 自动创建 `track=full` 的分析任务。

- `MYSTERY_ATLAS_ANALYSIS_EXECUTION=inline`：HTTP 响应结束后在 API 进程执行，适合本地开发。
- `MYSTERY_ATLAS_ANALYSIS_EXECUTION=celery`：派发到 Celery worker，适合部署环境。
- 未配置模型时，任务进入 `waiting_configuration`，不会伪造分析结果。

上传者可以查询：

```text
GET /api/v1/imports/{import_id}/analysis
```

## 模型配置

```dotenv
MYSTERY_ATLAS_AI_PROVIDER=openai-compatible
MYSTERY_ATLAS_AI_BASE_URL=https://provider.example/v1
MYSTERY_ATLAS_AI_API_KEY=...
MYSTERY_ATLAS_AI_READING_MODEL=...
MYSTERY_ATLAS_AI_TRUTH_MODEL=...
MYSTERY_ATLAS_AI_TIMEOUT_SECONDS=90
MYSTERY_ATLAS_AI_CONTENT_IDLE_TIMEOUT_SECONDS=180
MYSTERY_ATLAS_AI_MAX_CHUNK_CHARS=12000
MYSTERY_ATLAS_AI_CHUNK_OVERLAP_CHARS=500
MYSTERY_ATLAS_AI_CHAPTERS_PER_BATCH=6
MYSTERY_ATLAS_AI_MAX_CONCURRENCY=10
MYSTERY_ATLAS_AI_SYNTHESIS_BATCH_CHARS=40000
```

`AI_TRUTH_MODEL` 为空时，全书复核沿用 reading model。

DeepSeek V4 Pro 用于批量结构化 JSON 时显式关闭 thinking mode。整书分析请求不发送
`max_tokens`，由模型服务根据任务自行决定输出容量。观点任务只提交对应的已验证证据
ID 与去重证据，避免把整个证据库重复发送给模型。若服务端仍以 `length` 截断，
流水线会拆分当前批次，而不是重复发送同一个大请求。

Moonshot 的中国站与国际站 Key 不互通：中国站 Key 使用
`https://api.moonshot.cn/v1`，国际站 Key 使用
`https://api.moonshot.ai/v1`。分析器使用流式 SSE 接收长响应，以避免等待完整
JSON 时触发读取超时；只有收到 `[DONE]` 才接受结果。

模型流连续 3 分钟没有产生有效内容时视为 content-idle。可拆分的大任务会立即缩小
批次，最小批次只原样重试一次。HTTP 429、服务端 5xx、网络错误和结构化响应修复由
模型适配器统一重试，任务运行器不再叠加第二层重试。

本地 `inline` 模式会在 HTTP 响应结束后启动独立分析进程。API 重启不会重复派发
已经处于 `running` 的任务；数据库原子认领保证同一任务只有一个进程执行。
任务内部错误只保留在后端，工作台接口返回经过归类的用户提示。

`AI_MAX_CONCURRENCY` 是单本书的并发上限，默认值为 10；它用于章节提取、分部汇总
以及预拆分的观点合并/审计批次。当前实现不设置跨书全局并发上限；如果供应商返回
429，可把该值降为 5 或更低。

流式请求每 15 秒写入安全心跳元数据（任务类型、调用 ID、已接收字符数、内容空闲
秒数），不记录 prompt、响应正文或 API Key。API 每分钟扫描一次运行任务；心跳超过
5 分钟未更新时只把任务标记为失败并保留检查点，不会自动重发 AI 请求。用户重试时
从最近的章节、分部、观点批次、编辑分段或审计批次继续。

## 持久化与人工内容保护

- 完整报告保存到 `analysis_jobs.result_summary`。
- 结构化结果写入 `people`、`person_relations`、`evidence`、`claims`、
  `claim_evidence` 和 `chapter_snapshots`。
- 完整重分析在一个事务中替换该作品旧的 AI 派生人物、别名、关系、证据、主张、案件和章节快照；任务失败时不会留下半套新旧混合数据。
- `works.synopsis` 只在原值为空时由全书概要填充。
- 真实作品的关系图接口读取持久化人物和关系，并继续遵守 `through_chapter` 防剧透边界。

## 验证

```powershell
.\.venv\Scripts\ruff.exe check workers\analyzer\src workers\analyzer\tests apps\api\src apps\api\tests
.\.venv\Scripts\pytest.exe -q workers\analyzer\tests apps\api\tests
```

测试覆盖分层综合、自适应拆分、证据成功与失败验证、统一重试、流式心跳、僵尸任务恢复、SQLite 实际落库，以及未配置 AI 时的上传任务状态。
