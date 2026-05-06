# 化学科研资讯日报自动化项目

这个项目会从 arXiv、PubMed、Crossref 期刊元数据和 RSS 源检索近 24 小时到 3 天内的化学相关论文/科研资讯，调用 OpenAI 或 DeepSeek 生成中文标题、简评和分领域摘要，并输出 Word 文档。配置 SMTP 后，本地仍保存 `.docx`，邮件附件会自动转换为 `.pdf`。

默认输出：

```text
./output/chem_news_YYYY-MM-DD.docx
```

默认输出目录位于项目内，避免定时任务写入 `~/Documents` 或 iCloud 目录时遇到权限问题。仍可通过 `--output-dir` 手动指定其他目录。

## 支持来源

- arXiv API：化学、催化、材料、能源、计算化学等关键词检索。
- PubMed E-utilities：化学生物学、药物化学、分析化学、代谢组学等关键词检索。
- Crossref：JACS、Angewandte Chemie、Nature Chemistry、Science、ACS、RSC 代表性期刊。
- RSS：C&EN (ACS)、Nature Chemistry、Science、Chemistry World (RSC) 等新闻/目录源。

说明：ACS、RSC、Nature、Science 等出版商页面经常有访问限制或反爬策略，因此脚本优先使用 Crossref/RSS 等稳定接口。某个来源失败时会记录日志并跳过，不会中断整份日报。

## 安装

```bash
cd "/Users/zhangzimo/Library/Mobile Documents/com~apple~CloudDocs/chem-news-daily"
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
export CHEM_NEWS_DAYS="3"
export CHEM_NEWS_MAX_ITEMS="30"
export CHEM_NEWS_MAX_AI_ITEMS="30"
```

`NCBI_EMAIL` 和 `CROSSREF_MAILTO` 不是必需项，但建议填写，便于遵守 PubMed/Crossref 的礼貌访问规范。

如果对应供应商的 API Key 存在，脚本会调用模型 API 生成中文标题、今日重点、分领域摘要和简评。如果没有配置 API Key，脚本会自动使用本地 fallback summaries，不会因为缺少 Key 直接崩溃。

默认日报会根据来源重要性、研究新近性、摘要信息量和学习价值关键词压缩到 30 篇。学习价值关键词包括 review、perspective、mechanism、benchmark、platform、general method、design principle 等。

## 邮件发送

生成 `.docx` 后，脚本会先保存 Word 文件，再尝试把该文件转换为 PDF 并通过 SMTP 发送到默认收件人。支持多个收件人，用英文逗号或分号分隔：

```text
2510248@mail.nankai.edu.cn
```

需要配置 SMTP。建议写入 `.env`：

```env
REPORT_EMAIL_TO=2510248@mail.nankai.edu.cn,second@example.com
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
- 邮件附件只发送 PDF；本地输出目录仍保留 `chem_news_YYYY-MM-DD.docx`。
- PDF 转换依赖 LibreOffice。macOS 可安装 LibreOffice；如果命令不在 PATH，可设置 `LIBREOFFICE_PATH=/Applications/LibreOffice.app/Contents/MacOS/soffice`。
- 如果 SMTP 未配置或 PDF 转换失败，脚本只会记录 `Email not sent`，不会影响 Word 生成。

## 运行

生成最近 3 天日报：

```bash
python main.py
```

只看最近 24 小时：

```bash
python main.py --days 1
```

不调用模型 API，仅测试抓取和 Word 输出：

```bash
python main.py --no-openai --verbose
```

指定输出目录：

```bash
python main.py --output-dir "$HOME/Documents/ChemNewsDaily"
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
0 8 * * * cd "/Users/zhangzimo/Library/Mobile Documents/com~apple~CloudDocs/chem-news-daily" && /bin/zsh -lc 'source .venv/bin/activate && python main.py >> "./output/run.log" 2>&1'
```

也可以用 macOS `launchd`、GitHub Actions 或服务器定时任务运行。只要保证所选供应商的 API Key 环境变量可用即可。

## GitHub Actions 自动运行

项目包含 `.github/workflows/daily.yml`，会每天北京时间 07:30 自动运行一次。由于 GitHub Actions 的 cron 使用 UTC，workflow 中对应的是 `30 23 * * *`。

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
- `REPORT_EMAIL_TO`：收件人，默认 `2510248@mail.nankai.edu.cn`；多个邮箱用英文逗号或分号分隔。
- `SMTP_HOST`、`SMTP_PORT`、`SMTP_USERNAME`、`SMTP_PASSWORD`、`SMTP_FROM`、`SMTP_SECURITY`：用于发送 PDF 附件邮件。

workflow 会把 Secrets 注入为环境变量：

```yaml
LLM_PROVIDER: ${{ secrets.LLM_PROVIDER }}
OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
OPENAI_MODEL: ${{ secrets.OPENAI_MODEL }}
DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
DEEPSEEK_MODEL: ${{ secrets.DEEPSEEK_MODEL }}
REPORT_EMAIL_TO: ${{ secrets.REPORT_EMAIL_TO }}
SMTP_HOST: ${{ secrets.SMTP_HOST }}
SMTP_PORT: ${{ secrets.SMTP_PORT }}
SMTP_USERNAME: ${{ secrets.SMTP_USERNAME }}
SMTP_PASSWORD: ${{ secrets.SMTP_PASSWORD }}
SMTP_FROM: ${{ secrets.SMTP_FROM }}
SMTP_SECURITY: ${{ secrets.SMTP_SECURITY }}
```

如果没有配置对应 API Key，workflow 仍会运行，脚本会使用 fallback summaries 生成文档或失败报告。

workflow 会安装 LibreOffice Writer 和 Noto CJK 字体，用于把本地保存的 Word 报告转换为邮件 PDF 附件。

手动运行：

1. 打开 GitHub 仓库的 `Actions` 页面。
2. 选择 `Daily Chem News`。
3. 点击 `Run workflow`。
4. 选择分支后再次点击 `Run workflow`。

下载 artifact：

1. 打开对应的 workflow run。
2. 在页面底部找到 `Artifacts`。
3. 下载 `chem-news-daily-output`。
4. 解压后即可看到生成的 `.docx`；如果本次完成了邮件 PDF 转换，也会包含同名 `.pdf`。正常情况为 `chem_news_YYYY-MM-DD.docx`，抓取为 0 条时为 `运行失败报告.docx`。

GitHub Actions 只调用公开 API/RSS/元数据接口和你配置的模型 API，不会自动登录学校账号，也不会下载受版权保护的 PDF。

## 输出结构

Word 文档包含：

- 标题：化学科研资讯日报
- 日期
- 今日重点 5 条
- 分领域摘要
- 每条资讯的中文标题、原始英文标题、来源、发布日期、链接、摘要、简评

## 常见问题

如果 Word 中某些出版商条目显示“出版商元数据未提供摘要”，说明 Crossref 没有返回该论文摘要。脚本仍会保留标题、来源、发布日期、DOI/链接，并在简评中说明信息有限。

如果模型 API 调用失败，脚本会自动退回到本地规则生成简评，保证 `.docx` 仍然生成。
