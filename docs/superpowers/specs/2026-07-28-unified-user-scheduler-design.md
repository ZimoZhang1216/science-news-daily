# 外部 Cronjob 统一唤醒与用户计划调度设计

## 目标

使用现有 `repository_dispatch` 事件 `science-news-daily` 作为唯一的自动唤醒入口。外部 cronjob 每 30 分钟调用一次 `Cronjob Daily Research News`；该 workflow 保留固定五学科日报的现有流程，同时在同一 workflow 中运行数据库驱动的用户计划调度器。

固定日报和用户日报共享模型、SMTP、PDF 转换和 Actions 基础设施，但固定日报的 `.daily-run-marker` 不得阻止用户调度器扫描到期任务。

## 已确认范围

- 用户计划支持既有 `daily`、`weekdays`、`weekly` 频率，以及每个用户的 IANA 时区与本地发送时间。
- 数据库时间一律保存 ISO 8601 UTC；界面继续显示用户本地时间。
- 每次唤醒最多运行 `MAX_JOBS_PER_RUN` 个用户任务，并在 `MAX_RUNTIME_MINUTES` 到期前停止领取新任务。
- SQLite 与 Turso/libsql 都必须使用同一仓储接口和相同迁移路径。
- 自动投递采用数据库唯一周期键、条件更新领取和持久化执行状态；GitHub Actions concurrency 只减少重叠，不能替代数据库保护。
- 手动 preview/retry workflow 保留，但移除其 GitHub `schedule` 自动触发和自动扫描 job。

## 数据与状态设计

在既有 `deliveries` 表上做向后兼容迁移，新增 `schedule_id`、`schedule_period_key`、`locked_at`、`locked_by`、`execution_id`、`next_retry_at`、`error_stage`、`email_prepared_at`、`email_sending_at`。旧记录使用空字符串或空时间默认值；初始化会通过迁移版本表与列检测追加字段，绝不要求删除现有 SQLite/Turso 数据。

自动任务周期键为 `automatic:{user_id}:{schedule_id}:{due_at_utc}:email`，并继续受 `deliveries.idempotency_key` 的唯一约束。`due_at_utc` 是原 `schedules.next_run_at` 的值，因此同一用户、同一计划、同一应执行周期只能创建一次投递记录。

状态转换：

```text
queued/retryable_failed --(atomic claim)--> claimed
claimed --(DOCX/PDF success)--> claimed + email_prepared_at
claimed --(persist before SMTP)--> sending
sending --(SMTP success)--> sent
claimed --(pre-mail failure)--> retryable_failed
sending --(SMTP failure)--> retryable_failed
sending --(lease timeout)--> failed / delivery outcome unknown
claimed --(lease timeout)--> retryable_failed
```

`claimed` 的超时可重试；`sending` 的超时标记为不可自动重试的未知投递结果。SMTP 没有可事务化的最终回执，因此此策略优先防止“SMTP 已接收但进程在写库前崩溃”导致的自动重复邮件。运营者可以从投递记录中人工确认后重试。

可重试失败记录错误阶段（`fetch`、`ai`、`document`、`pdf`、`email`、`database`）、脱敏错误摘要、最后尝试时间和指数退避后的 `next_retry_at`。最大尝试次数由 `MAX_DELIVERY_ATTEMPTS` 配置，默认 3。

## 原子领取与调度

扫描只查询 `enabled=1`、`users.status='active'` 且 `next_run_at <= now` 的计划。入队和推进下一次计划在一个事务中执行；领取使用带前置状态和 `next_retry_at` 条件的 `UPDATE`，以受影响行数确定归属。Turso 事务冲突或条件更新受影响行数为零时视为未领取，不得继续生成或发送。

成功投递后计算新的 `next_run_at`。遇到延迟唤醒时，对原周期只投递一次，再从当前 UTC 计算下一个未来周期，避免积压任务逐日补发。夏令时使用明确规则：歧义本地时间取第一次出现；不存在的本地时间向前顺延至同一墙钟分钟数的有效时间。

## Workflow

`cronjob-daily.yml` 保持 `repository_dispatch: science-news-daily` 与 `workflow_dispatch`。固定日报 job 延续当前 cache marker 与依次调用 `main.py` 的路径。新增同一 workflow 的用户调度 job，注入现有模型、SMTP 与新增 Turso Secrets，执行 `python custom_user_daily.py scan`，并输出不含邮箱或 secret 的数量摘要。

外部 cronjob 配置为每 30 分钟调用同一 GitHub dispatch API；它不传用户、计划、收件人或邮件内容。

## 验证

单元测试覆盖未到期/暂停跳过、SQLite 并发领取、Turso DB-API 兼容、周期幂等、退避、锁超时恢复、SMTP 不确定状态、批处理上限、单任务失败隔离、时区/DST 和下一次运行时间。运行器测试使用假生成器、PDF 转换器和 mailer；不得发送真实邮件或调用模型。workflow 测试验证统一入口、30 分钟外部唤醒文档和 fixed marker 与用户扫描的隔离。
