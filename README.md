# 世界来信 · Kindle Intelligence Brief

个人新闻简报服务。保留原项目的来源管理、真实原文截图核查、HTML 和 EPUB 排版，将同一条流水线用于 Windows 本地试运行及 GitHub Actions Ubuntu 一次性任务。

**当前状态：基础版已上传目标仓库并通过 Ubuntu Chromium 测试；真实模型调用因 API 额度问题尚未成功，Kindle 投递尚未验证。本次模型切换功能仍需上传并测试。**


## 切换模型 API 服务商

云端 GitHub Actions 的 **Secrets** 中设置 `LLM_API_KEY`（新服务商密钥）；**Variables** 中设置 `LLM_MODEL`（该服务商的准确模型 ID）、`LLM_API_BASE_URL`（HTTPS API 根地址，例 `https://example.com/v1`）、`LLM_API_FORMAT`（`responses` 或 `chat_completions`）。这些配置覆盖旧的 `OPENAI_API_KEY`、`OPENAI_MODEL`、`OPENAI_BASE_URL`；旧配置继续可用。切换前先确认密钥、模型、地址属于同一服务商。不要在聊天或仓库文件中填写密钥。

`responses` 适用于兼容 OpenAI Responses API 的服务；`chat_completions` 适用于兼容 Chat Completions API 且支持 `response_format: json_object`、图片输入的服务。程序会将目标 JSON Schema 放进提示词，并在收到结果后用 Pydantic 校验；输出不符合结构或事实证据核查失败时不会生成可投递简报。兼容 Chat Completions 并不保证图像、JSON 模式、token 参数都可用，需先用 `dry_run=true` 验证。API 根地址不要包含 `/responses` 或 `/chat/completions`，程序会按格式追加路径。

本地可用同名环境变量，或在管理页面设置 API 根地址、接口格式、模型名称与密钥。GitHub Variables/Secrets 仅作用于云端，管理页面保存的本机密钥不会上传 GitHub。

## 1. 流程与边界

### 受限原文的公开版本回退

如果原网页只显示订阅提示，采集器会检查该出版社在页面中声明的 `rel=amphtml` 公开替代页。只接受同一主机名的地址；替代页也必须实际显示可读正文。证据截图从最终显示的网页段落直接拍摄，简报同时列出原始文章链接和截图页链接。两页都无法阅读时将该文章标记为 `AccessRestricted` 并跳过，不使用缓存、搜索片段或第三方转载来补造证据。此功能不适用于真正需要订阅或登录的内容。

用户提供的 Bypass Paywalls Clean 压缩包采用 Chrome Manifest V2；当前 Chromium 已停止支持，且扩展包含广泛的站点与 Cookie 权限，因此不把它装进 GitHub Actions。项目本身没有复制或执行该扩展。

RSS/Atom/网页发现候选 → 标题/日期/来源规则 → 隔离 Chromium 打开原文 → 等待动态正文和滚动 → article/main 正文清洗 → canonical/正文哈希/相似度去重 → 事件聚类 → 六维评分及14天历史对照 → 最多30个事件交给模型 → 中文编辑 → 核心事实逐句绑定原文段落 → 实际 DOM 截图 → 图文复核 → HTML + EPUB → SMTP → 历史元数据持久化。

- 默认候选上限300、日报最多16项、周报最多20项。质量不足允许少量条目，最少条数在配置中调整；没有合格内容会失败，不用旧闻凑数。
- 每条核心事实配原网页段落截图，并在新闻末尾列出原始链接、原文标题及时间。截图记录来源表述，不能独自证明表述真实。
- 官方声明、个人观点、研究结果、单一来源和交叉核对报道分开标注。
- 同一模型的第二次核查减少部分错误，**不等于独立人工事实核查**。跨语言轻量聚类、事件更新判断和来源独立性仍有误差。
- 不绕过付费墙、登录限制、验证码。此类来源可保留在观察名单，不能假称已经自动全文订阅。
- 保留108个候选来源，其中23个 RSS 配置默认启用；其余为待接入/手动观察项。默认启用表示尝试采集，不代表已通过持续可用性验收。X、付费媒体及部分人物动态尚无完整自动适配器。

## 2. 本地安装

需要 Python 3.12、Git（仅云端持久化需要）；Node 不参与新闻任务，只用于可选的本地界面语法检查。

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Ubuntu：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m playwright install --with-deps chromium
```

Windows 若 Chromium 尚未安装，可使用隔离的系统 Edge 进程回退；Ubuntu 不使用此回退，必须成功启动 Playwright Chromium。

## 3. 配置

| 文件 | 调整内容 |
|---|---|
| `config/sources.json` | 来源增删、启用/禁用、订阅地址、地区、语言、机构分组、优先级、站点正文选择器 |
| `config/interests.json` | 兴趣、黑白名单、关键词、长度/相似度、六维权重、历史期限、趋势和深读阈值 |
| `config/settings.json` | 数量、浏览器超时、滚动次数、正文长度、模型及 token 预算、语言和时区 |
| 环境变量 / GitHub Secrets | 密钥、邮箱、可选覆盖项 |

优先级 `priority` 为1–5；`group` 填实际媒体机构/共同稿源，不能给同一机构的不同账号假设独立性。来源规则的白名单/黑名单填写 source ID（如 `s015`），空白表示不限定。`adapter` 支持 `rss`、`page`、`manual`。页面来源可设置 `link_selector` 和 `content_selector`。缺少可信发布时间的文章不进入简报。

六维满分100：Importance30 / Relevance25 / Novelty20 / SourceQuality10 / CrossSource10 / Depth5。这是可解释的规则估分，不是对“客观重要性”的准确测量。单项得分和淘汰计数保存在运行统计中。

环境变量模板见 `.env.example`。**程序不会自动加载 `.env`**；请通过 shell 或 GitHub 设置注入。不要把密钥写入 JSON、命令行参数或提交到 Git。

PowerShell 中设置本次进程变量，例如：

```powershell
$env:OPENAI_MODEL = '你的图像和结构化输出模型名称'
# API 密钥请使用本地安全配置界面或环境变量管理器注入。
python -m briefing.daily_brief --dry-run --limit 10
```

本地保留的管理界面：`python -m briefing serve`，浏览器访问 `http://127.0.0.1:8765`。Windows 密钥使用当前用户 DPAPI 加密。界面修改的是本机数据库；若要影响云端，导出来源 JSON 替换仓库的 `config/sources.json` 并提交。云端始终以 config 文件为准。本机定时器在迁移云端后保持关闭，避免两个独立状态库同时发信。

## 4. GitHub 部署

1. 建立私有仓库或 Fork/使用现有仓库，将本项目文件放在**仓库根目录**，不要把包含个人运行数据的 `data/` 整个上传。发布 ZIP 已仅包含空 `data/state.json`。
2. Push 默认分支。确认 `.github/workflows/daily-brief.yml` 和 `test.yml` 已存在。
3. 进入 **Settings → Secrets and variables → Actions → New repository secret**，添加下表所有 Secrets。
4. 在同一页面的 **Variables** 添加 `LLM_MODEL`、`LLM_API_BASE_URL`、`LLM_API_FORMAT`；完成 Amazon 白名单后设置 `APPROVED_SENDER_CONFIRMED=true`。OpenAI 旧变量 `OPENAI_MODEL` 继续可用。
5. **Actions → Verify Python and Chromium → Run workflow**。这个验收任务不需要模型/邮箱密钥，使用 Ubuntu 真 Chromium 打开本地动态测试页并生成真实截图，执行单元及集成测试。
6. **Actions → Daily Kindle Brief → Run workflow**，第一次保持 `dry_run=true`、`limit=10`。成功后下载 Artifacts 查看 HTML/EPUB 与统计。
7. 确认截图和文章质量，再手动运行 `dry_run=false` 验证 Gmail → Kindle。随后保持 workflow enabled，个人电脑可以关机。

运行依赖 GitHub 的 `GITHUB_TOKEN` 具有 `contents: write`。工作流已声明；如果仓库/组织策略禁止，或默认分支保护阻止机器人直接提交，则发送前的状态提交会失败，**邮件不会发送**。需要由仓库所有者选择允许的仓库策略或使用专用仓库。不要为了部署公开私人邮箱或密钥。

### 必填 Secrets

| 名称 | 内容 |
|---|---|
| `LLM_API_KEY` | 当前服务商的模型 API 密钥；旧的 `OPENAI_API_KEY` 仍兼容 |
| `SMTP_HOST` | Gmail 填 `smtp.gmail.com` |
| `SMTP_PORT` | SSL 填 `465`；STARTTLS 填 `587` 并修改 smtp_security |
| `SMTP_USERNAME` | 完整 Gmail 地址 |
| `SMTP_PASSWORD` | Gmail 应用专用密码；不要使用普通登录密码 |
| `EMAIL_FROM` | 发件邮箱，通常与 SMTP_USERNAME 相同 |
| `KINDLE_EMAIL` | 你的 Send to Kindle 邮箱 |

Gmail 账号须允许使用应用专用密码，通常需要两步验证。Amazon 的 **Manage Your Content and Devices → Preferences → Personal Document Settings** 中，把发件 Gmail 加入认可的发件人列表。SMTP 接受邮件不代表 Kindle 一定收录；首次可能需要 Amazon 验证，需在设备上检查。

### 可选覆盖项

本地支持 `LLM_API_BASE_URL`、`LLM_API_FORMAT`、`SMTP_SECURITY`、`MAX_CANDIDATES`、`MAX_FINAL_ITEMS`、`TIMEZONE`、`LLM_TOKEN_BUDGET`。云端工作流已映射模型密钥、模型 ID、API 根地址和接口格式；其余覆盖项默认读取 config。

支持 `LLM_INPUT_USD_PER_MILLION` / `LLM_OUTPUT_USD_PER_MILLION`（或对应 settings 字段）。填写你实际模型的每百万 token 单价后，统计输出估计费用；未填写时只报告 token，不捏造金额。估值按普通输入/输出价计算，不细分缓存折扣。

## 5. 时间、日报与周报

GitHub cron 使用 UTC：

| 任务 | 北京时间启动 | workflow cron |
|---|---|---|
| 日报 | 每天07:30 | `30 23 * * *`（UTC 前一天23:30） |
| 周报 | 周六09:00 | `0 1 * * 6` |

修改时间要改 workflow 中的 cron；仅修改 settings 的 daily_time/weekly_time 会影响本机定时器，不改变 GitHub 触发器。如修改周报 cron，还要同步 `scripts/actions_run.py` 的周报判别字符串。

**这是启动时间，不是准时收件承诺**：采集、模型编辑、GitHub 排队和 Amazon 入库都有延迟。GitHub 定时任务在高负载时可能延迟或丢弃，且仅默认分支生效；公开仓库长期无活动还可能停用 schedule。可手动补跑。两种简报使用不同 delivery ID，周六日报不会挡住额外周报。

周报会重新读取过去一周的候选，以及已发送历史中保存的原文链接；不会只凭过期短摘要生成“新截图”。原文失效、付费墙或日期不可验证的内容会被跳过，覆盖并非百分之百。

## 6. 命令行

```bash
# 真采集 + 真模型 + 排版，但不发信、不记为已发送
python -m briefing.daily_brief --dry-run --limit 10

# 不调用模型，只验证候选、浏览器、正文、规则、评分
python -m briefing.daily_brief --collect-only --limit 10

# 正式发送日报
python -m briefing.daily_brief

# 周报
python -m briefing.daily_brief --kind weekly

# 同日已经发送或结果不明，核查 Gmail / Kindle 后才使用
python -m briefing.daily_brief --force

# 工作流内部使用：发送前后把状态提交至 GitHub
python -m briefing.daily_brief --persist-git
```

默认的老入口 `python -m briefing daily/weekly/collect` 仍向本机服务排队。云端和一次性运行请使用 `briefing.daily_brief`。

`--limit` 限制进入正文采集的候选数，RSS 发现仍检查所有启用来源；留空时默认从原定信息源轮流取得最多500条初步信息。规则评分和模型先把它们收窄到最多40个事件簇，再经过原文重开、逐字引文、截图和独立复核，质量充足时形成15—25条日报或周报，最多25条。15条是选材目标而非最低配额：当天合格内容不足时会少发，不能用重复或低质量新闻补足。手动填写较小的 `limit` 会相应减少可选内容。

`--force` 覆盖当天投递防重复，并从重复判断中排除当天同类简报的已发记录，允许重新编排并发送。它不关闭事实核查、日期过滤和质量规则；原文失效等情况仍可能导致生成失败。要仅重看当天已生成版面，下载原运行 Artifacts。

## 7. 状态与重复投递

- `data/state.json` 保存最近14天、最多700个已发送事件的 URL、标题、内容哈希、事件指纹、短摘要及投递状态，**不提交完整网页正文**。
- 发送键为 `daily:本地日期` / `weekly:本地日期`。
- SMTP 登录后先写 `sending`，原子保存并 commit/push 到 GitHub；成功后才执行 SMTP DATA。推送失败即停止。
- SMTP 接受后写 `smtp_accepted`，保存已发送事件，再次提交。每次正常投递通常两次小状态提交，这是为降低“邮件已发但状态丢失”的风险所需。
- 发送期间断线记 `uncertain`；下次不会自动重发。SMTP 没有端到端 exactly-once 协议，本实现优先避免重复，结果不明可能需要人工核查。
- 日报 workflow 共享 concurrency，日报、周报、手动运行共用状态锁；本机发送另有跨进程锁。日报工作流不监听 push；独立测试工作流仅监听代码/配置路径变更，状态提交不会自触发运行。
- 过期状态会被清理，但 Git 提交历史不会随 JSON 清理自动缩小；小体量元数据适合个人规模，长年使用仍应关注仓库体积。

**不要同时运行另一个分支、另一个仓库或未同步状态的本机自动发信服务。** 它们有各自状态，无法互相防重发。

## 8. 运行结果与排错

日志阶段：`FETCH / EXTRACT / FILTER / DEDUP / CLUSTER / SCORE / LLM / RENDER / EMAIL / STATE / SUMMARY`。

`data/jobs/*.stats.json`：来源数量、候选、成功/失败、每层剩余、调用数/token、最终条数、是否 SMTP 接受及耗时。
`*.scores.json`：事件各维度得分和新颖性理由。
`data/editions/<id>/index.html` / `briefing.epub`：可读产物。

Artifacts 保存7天，只打包简报、所引用截图、统计和评分；不上传原网页 HTML、数据库、设置或密钥。下载后解压完整目录再打开 `editions/<id>/index.html`，才能显示相对路径截图。邮件附件和下载的 EPUB 统一命名为 `日期_世界来信-日报或周报_本期头条.epub`；服务内部仍保留 `briefing.epub`，不影响旧投递流程。

周报除一周新闻和原有“值得深读”外，新增“热点背景深读”：根据本周前两条重点新闻提炼事件／人物搜索词，在较早年份搜寻报道，仅保留能打开原站、确认发表日期、正文足够长且与主题相关的来源。每篇附中文标题、300—700 字译读摘要、文章要点、与本周事件的联系、阅读局限、历史发表日期和原文链接；旧报道不冒充本周最新消息。出于版权和附件体积考虑，这里提供忠实的中文译读摘要，不转载或全文翻译第三方报道。搜索依赖 Google News RSS 的历史检索；如果检索、原站访问或译读生成失败，周报照常生成，并说明本期没有通过筛选的背景文章。该栏目不把旧报道中的内容写成新的核心新闻事实。

### 在 Windows 电脑上自动备份 EPUB

云端运行不会自动写入本机磁盘。安装 [GitHub CLI](https://cli.github.com/) 后，在这台电脑运行 `gh auth login`，然后在仓库目录执行：

```powershell
python scripts/backup_local.py
powershell -ExecutionPolicy Bypass -File scripts/install_backup_task.ps1
```

第一条命令立即同步，第二条创建每天 11:00 的 Windows 计划任务（电脑需要开机或稍后唤醒；错过的任务会在可用时启动）。备份默认保存在 `文档\Letters-from-the-World\backups`，使用与邮件附件相同的易读文件名，已有文件不会覆盖。即使邮件发送失败，只要生成阶段成功且 Actions 上传了产物，仍可同步。GitHub 产物只保留 7 天，所以长期关机后应手动到 Actions 下载漏掉的产物。本机直接运行简报时，原始 EPUB 也保存在 `data/editions/<id>/briefing.epub`。目前没有生成 PDF；EPUB 可直接手动发送至 Kindle。

- `SourceAddressBlocked`：DNS 返回了内网/保留地址。当前开发电脑发现 Fake-IP 代理将新闻域名解析为 `198.18.x.x` / 私有 IPv6，采集器因此阻止访问；请在正常公共 DNS 的云端验收，或由使用者调整代理解析方式。程序没有关闭此保护。
- 单篇失败 warning、单源失败 error，继续其他内容；无合格新闻、核心配置/模型/渲染/邮件失败则退出1。
- 模型 token 预算耗尽时，只保留此前已完成截图复核的条目；如果不足最低条数则不发信。
- 验证墙/付费墙：禁用该源或使用合规的可访问订阅入口，不以搜索摘要冒充原文。
- SMTP 登录失败：检查应用专用密码与账号政策；SMTP 接受但 Kindle 未收到：检查 Amazon 发件白名单、验证邮件和附件大小。
- `sending/uncertain`：先核查 Gmail 与 Kindle，再决定是否 `--force`。不要直接删除防重发记录。

## 9. 测试

```bash
python -m compileall -q briefing tests scripts
python -m pytest -q
# Ubuntu / bash
RUN_BROWSER_TESTS=1 python -m pytest -q
# Windows / PowerShell
$env:RUN_BROWSER_TESTS='1'
python -m pytest -q
# 可选，本机已安装 Node 时
python scripts/check_web.py
```

覆盖 URL/正文去重、聚类、历史新颖性、分数、配置、防重发、SMTP 不确定结果、远程提交失败先于邮件、真实 Git 提交只包含状态、结构化模型请求、预算、截图完整性及动态浏览器到 EPUB 的集成。浏览器集成使用本地测试网页，模型和 SMTP 使用测试替身；不把这些结果称为真实新闻质量或真实投递验收。

## 10. 参考

- [Playwright Python CI](https://playwright.dev/python/docs/ci) 与 [截图 API](https://playwright.dev/python/docs/screenshots)：Ubuntu 浏览器安装与原 DOM 截图。
- [GitHub schedule](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule) 与 [concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)：UTC、延迟、并发与默认分支限制。
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)：结构化输出约束。
- [Gmail SMTP](https://support.google.com/mail/answer/7104828?hl=en)：发件设置。
- 你提供的 [n8n workflows](https://github.com/lucaswalter/n8n-ai-workflows)、[AI News Bot 文章](https://medium.com/@fengliu_367/build-your-own-ai-news-bot-automated-daily-digests-with-claude-and-github-actions-bc3d48e67d98)、[RSSMonster](https://github.com/pietheinstrengholt/rssmonster)：借鉴分阶段采集、历史过滤与来源管理思路；未引入 n8n、向量数据库或新的大型后台。
