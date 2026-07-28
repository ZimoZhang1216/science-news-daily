# 科研日报个人运营面板设计

## 目标

在不替换既有日报生成链路的前提下，新增一个只供运营者本人使用的本地 Streamlit 面板。它用于维护多位客户的科研画像、查看自动任务状态、手动预览与确认发送，并把用户、报告和交付状态保存到 Turso 托管 SQLite。

系统要把“固定学科日报”扩展为“按用户科研画像生成日报”，同时保留现有 `python main.py --profile <profile>` 命令和 11 个 GitHub Actions 工作流。

## 已确认范围

- 面板只在运营者本机运行，不对客户公开，不需要登录或支付界面。
- 首页采用运行总览：展示待发送、已发送、失败待重试、来源状态和最近任务。
- 用户画像拥有独立页面：研究方向、包含/排除词、来源、期刊、内容偏好、条目数、频率、时区、模型、邮箱和服务状态。
- 自动发送由 GitHub Actions 执行；面板通过 GitHub dispatch 创建手动预览或发送任务。
- 手动任务必须“生成预览 → 检查 → 确认发送”。
- 自动任务不要求人工确认；失败时有限重试，最终记录为待处理，禁止发送 AI 不完整的正常日报。
- Turso 是用户、画像、任务、交付、统计的唯一状态源。
- 既有五个 profile、现有 SMTP/模型 Secrets 和固定学科工作流继续工作，不迁移、不改名。

## 非目标

- 不创建客户自助门户、注册、登录、支付、订阅扣费或团队权限系统。
- 不在第一版提供任意 RSS URL、任意外部数据源或用户自带模型密钥。
- 不在第一版建设全局论文候选缓存、向量检索、PostgreSQL、Redis、Celery 或 Docker。
- 不替换现有 Word、PDF、SMTP、科学记号或固定 profile 生成逻辑。

## 架构

```text
本地 Streamlit 面板（仅 127.0.0.1）
  ├─ 用户画像 CRUD、运行总览、预览确认、失败重试
  ├─ Turso SQLite
  └─ GitHub repository_dispatch / workflow_dispatch
       └─ 新增 custom-user-daily.yml
            └─ Python 定制任务运行器
                 ├─ 读取用户画像与领取交付任务
                 ├─ 复用现有抓取、筛选、AI、DOCX、PDF、SMTP 链路
                 ├─ 写回报告、交付和来源统计
                 └─ 上传报告 artifact

既有 target-* / personal-* / cronjob-daily.yml
  └─ 保持现状，不依赖新表
```

本地面板不保存 SMTP、OpenAI、DeepSeek、Turso 或 GitHub token。它们只通过本机 `.env` 或 GitHub Actions Secrets 注入。面板只能显示“已配置/缺失”的状态，不能显示 secret 值。

## 数据模型

下列为第一版的 Turso 表，所有时间存 UTC，并在显示时按用户时区转换。

### users

- `id`：稳定用户标识，例如 `usr_xxx`。
- `display_name`：运营者可读名称。
- `email`：日报收件邮箱。
- `status`：`active`、`paused`、`expired`。
- `created_at`、`updated_at`。

### research_profiles

- `id`、`user_id`、`version`、`is_current`。
- `base_profile`：现有五个 profile 之一。
- `research_topic`、`include_keywords_json`、`exclude_keywords_json`。
- `source_ids_json`、`journal_ids_json`、`content_preferences_json`。
- `max_items`、`llm_provider`、`llm_model`、`output_formats_json`。
- `created_at`。

每次保存画像创建新版本，旧版本保留；报告和交付记录引用版本，便于追溯“当时按什么规则发送”。

### schedules

- `id`、`user_id`、`frequency`、`weekday`、`timezone`、`local_send_time`、`next_run_at`。
- `enabled`、`updated_at`。

第一版频率支持 `daily`、`weekdays`、`weekly`；不支持任意 cron 表达式。

### report_runs

- `id`、`user_id`、`profile_version`、`report_date`、`mode`。
- `status`：`queued`、`running`、`preview_ready`、`completed`、`failed`。
- `github_run_url`、`artifact_name`、`artifact_expires_at`。
- `candidate_count`、`selected_count`、`ai_generated`、`error_summary`。
- `created_at`、`started_at`、`finished_at`。

### deliveries

- `id`、`user_id`、`report_run_id`、`profile_version`、`report_date`、`channel`。
- `mode`：`automatic` 或 `manual`。
- `status`：`queued`、`claimed`、`preview_ready`、`sending`、`sent`、`retryable_failed`、`failed`、`cancelled`。
- `idempotency_key`：唯一约束。自动邮件由用户、用户本地报告日期和 channel 组成；手动发送由预览报告 ID 和 channel 组成。画像版本只作追溯，不参与自动邮件的唯一键。
- `attempt_count`、`last_error`、`sent_at`、`created_at`、`updated_at`。

### report_items

- `id`、`report_run_id`、`user_id`、`report_date`、`profile_version`。
- `doi`、`link`、`title`、`source`、`published_at`、`score`。
- `identity_keys_json`、`title_key`、`topic_key`。

定制任务从该表读取同一用户最近 10 天的去重指纹，并复用现有 `prepare_items()` 的既有精确去重和主题降权规则；不依赖 GitHub Actions 的临时 cache。

### run_events 与 source_metrics

记录任务阶段、来源成功/失败、抓取数量、筛选数量、耗时和可用的模型 usage。首页统计只读取这些汇总数据，不扫描原始日志。

## 交付与幂等

### 自动发送

1. `custom-user-daily.yml` 定期扫描 `active` 且 `next_run_at <= now` 的用户。
2. 每个用户尝试以唯一 `idempotency_key` 原子创建或领取交付记录。同一用户在同一本地报告日期内更新画像，也不能让自动任务多发一封邮件。
3. 已有 `sent`、`sending` 或其他活跃领取状态时跳过，避免重复发送。
4. 任务复用现有抓取、准备、AI、DOCX、PDF、SMTP 路径。
5. 只有全部条目获得 AI 总结、PDF 转换成功且 SMTP 成功时，写入 `sent`。
6. 可恢复错误最多重试两次；随后标记 `retryable_failed` 并在首页提示。不可恢复错误标记 `failed`。

### 手动预览与确认发送

1. 面板创建 `mode=manual` 的 preview 任务，并 dispatch 到 GitHub Actions。
2. Workflow 生成 DOCX/PDF，不发送邮件，状态更新为 `preview_ready`。
3. Workflow 上传带有稳定 artifact 名称的报告文件，保存产生该 artifact 的 GitHub run ID；面板展示条目、状态与 GitHub artifact 链接。
4. 运营者点击“确认发送”后，将同一条预览交付记录从 `preview_ready` 原子转换为 `queued`；新的发送任务按保存的 GitHub run ID 下载已生成的 PDF，不再抓取、总结或重新生成报告。
5. 手动发送任务沿用相同幂等约束，不会因重复点击发送两次。同一用户同一天如需发送修订版，必须由运营者显式创建新的手动报告并确认，页面会给出重复发送警告。

SMTP 不提供端到端的 exactly-once 确认语义；设计目标是通过唯一任务领取、发送状态和明确人工重试，实现可审计的 at-most-one 自动尝试。

## 用户画像与现有日报链路

用户画像先组合为“有效 profile”：现有 `REPORT_PROFILES` 是可信来源和默认学科规则，用户配置只覆盖研究关键词、排除词、可选来源/期刊、偏好、最大条目数、模型和输出标题。

定制任务优先复用现有：

- `fetch_arxiv()`、`fetch_pubmed()`、`fetch_crossref()`、`fetch_rss()`。
- `prepare_items()`、`generate_ai_summaries()`、`apply_ai_scientific_notation()`。
- `create_document()`、`convert_docx_to_pdf()`、SMTP 发送逻辑。

第一版按用户执行抓取，以最小改动验证画像价值。统一候选缓存是后续单独阶段，不在本次范围内。

## Streamlit 信息架构与视觉规范

### 页面

1. **运行总览**：今日待发送、已发送、失败待处理、来源健康度、最近运行、需要注意的用户。
2. **用户**：列表、创建、编辑、暂停/恢复、画像版本和下次发送时间。
3. **报告与发送**：预览、artifact 链接、确认发送、取消、失败重试和发送历史。
4. **来源与统计**：来源成功率、候选/入选数量、模型调用和运行耗时。
5. **设置**：只显示连接配置是否就绪，不显示 secret。

### 视觉事实来源

已生成三张概念图：运行总览、用户画像页、预览确认页。实现使用真白背景、浅冷灰应用外壳、深墨蓝文字、细蓝灰分隔线和深青色主操作色。以左侧导航、表格、时间线和详情抽屉为主，不使用营销 Hero、Bento 卡片墙、暖色底或装饰性插图。

## 运行与 Secrets

本地面板需要：

- `TURSO_DATABASE_URL`、`TURSO_AUTH_TOKEN`。
- GitHub fine-grained token，仅允许 dispatch 指定仓库的 workflow。

GitHub Actions 需要：

- `TURSO_DATABASE_URL`、`TURSO_AUTH_TOKEN`。
- 现有 `LLM_PROVIDER`、模型 API Key、SMTP Secrets。

手动预览和自动发送都在 GitHub Actions 中运行，因此本机不需要 SMTP 或模型 API Key。

## 失败处理与可观测性

- 面板只显示归类后的错误摘要，不输出 token、密码、收件人完整地址或 API 响应中的 secret。
- 来源失败不阻塞其他来源；无内容、AI 不完整、PDF 失败、SMTP 失败分别显示不同状态。
- `report_runs` 保存 GitHub run URL，运营者可跳转查看完整 Actions 日志。
- 每次状态迁移写入 `run_events`，支持首页最近活动与排障。

## 测试与验证

- 新增数据库仓储单元测试：schema、用户画像版本、到期查询、幂等领取、状态迁移。
- 新增有效 profile 组合测试：包含词、排除词、来源和条目数不会破坏旧 profile。
- 新增定制交付运行器测试：preview 不发送、确认发送只发送一次、自动重试两次后停止。
- 用 mocked GitHub dispatch、SMTP、PDF、LLM 和数据源验证失败路径。
- 保留现有 `tests/` 的 fixed-profile、DOCX 和科学记号回归测试。
- 本地运行 Streamlit，检查桌面与移动宽度、创建用户、预览、确认、失败重试和统计刷新。
- 新 workflow 在推送前进行 YAML 解析与 Python 测试；既有 11 个工作流不改动。

## 渐进发布

1. 创建数据层、画像模型和测试，但不改变既有 CLI 行为。
2. 创建 Streamlit 面板并使用本地 SQLite 测试模式；远程 Turso 未配置时显示明确 setup 状态。
3. 增加定制 workflow 的 preview 模式，验证从 Turso 到 artifact 的闭环。
4. 增加确认发送、自动到期扫描、幂等与重试。
5. 在至少一位真实试点用户上验证后，再考虑统一候选缓存。
