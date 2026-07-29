# 科研资讯日报自动化项目

这个项目会从 arXiv、PubMed、Crossref 期刊元数据、OpenAlex 学术索引和公开 RSS 源检索近 24 小时到 3 天内的前沿论文/科研资讯，调用 OpenAI 或 DeepSeek 生成中文标题、简短中文摘要和分领域摘要，并输出 Word 文档。固定日报仍保留化学、有机化学、生物、统计学和工商管理五套；用户专属日报则支持完整学科目录和可编辑研究画像。配置 SMTP 后，本地仍保存 `.docx`，邮件附件会自动转换为 `.pdf`。

默认输出：

```text
./output/chem_news_YYYY-MM-DD.docx
./output/organic_chem_news_YYYY-MM-DD.docx
./output/bio_news_YYYY-MM-DD.docx
./output/stat_news_YYYY-MM-DD.docx
./output/business_news_YYYY-MM-DD.docx
```

默认输出目录位于项目内，避免定时任务写入 `~/Documents` 或 iCloud 目录时遇到权限问题。仍可通过 `--output-dir` 手动指定其他目录。

## 支持学科与来源

固定日报继续使用原有五个专业 profile，不受用户专属画像扩展影响：

- 化学：arXiv、PubMed、JACS、Angewandte Chemie、Nature Chemistry、Science、ACS、RSC 和 Chemistry World。
- 有机化学：Organic Letters、The Journal of Organic Chemistry、JACS、Angewandte Chemie、Nature Chemistry、Chemical Science、ACS Catalysis、arXiv/PubMed 有机合成与药物化学关键词、Chemistry World。
- 生物：arXiv q-bio、PubMed、Nature、Science、Cell、Nature Biotechnology、Nature Methods、Nature Genetics、Nature Medicine、PLOS Biology、eLife 等。
- 统计学：arXiv stat/math.ST、PubMed 生物统计关键词、Annals of Statistics、Biometrika、JASA、JRSS B、Statistical Science、Bayesian Analysis、Bernoulli、JMLR 等。
- 工商管理：arXiv 管理研究关键词，以及 Crossref 中 36 本已核验 ISSN 的英文管理学、组织行为、人力资源、营销、创新创业、运营、信息系统和公司治理期刊。

用户专属日报在上述专业 profile 外，提供以下 14 个一级学科入口：哲学、经济学、法学、教育学、文学、历史学、理学、工学、农学、医学、管理学、艺术学、交叉学科、军事学。每个入口可再由用户主题、包含/排除关键词和来源偏好细化。计算机科学是工学下的专门入口，覆盖 AI/智能体、数据管理与时空数据、系统软件和人机交互。

信息来源按证据层级分开标记：

- `学术研究`：arXiv、PubMed、Crossref 和 OpenAlex。OpenAlex 用于跨学科发现，属于学术索引，不等同于同行评议结论。
- `官方发布`：期刊、学会、实验室和项目所有者的公开 RSS。
- `社区信号`：公开 Hacker News 故事和计算机科学 profile 的白名单 GitHub Release。它们只用于发现新线索，不作为学术证据；同批有学术条目时不会进入“今日重点”。

不接入需要登录、身份难核验或接口不稳定的平台，例如 X、微信、小红书、私有群组。用户不能让系统抓取任意账号或任意 URL。

说明：出版商页面经常有访问限制或反爬策略，因此脚本优先使用 Crossref/RSS/API 等稳定接口。某个来源失败时会记录日志并跳过，不会中断整份日报。

工商管理 Crossref 配置只接入 36 本可验证的英文期刊。中文推荐期刊暂未接入，因为当前公开元数据接口的覆盖和可核验性不足；`International Journal of Operations & Production Management` 也未接入，因为现有 Crossref ISSN 映射错误，可能把无关内容混入日报。

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
export OPENALEX_API_KEY="你的 OpenAlex API Key"
export GITHUB_SOURCE_TOKEN="可选的 GitHub token，仅用于公开 release 查询"
export REPORT_PROFILE="chemistry"  # 可选 profile 由 `python main.py --help` 列出
export CHEM_NEWS_DAYS="3"
export CHEM_NEWS_MAX_ITEMS="30"
export SCIENCE_NEWS_MIN_ITEMS="15"
export SCIENCE_NEWS_HISTORY_DAYS="10"
export SCIENCE_NEWS_HISTORY_DIR=".report-history"
export CHEM_NEWS_MAX_AI_ITEMS="30"
```

`NCBI_EMAIL` 和 `CROSSREF_MAILTO` 不是必需项，但建议填写，便于遵守 PubMed/Crossref 的礼貌访问规范。启用 OpenAlex 来源时需要设置 `OPENALEX_API_KEY`；可以在 [OpenAlex Settings](https://openalex.org/settings/api) 创建免费 key。`GITHUB_SOURCE_TOKEN` 为可选项，只会随 GitHub Release 请求发送，用于提高公开 GitHub API 的限额；不会发送给其他来源，也绝不能提交到仓库。

如果对应供应商的 API Key 存在，脚本会调用模型 API 生成中文标题、今日重点、分领域摘要和简短中文摘要。如果没有配置 API Key，默认本地运行会自动使用规则模板生成标题和 fallback summaries，不会因为缺少 Key 直接崩溃。所有学科标题都会优先突出研究对象、方法、材料/体系、机制、模型、数据类型或证据边界，避免营销号式反问和悬念表达。

默认日报会根据来源重要性、研究新近性、摘要信息量和学习价值关键词优先筛选高质量条目，数量会在 15-30 篇之间动态调整。学习价值关键词包括 review、perspective、mechanism、benchmark、platform、general method、design principle 等。

脚本会在 `.report-history/` 记录各学科已生成日报的 DOI、链接、标题指纹和主题指纹，并默认参考最近 10 天历史降低跨天重复。完全相同的 DOI/链接/标题会优先剔除；主题相近但质量很高的条目会被降权而不是一刀切删除。GitHub Actions 会通过 cache 保存这份历史，因此 cronjob、目标邮箱 workflow 和私人邮箱 workflow 都共用同一套跨天去重逻辑。

Word 输出会保留常见科学记号的上下标：HTML `<sub>/<sup>`、化学式中的数字下标（如 `H2O`、`CO2`、`Na2SO4`）、同位素质量数（如 `18O`、`13C`、`H2^18O`）、离子电荷（如 `Fe3+`、`NH4+`）以及数学标记（如 `R^2`、`x_i`、`a^n`）会写成真正的 Word 上/下标。配置模型 API 后，脚本还会增加一轮 AI 科学排版校对，只允许模型插入 `^{...}` / `_{...}` 标记，并会校验去掉标记后的文字必须与原文一致，避免模型改写内容。

## 邮件发送

生成 `.docx` 后，脚本会先保存 Word 文件，再尝试把该文件转换为 PDF 并通过 SMTP 发送。每个学科可以配置不同收件人，多个收件人用英文逗号或分号分隔：

```text
2510248@mail.nankai.edu.cn
```

需要配置 SMTP。建议写入 `.env`：

```env
REPORT_EMAIL_TO=2510248@mail.nankai.edu.cn,second@example.com
CHEM_REPORT_EMAIL_TO=chem-reader@example.com
ORGANIC_REPORT_EMAIL_TO=organic-reader@example.com
BIO_REPORT_EMAIL_TO=bio-reader@example.com
STAT_REPORT_EMAIL_TO=stat-reader@example.com
BUSINESS_REPORT_EMAIL_TO=business-reader@example.com
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
- `ORGANIC_REPORT_EMAIL_TO` 控制有机化学日报目标收件人。
- `BUSINESS_REPORT_EMAIL_TO` 是工商管理日报的专属目标收件人；工商管理不会回退到 `REPORT_EMAIL_TO`，避免把管理类日报误发给通用收件人。
- `REPORT_EMAIL_TO` 是化学、有机化学、生物和统计学的通用目标收件人兜底；这些学科的专属收件人为空或被 SMTP 全部拒收时，会尝试回退到 `REPORT_EMAIL_TO`。
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

生成有机化学、生物、统计学、工商管理或计算机科学日报：

```bash
python main.py --profile organic_chemistry
python main.py --profile biology
python main.py --profile statistics
python main.py --profile business_management
python main.py --profile computer_science
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
python main.py --profile organic_chemistry --output-dir ./output --no-email
python main.py --profile biology --output-dir ./output --no-email
python main.py --profile statistics --output-dir ./output --no-email
python main.py --profile business_management --output-dir ./output --no-email
python main.py --profile computer_science --output-dir ./output --no-email
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
0 8 * * * cd "/Users/zhangzimo/Library/Mobile Documents/com~apple~CloudDocs/science-news-daily" && /bin/zsh -lc 'source .venv/bin/activate && python main.py --profile chemistry >> "./output/run.log" 2>&1 && python main.py --profile organic_chemistry >> "./output/run.log" 2>&1 && python main.py --profile biology >> "./output/run.log" 2>&1 && python main.py --profile statistics >> "./output/run.log" 2>&1'
```

也可以用 macOS `launchd`、GitHub Actions 或服务器定时任务运行。只要保证所选供应商的 API Key 环境变量可用即可。

## GitHub Actions 自动运行

项目现在把 GitHub Actions 拆成固定日报、手动预览和统一用户调度等独立 workflow，避免“手动测试、私人邮箱、每日自动任务”互相干扰。

单科目标收件人 workflow：

- `.github/workflows/target-chemistry.yml`：`Chemistry News - Target Email`，发送到 `CHEM_REPORT_EMAIL_TO`；为空或拒收时回落到 `REPORT_EMAIL_TO`。
- `.github/workflows/target-organic-chemistry.yml`：`Organic Chemistry News - Target Email`，发送到 `ORGANIC_REPORT_EMAIL_TO`；为空或拒收时回落到 `REPORT_EMAIL_TO`。
- `.github/workflows/target-biology.yml`：`Biology News - Target Email`，发送到 `BIO_REPORT_EMAIL_TO`；为空或拒收时回落到 `REPORT_EMAIL_TO`。
- `.github/workflows/target-statistics.yml`：`Statistics News - Target Email`，发送到 `STAT_REPORT_EMAIL_TO`；为空或拒收时回落到 `REPORT_EMAIL_TO`。
- `.github/workflows/target-business-management.yml`：`Business Management News - Target Email`，只发送到 `BUSINESS_REPORT_EMAIL_TO`，不回落到 `REPORT_EMAIL_TO`。

单科私人邮箱 workflow：

- `.github/workflows/personal-chemistry.yml`：`Chemistry News - Personal Email`，发送到 `PERSONAL_REPORT_EMAIL_TO`。
- `.github/workflows/personal-organic-chemistry.yml`：`Organic Chemistry News - Personal Email`，发送到 `PERSONAL_REPORT_EMAIL_TO`。
- `.github/workflows/personal-biology.yml`：`Biology News - Personal Email`，发送到 `PERSONAL_REPORT_EMAIL_TO`。
- `.github/workflows/personal-statistics.yml`：`Statistics News - Personal Email`，发送到 `PERSONAL_REPORT_EMAIL_TO`。
- `.github/workflows/personal-business-management.yml`：`Business Management News - Personal Email`，把 `PERSONAL_REPORT_EMAIL_TO` 作为工商管理专属收件人。

每日自动 workflow：

- `.github/workflows/cronjob-daily.yml`：`Cronjob Daily Research News`，专门给 cron-job.org 等外部定时器触发。
- 监听 `repository_dispatch` 的 `event_type=science-news-daily`，也保留 `workflow_dispatch` 便于手动测试。
- 每次运行固定生成化学、有机化学、生物、统计学四份日报；仅当 `BUSINESS_REPORT_EMAIL_TO` 非空时追加工商管理日报。未配置该变量不会令既有四科失败，也不会把工商管理日报发给 `REPORT_EMAIL_TO`。
- `repository_dispatch` 成功后会保存当天 marker，避免外部定时器重复请求导致当天重复发送。
- 同一次外部唤醒还会运行数据库驱动的用户计划调度器；固定日报的当天 marker 不会跳过用户计划扫描。

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
- `REPORT_EMAIL_TO`：通用目标收件人兜底；多个邮箱用英文逗号或分号分隔。
- `CHEM_REPORT_EMAIL_TO`：化学日报目标收件人；为空或 SMTP 全部拒收时回落到 `REPORT_EMAIL_TO`。
- `ORGANIC_REPORT_EMAIL_TO`：有机化学日报目标收件人；为空或 SMTP 全部拒收时回落到 `REPORT_EMAIL_TO`。
- `BIO_REPORT_EMAIL_TO`：生物日报目标收件人；为空或 SMTP 全部拒收时回落到 `REPORT_EMAIL_TO`。
- `STAT_REPORT_EMAIL_TO`：统计学日报目标收件人；为空或 SMTP 全部拒收时回落到 `REPORT_EMAIL_TO`。
- `BUSINESS_REPORT_EMAIL_TO`：工商管理日报目标收件人；不回落到 `REPORT_EMAIL_TO`。每日 workflow 仅在该 Secret 非空时运行工商管理。
- `PERSONAL_REPORT_EMAIL_TO`：私人手动 workflow 专用收件人，供五条 `personal-*` workflow 使用。
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
ORGANIC_REPORT_EMAIL_TO: ${{ secrets.ORGANIC_REPORT_EMAIL_TO }}
BIO_REPORT_EMAIL_TO: ${{ secrets.BIO_REPORT_EMAIL_TO }}
STAT_REPORT_EMAIL_TO: ${{ secrets.STAT_REPORT_EMAIL_TO }}
BUSINESS_REPORT_EMAIL_TO: ${{ secrets.BUSINESS_REPORT_EMAIL_TO }}
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

使用 cron-job.org、UptimeRobot、服务器 cron、Cloudflare Workers Cron Trigger 等外部定时器，每 30 分钟调用 GitHub `repository_dispatch` API。仓库内的自动入口只有 `.github/workflows/cronjob-daily.yml`；外部定时器不需要知道用户、计划或收件人。

例如 cron 表达式为：

```cron
*/30 * * * *
```

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

外部定时器不需要传 `profiles`；`Cronjob Daily Research News` 会固定运行化学、有机化学、生物、统计学四份日报，并在 `BUSINESS_REPORT_EMAIL_TO` 已配置时追加工商管理日报。同时，它会在 Turso/SQLite 中领取有限数量的到期用户计划。单次最多领取 `MAX_JOBS_PER_RUN`（默认 10）个用户任务，并在 `MAX_RUNTIME_MINUTES`（默认 80）预算内停止领取新任务；未领取任务保留到下一次唤醒。

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
4. 解压后即可看到生成的 `.docx`；如果本次完成了邮件 PDF 转换，也会包含同名 `.pdf`。正常情况会包含对应学科的 `chem_news_YYYY-MM-DD.docx`、`organic_chem_news_YYYY-MM-DD.docx`、`bio_news_YYYY-MM-DD.docx`、`stat_news_YYYY-MM-DD.docx` 或 `business_news_YYYY-MM-DD.docx`；抓取为 0 条时会生成对应失败报告，例如 `business_news_运行失败报告.docx`。

GitHub Actions 只调用公开 API/RSS/元数据接口和你配置的模型 API，不会自动登录学校账号，也不会下载受版权保护的 PDF。

## 专属日报运营面板

仓库新增了一个本地 Streamlit 运营面板，用于维护客户级科研日报。它不会替换现有的 5 套固定学科画像和 11 个 workflow；专属日报仍复用既有的抓取、排序、AI、DOCX、PDF 和 SMTP 路径，只是按保存的客户画像筛选与发送。

面板支持创建和版本化客户科研画像：基础学科、研究主题、包含/排除词、来源、期刊 ISSN、内容偏好、条目上限、模型、输出格式和发送计划。创建时可以用一段自然语言描述客户想追踪的研究兴趣；AI 只会生成可编辑的学科、关键词和信源建议，不能自动保存、发信或使用未在系统白名单中的来源。保存新版画像不会改写已经生成的历史日报配置。

### 新用户开通与预览确认

专属日报必须按以下顺序开通：

```text
必填信息 → 使用当前配置 provider 的大模型建议（可编辑） → 生成预览（不发邮件）
→ 启用计划 → 下一个固定发送时间自动邮件
```

先填写姓名、收件邮箱和一段研究兴趣描述，再由面板生成可编辑的研究画像与计划建议；保存画像后只会创建预览任务。研究兴趣只用于提炼关键词、信源与筛选条件，绝不会直接作为日报主标题；主标题由模型基于当期实际入选内容生成，模型不可用时使用基础学科的通用标题。预览会生成并上传 DOCX artifact，绝不会向收件人发邮件；PDF 转换仅在确认后的正式定时投递中执行。确认预览内容后，点击“启用固定频率计划”才会启用计划；系统会重新计算严格晚于启用时刻的下一次固定发送时间，并由统一 `Cronjob Daily Research News` workflow 的 30 分钟唤醒在该时间后自动发送。

面板的“系统建议”与日报 runner 共用当前配置的模型供应商和凭据：使用 `LLM_PROVIDER` 选择 `openai` 或 `deepseek`，并配置对应的 `OPENAI_API_KEY` 或 `DEEPSEEK_API_KEY`（以及可选模型名）。若当前 provider 缺少或无法使用模型 Key，面板不会静默使用规则模板或其他 fallback 生成建议；它会保留必填信息并提示修正模型配置后重试。

在私有 `.env` 中配置以下变量；`.env.example` 只保留空变量名：

```text
TURSO_DATABASE_URL=
TURSO_AUTH_TOKEN=
MAX_JOBS_PER_RUN=10
MAX_RUNTIME_MINUTES=80
CUSTOM_DELIVERY_LEASE_MINUTES=120
PERSONAL_ADMIN_GITHUB_REPOSITORY=owner/repository
GITHUB_DISPATCH_TOKEN=
```

`TURSO_*` 用于保存画像、计划、报告历史和投递状态。日常面板会在本机维护一个 Turso 读取副本：切换页面、查看用户和投递记录只读取本地副本；点击侧栏的“同步当前状态”才会刷新 GitHub Actions 写入的云端状态。首次启动不会自动联网；首次或缓存为空时，点击该按钮即可建立可读取副本。需要自定义本机缓存位置时，可设置 `PERSONAL_ADMIN_REPLICA_PATH`。`PERSONAL_ADMIN_GITHUB_REPOSITORY` 与 `GITHUB_DISPATCH_TOKEN` 使本地面板可以请求专用的 `Custom User Research Daily` GitHub workflow。Token 只能保存在本地环境，不能写入仓库。

当前使用的 libsql Embedded Replica 只将读取保存在本机；用户画像、计划和暂停状态的写入会直接提交到 Turso 云端主库。因此同步按钮用于拉取最新状态，而不是上传待提交修改。同步临时失败时，面板仍会显示上次已同步的数据；如果尚未成功同步过，面板会显示可重试的空状态，不会执行数据库查询或触发任务。对于一个尚未初始化的空 Turso 数据库，首次成功点击同步会建立项目既有表结构，再读取本地副本。

本地开发可以不使用 Turso，而使用被 Git 忽略的 SQLite 文件：

```bash
export PERSONAL_ADMIN_LOCAL_DB=".personal-admin/dashboard.db"
streamlit run dashboard/app.py
```

同一个 `PERSONAL_ADMIN_LOCAL_DB` 也可让 `custom_user_daily.py scan` 使用 SQLite，便于本地调度验证；GitHub Actions 生产运行仍使用 Turso。两种模式共用同一套迁移、幂等键和条件领取逻辑。

日常使用配置 Turso 后，去掉 `PERSONAL_ADMIN_LOCAL_DB` 并执行相同命令：

```bash
streamlit run dashboard/app.py
```

自动用户计划不再使用独立的 GitHub `schedule`。外部 cronjob 每 30 分钟触发统一 workflow，调度器只扫描 `active` 用户的启用计划和已到期的 UTC `next_run_at`。手动 `Custom User Research Daily` workflow 保留 preview/retry dispatch，仅用于运营操作。

每个自动投递使用“用户 ID + 计划 ID + UTC 应执行周期 + 渠道”的唯一幂等键；数据库使用条件更新记录执行 ID、锁定者、锁定时间和尝试次数，多个 workflow 不能领取同一周期。成功投递后才会按用户时区推进 `next_run_at`，因此延迟唤醒只补当前欠送周期，不会跳过失败任务或一次性补发多期。失败会记录抓取、AI、Word、PDF、邮件或数据库阶段，并按 30、60 分钟的退避重试，最多 3 次；第三次失败会转为最终失败，等待运营处理而不会伪装成“等待重试”。`claimed` 任务超过 `CUSTOM_DELIVERY_LEASE_MINUTES` 会进入下一轮可重试状态；已进入 SMTP `sending` 后超时、SMTP 传输异常或邮件成功后数据库状态写入异常，都会标为“投递结果未知”，默认不自动重发，避免 SMTP 已接收但数据库尚未写回时的重复邮件。只有 SMTP 明确返回未发送时才进入自动重试；“结果未知”需要运营者人工核验后处理。

启用统一调度前，把数据库、模型和 SMTP 变量作为 GitHub Actions secrets 配置，并额外加入 `TURSO_DATABASE_URL` 与 `TURSO_AUTH_TOKEN`。可将 `MAX_JOBS_PER_RUN`、`MAX_RUNTIME_MINUTES` 和 `CUSTOM_DELIVERY_LEASE_MINUTES` 配置为 GitHub Actions repository variables。运行摘要只输出任务数量，不输出邮箱、SMTP 密码、API Key 或 Turso Token。

操作建议：编辑正在服务的客户前先在 Users 页面暂停该客户；保存后会创建新的画像版本，下一次新建报告才使用新版。手动预览 artifact 在 GitHub Actions 中保留 14 天；过期后需要重新生成预览。用户的发送时间在界面按其 IANA 时区显示，数据库保存 UTC；夏令时歧义时间取第一次出现，不存在的本地时间向前顺延。自动投递失败最多自动重试 3 次，且不会在同一轮扫描立即再次发送。

## 输出结构

Word 文档包含：

- 对应学科的日报标题
- 日期
- 今日重点（最多 5 条，按实际收录数量显示）
- 分领域摘要
- 每条资讯的中文标题、原始英文标题、来源、发布日期、DOI/链接、简短中文摘要和原文摘要

## 常见问题

如果 Word 中某些出版商条目显示“出版商元数据未提供摘要”，说明 Crossref 没有返回该论文摘要。脚本仍会保留标题、来源、发布日期、DOI/链接，并在简评中说明信息有限。

如果模型 API 调用失败，脚本会自动退回到本地规则模板生成中文标题和简短中文摘要，保证 `.docx` 仍然生成。
