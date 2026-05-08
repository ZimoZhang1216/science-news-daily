# 科研资讯日报自动化项目

这个项目会从 arXiv、PubMed、Crossref 期刊元数据和 RSS 源检索近 24 小时到 3 天内的前沿论文/科研资讯，调用 OpenAI 或 DeepSeek 生成中文标题、简短中文摘要和分领域摘要，并输出 Word 文档。化学、生物和统计学日报统一使用严谨的学术亮点标题，突出可核对的研究对象、方法、机制、模型或证据边界。当前支持化学、生物、统计学三套日报；配置 SMTP 后，本地仍保存 `.docx`，邮件附件会自动转换为 `.pdf`。

默认输出：

```text
./output/chem_news_YYYY-MM-DD.docx
./output/bio_news_YYYY-MM-DD.docx
./output/stat_news_YYYY-MM-DD.docx
```

默认输出目录位于项目内，避免定时任务写入 `~/Documents` 或 iCloud 目录时遇到权限问题。仍可通过 `--output-dir` 手动指定其他目录。

## 支持学科与来源

- 化学：arXiv、PubMed、JACS、Angewandte Chemie、Nature Chemistry、Science、ACS、RSC 和 Chemistry World。
- 生物：arXiv q-bio、PubMed、Nature、Science、Cell、Nature Biotechnology、Nature Methods、Nature Genetics、Nature Medicine、PLOS Biology、eLife 等。
- 统计学：arXiv stat/math.ST、PubMed 生物统计关键词、Annals of Statistics、Biometrika、JASA、JRSS B、Statistical Science、Bayesian Analysis、Bernoulli、JMLR 等。

说明：出版商页面经常有访问限制或反爬策略，因此脚本优先使用 Crossref/RSS/API 等稳定接口。某个来源失败时会记录日志并跳过，不会中断整份日报。

## 安装

```bash
cd "/Users/zhangzimo/Library/Mobile Documents/com~apple~CloudDocs/science-news-daily"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 配置

如需启用大模型中文总结，先选择供应商：

```bash
export LLM_PROVIDER="openai"   # 可选：openai 或 deepseek，默认 openai
```

使用 OpenAI：

```bash
export OPENAI_API_KEY="你的 OpenAI API Key"
export OPENAI_MODEL="gpt-5.4-mini"
```

使用 DeepSeek：

```bash
export LLM_PROVIDER="deepseek"
export DEEPSEEK_API_KEY="你的 DeepSeek API Key"
export DEEPSEEK_MODEL="deepseek-v4-flash"
```

也可以把这些变量写入项目根目录的 `.env` 文件；脚本会通过 `python-dotenv` 自动读取。不要把 `.env` 提交到公开仓库。

可选配置：

```bash
export NCBI_EMAIL="you@example.com"
export NCBI_API_KEY="你的 NCBI API Key"
export CROSSREF_MAILTO="you@example.com"
export REPORT_PROFILE="chemistry"  # 可选：chemistry、biology、statistics
export CHEM_NEWS_DAYS="3"
export CHEM_NEWS_MAX_ITEMS="30"
export CHEM_NEWS_MAX_AI_ITEMS="30"
```

`NCBI_EMAIL` 和 `CROSSREF_MAILTO` 不是必需项，但建议填写，便于遵守 PubMed/Crossref 的礼貌访问规范。

如果对应供应商的 API Key 存在，脚本会调用模型 API 生成中文标题、今日重点、分领域摘要和简短中文摘要。如果没有配置 API Key，默认本地运行会自动使用规则模板生成标题和 fallback summaries，不会因为缺少 Key 直接崩溃。所有学科标题都会优先突出研究对象、方法、材料/体系、机制、模型、数据类型或证据边界，避免营销号式反问和悬念表达。

默认日报会根据来源重要性、研究新近性、摘要信息量和学习价值关键词压缩到 30 篇。学习价值关键词包括 review、perspective、mechanism、benchmark、platform、general method、design principle 等。

## 邮件发送

生成 `.docx` 后，脚本会先保存 Word 文件，再尝试把该文件转换为 PDF 并通过 SMTP 发送。每个学科可以配置不同收件人，多个收件人用英文逗号或分号分隔：

```text
2510248@mail.nankai.edu.cn
```

需要配置 SMTP。建议写入 `.env`：

```env
REPORT_EMAIL_TO=2510248@mail.nankai.edu.cn,second@example.com
CHEM_REPORT_EMAIL_TO=chem-reader@example.com
BIO_REPORT_EMAIL_TO=bio-reader@example.com
STAT_REPORT_EMAIL_TO=stat-reader@example.com
SMTP_HOST=smtp.example.com
SMTP_PORT=465
SMTP_USERNAME=your_email@example.com
SMTP_PASSWORD=你的SMTP授权码或应用专用密码
SMTP_FROM=your_email@example.com
SMTP_SECURITY=ssl
EMAIL_ENABLED=true
```

常见设置：

- `SMTP_SECURITY=ssl` 通常配 `SMTP_PORT=465`。
- `SMTP_SECURITY=starttls` 通常配 `SMTP_PORT=587`。
- `SMTP_PASSWORD` 应使用邮箱服务商提供的 SMTP 授权码/app password，不要使用网页登录密码。
- `CHEM_REPORT_EMAIL_TO`、`BIO_REPORT_EMAIL_TO`、`STAT_REPORT_EMAIL_TO` 分别控制化学、生物、统计学收件人。
- 化学为了兼容旧配置，会在 `CHEM_REPORT_EMAIL_TO` 为空时使用 `REPORT_EMAIL_TO`；生物和统计学需要单独配置对应收件人。
- 邮件附件只发送 PDF；本地输出目录仍保留对应 `.docx`。
- PDF 转换依赖 LibreOffice。macOS 可安装 LibreOffice；如果命令不在 PATH，可设置 `LIBREOFFICE_PATH=/Applications/LibreOffice.app/Contents/MacOS/soffice`。
- 默认本地运行时，如果 SMTP 未配置、PDF 转换失败，或日报没有完整 AI 总结，脚本只会记录 `Email not sent`，不会影响 Word 生成。
- 线上和手动发邮件的 workflow 会使用 `--require-ai`；只要模型 API 没有成功覆盖所有日报条目，就不会发送日报邮件。
- 所有发邮件 workflow 会同时使用 `--require-email`，只要 SMTP、收件人、PDF 转换或发信失败，workflow 就会失败，避免误判为已发送。

## 运行

生成最近 3 天化学日报：

```bash
python main.py
```

生成生物或统计学日报：

```bash
python main.py --profile biology
python main.py --profile statistics
```

只看最近 24 小时：

```bash
python main.py --days 1
```

不调用模型 API，仅测试抓取和 Word 输出：

```bash
python main.py --no-openai --verbose
```

只生成本地文档、不发送邮件：

```bash
python main.py --profile chemistry --output-dir ./output --no-email
python main.py --profile biology --output-dir ./output --no-email
```

指定输出目录：

```bash
python main.py --output-dir "$HOME/Documents/ScienceNewsDaily"
```

单独检查网络：

```bash
python network_check.py
```

网络诊断会检查 `arxiv.org`、`pubmed.ncbi.nlm.nih.gov`、`api.crossref.org` 的 DNS 解析和 HTTPS 请求。

如果抓取和过滤后为 0 条，脚本不会生成正常日报，而会在输出目录生成：

```text
运行失败报告.docx
```

失败报告会写明 DNS 是否失败、哪些来源失败、HTTPS 错误和建议修复动作。全部来源失败时退出码为非 0；单个来源失败不会影响其他来源继续抓取。

## 每天自动运行

macOS/Linux 可以用 cron，例如每天早上 8 点运行：

```cron
0 8 * * * cd "/Users/zhangzimo/Library/Mobile Documents/com~apple~CloudDocs/science-news-daily" && /bin/zsh -lc 'source .venv/bin/activate && python main.py --profile chemistry >> "./output/run.log" 2>&1 && python main.py --profile biology >> "./output/run.log" 2>&1 && python main.py --profile statistics >> "./output/run.log" 2>&1'
```

也可以用 macOS `launchd`、GitHub Actions 或服务器定时任务运行。只要保证所选供应商的 API Key 环境变量可用即可。

## GitHub Actions 自动运行

项目现在把 GitHub Actions 拆成 7 个独立 workflow，避免“手动测试、私人邮箱、每日自动任务”互相干扰。

单科目标收件人 workflow：

- `.github/workflows/target-chemistry.yml`：`Chemistry News - Target Email`，发送到 `CHEM_REPORT_EMAIL_TO`；为空时回落到 `REPORT_EMAIL_TO`。
- `.github/workflows/target-biology.yml`：`Biology News - Target Email`，发送到 `BIO_REPORT_EMAIL_TO`。
- `.github/workflows/target-statistics.yml`：`Statistics News - Target Email`，发送到 `STAT_REPORT_EMAIL_TO`。

单科私人邮箱 workflow：

- `.github/workflows/personal-chemistry.yml`：`Chemistry News - Personal Email`，发送到 `PERSONAL_REPORT_EMAIL_TO`。
- `.github/workflows/personal-biology.yml`：`Biology News - Personal Email`，发送到 `PERSONAL_REPORT_EMAIL_TO`。
- `.github/workflows/personal-statistics.yml`：`Statistics News - Personal Email`，发送到 `PERSONAL_REPORT_EMAIL_TO`。

每日自动 workflow：

- `.github/workflows/cronjob-daily.yml`：`Cronjob Daily Research News`，专门给 cron-job.org 等外部定时器触发。
- 监听 `repository_dispatch` 的 `event_type=science-news-daily`，也保留 `workflow_dispatch` 便于手动测试。
- 每次运行固定生成化学、生物、统计学三份日报，并分别发送到目标收件人，不使用 `PERSONAL_REPORT_EMAIL_TO`。
- `repository_dispatch` 成功后会保存当天 marker，避免外部定时器重复请求导致当天重复发送。

所有发邮件 workflow 都强制使用：

```bash
python main.py --profile <profile> --output-dir ./output --require-email --require-ai
```

因此只有在模型 API 确实为日报条目生成总结、PDF 转换成功、SMTP 发送成功时，workflow 才会显示成功。

配置模型供应商和 API Key：

1. 打开 GitHub 仓库页面。
2. 进入 `Settings` -> `Secrets and variables` -> `Actions`。
3. 点击 `New repository secret`。
4. 使用 OpenAI 时，添加 `OPENAI_API_KEY`，Secret 填你的 OpenAI API Key。
5. 使用 DeepSeek 时，添加 `LLM_PROVIDER`，Secret 填 `deepseek`；再添加 `DEEPSEEK_API_KEY`，Secret 填你的 DeepSeek API Key。

可选 Secrets：

- `OPENAI_MODEL`：OpenAI 模型名，未配置时默认 `gpt-5.4-mini`。
- `DEEPSEEK_MODEL`：DeepSeek 模型名，未配置时默认 `deepseek-v4-flash`。
- `LLM_PROVIDER`：`openai` 或 `deepseek`，未配置时默认 `openai`。
- `REPORT_EMAIL_TO`：化学日报兼容旧配置的默认收件人；多个邮箱用英文逗号或分号分隔。
- `CHEM_REPORT_EMAIL_TO`：化学日报收件人；为空时回落到 `REPORT_EMAIL_TO`。
- `BIO_REPORT_EMAIL_TO`：生物日报收件人。
- `STAT_REPORT_EMAIL_TO`：统计学日报收件人。
- `PERSONAL_REPORT_EMAIL_TO`：私人手动 workflow 专用收件人，供三条 `personal-*` workflow 使用。
- `SMTP_HOST`、`SMTP_PORT`、`SMTP_USERNAME`、`SMTP_PASSWORD`、`SMTP_FROM`、`SMTP_SECURITY`：用于发送 PDF 附件邮件。

workflow 会把 Secrets 注入为环境变量：

```yaml
LLM_PROVIDER: ${{ secrets.LLM_PROVIDER }}
OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
OPENAI_MODEL: ${{ secrets.OPENAI_MODEL }}
DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
DEEPSEEK_MODEL: ${{ secrets.DEEPSEEK_MODEL }}
REPORT_EMAIL_TO: ${{ secrets.REPORT_EMAIL_TO }}
CHEM_REPORT_EMAIL_TO: ${{ secrets.CHEM_REPORT_EMAIL_TO }}
BIO_REPORT_EMAIL_TO: ${{ secrets.BIO_REPORT_EMAIL_TO }}
STAT_REPORT_EMAIL_TO: ${{ secrets.STAT_REPORT_EMAIL_TO }}
PERSONAL_REPORT_EMAIL_TO: ${{ secrets.PERSONAL_REPORT_EMAIL_TO }}
SMTP_HOST: ${{ secrets.SMTP_HOST }}
SMTP_PORT: ${{ secrets.SMTP_PORT }}
SMTP_USERNAME: ${{ secrets.SMTP_USERNAME }}
SMTP_PASSWORD: ${{ secrets.SMTP_PASSWORD }}
SMTP_FROM: ${{ secrets.SMTP_FROM }}
SMTP_SECURITY: ${{ secrets.SMTP_SECURITY }}
```

如果没有配置对应 API Key，本地普通命令仍可使用 fallback summaries 生成文档；但脚本不会发送这类普通日报邮件。所有 GitHub 发邮件 workflow 都会失败并停止发送，因为它们强制启用 `--require-ai`。

workflow 会安装 LibreOffice Writer 和 Noto CJK 字体，用于把本地保存的 Word 报告转换为邮件 PDF 附件。

### 外部定时器触发

使用 cron-job.org、UptimeRobot、服务器 cron、Cloudflare Workers Cron Trigger 等外部定时器，每天北京时间 07:30 调用 GitHub `repository_dispatch` API。仓库内的自动入口只有 `.github/workflows/cronjob-daily.yml`，不会再由各个单科手动 workflow 接收外部定时器事件。

先创建一个 GitHub fine-grained personal access token：

1. GitHub 右上角头像 -> `Settings` -> `Developer settings`。
2. 进入 `Personal access tokens` -> `Fine-grained tokens`。
3. 新建 token，Repository access 选择 `ZimoZhang1216/science-news-daily`。
4. Repository permissions 至少给 `Contents: Read and write`。
5. 复制 token；不要提交到仓库。

外部定时器配置：

- Method: `POST`
- URL: `https://api.github.com/repos/ZimoZhang1216/science-news-daily/dispatches`
- Header: `Accept: application/vnd.github+json`
- Header: `Authorization: Bearer YOUR_GITHUB_TOKEN`
- Header: `X-GitHub-Api-Version: 2022-11-28`
- Body:

```json
{
  "event_type": "science-news-daily",
  "client_payload": {}
}
```

外部定时器不需要传 `profiles`；`Cronjob Daily Research News` 会自动运行化学、生物、统计学三份日报并发送三封 PDF 附件邮件。

服务器上也可以用 curl 测试：

```bash
curl -L -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer YOUR_GITHUB_TOKEN" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  https://api.github.com/repos/ZimoZhang1216/science-news-daily/dispatches \
  -d '{"event_type":"science-news-daily","client_payload":{}}'
```

如果想指定报告日期，可传：

```json
{
  "event_type": "science-news-daily",
  "client_payload": {
    "report_date": "2026-05-07"
  }
}
```

手动运行：

1. 打开 GitHub 仓库的 `Actions` 页面。
2. 选择需要的 workflow，例如 `Chemistry News - Target Email`、`Biology News - Personal Email` 或 `Cronjob Daily Research News`。
3. 点击 `Run workflow`。
4. 选择分支后再次点击 `Run workflow`。

下载 artifact：

1. 打开对应的 workflow run。
2. 在页面底部找到 `Artifacts`。
3. 下载对应 artifact，例如 `chemistry-target-output`、`biology-personal-output` 或 `cronjob-science-news-daily-output`。
4. 解压后即可看到生成的 `.docx`；如果本次完成了邮件 PDF 转换，也会包含同名 `.pdf`。正常情况会包含 `chem_news_YYYY-MM-DD.docx`、`bio_news_YYYY-MM-DD.docx`、`stat_news_YYYY-MM-DD.docx`；抓取为 0 条时会生成对应失败报告。

GitHub Actions 只调用公开 API/RSS/元数据接口和你配置的模型 API，不会自动登录学校账号，也不会下载受版权保护的 PDF。

## 输出结构

Word 文档包含：

- 标题：化学科研资讯日报
- 日期
- 今日重点 5 条
- 分领域摘要
- 每条资讯的中文标题、原始英文标题、来源、发布日期、DOI/链接、简短中文摘要和原文摘要

## 常见问题

如果 Word 中某些出版商条目显示“出版商元数据未提供摘要”，说明 Crossref 没有返回该论文摘要。脚本仍会保留标题、来源、发布日期、DOI/链接，并在简评中说明信息有限。

如果模型 API 调用失败，脚本会自动退回到本地规则模板生成中文标题和简短中文摘要，保证 `.docx` 仍然生成。
