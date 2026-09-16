# GitHub Actions 云端升级开发报告

日期：2026-09-16

**结论：已完成现有项目的云端代码改造和本地验证；远程部署与 Ubuntu 实机验收尚未完成。** 用户已提供目标仓库 `j959728-hue/Letters-from-the-World`，已确认是新建的空公开仓库；未配置真实模型和 Gmail Secrets。没有发送真实邮件，也没有把测试替身输出作为真实新闻交付。

## 1. 原项目结构与问题

原项目为 `briefing/` Python 应用，包含 SQLite 来源/文章/任务记录、RSS 和浏览器采集、模型编辑、截图复核、EPUB/HTML、SMTP、本地 FastAPI 管理界面及后台队列。

主要问题：候选过早交给模型，没有完整的规则—去重—聚类—评分链；历史只在本机 SQLite；一次性 CLI 只入队不执行；邮件只按 edition ID 防重复；Ubuntu 不能依赖 Windows Edge；正文提取范围偏宽，缺作者和 canonical；周报无法依赖临时 runner 上的旧数据库。

## 2. 本次修改了什么

沿用浏览器、原文段落截图、中文编辑/图文核查、排版和本地界面。新增共享一次性 builder，原队列改为调用它。补正文清洗、统一 Article、低成本过滤去重聚类、六维规则评分、历史/新颖性、趋势与深读、元数据 Git 状态持久化、独立邮件模块、CLI、Actions、文档和测试。

同时修复了检查中发现的旧 pipeline 列表推导式缺失括号、手动来源候选被排除、不同期刊复用截图文件导致旧证据哈希失效、Windows 凭据保存文案与实现不一致，以及本地调度器外层静默吞错。旧 UI 的逐条核查记录仍保留。

## 3. 新增了哪些文件

- `briefing/models.py`、`config.py`、`curation.py`、`state.py`、`llm_client.py`、`builder.py`、`mailer.py`、`daily_brief.py`、`vault.py`。
- `config/sources.json`、`interests.json`、`settings.json`。
- `.github/workflows/daily-brief.yml`、`test.yml`。
- `.env.example`、`.gitignore`、`data/state.json`、`pytest.ini`。
- `scripts/actions_run.py`、`bundle_artifacts.py`、`check_web.py`。
- `tests/conftest.py`、`test_curation.py`、`test_state.py`、`test_delivery.py`、`test_git_state.py`、`test_llm.py`、`test_browser.py`。
- `README.md`、本报告。

这些是本轮服务构建过程中增加的文件；原工程尚无可用 Git 基线，未伪造逐提交变更记录。

## 4. 修改了哪些文件

- `core.py`：配置字段、环境变量密钥、DPAPI、config 来源初始化。
- `collect.py`：URL 规范化、Ubuntu Chromium、动态正文等待/滚动、正文范围、元数据、唯一截图文件名、分级失败日志。
- `editor.py`：接收已评分事件、受限 ID、历史对照、新进展标记、更新复核上下文；调用统一模型客户端。
- `pipeline.py`：保留队列和本地定时，执行交给共享 builder。
- `publish.py`：保留 EPUB、截图验证与原链接，补概览、阅读分区、评分、趋势和深读；邮件入口兼容转发。
- `requirements.txt`：固定当前验证过的依赖版本。

`app.py`、`__main__.py`、`web/index.html` 的本地管理功能继续保留；没有增加 SaaS、账号系统或大型后台。

## 5. 核心模块职责

| 模块 | 职责 |
|---|---|
| core / config | 数据库、本地配置和校验、云端环境覆盖、来源模型 |
| collect | RSS 发现、原浏览器页面读取、正文/元数据、实际截图 |
| models | Article / StoryCluster 数据结构 |
| curation | 规则、hash/SimHash/标题相似度、事件聚类、六维评分、历史差异信号、趋势、深读 |
| llm_client / editor | 唯一模型 HTTP 入口、结构约束、预算/重试、选题、写作、图文复核 |
| builder | 完整流水线、阶段统计、合格条目、周报回读链接、调用排版与发送 |
| publish | HTML/EPUB、证据哈希、XML/ZIP 基础完整性检查 |
| mailer | SMTP、HTML 正文与 EPUB、有限连接重试、发送锁、防重复、结果不确定处理 |
| state | 有界元数据状态、原子写、发送前后 Git 持久化 |
| daily_brief | 一次性入口、环境配置、明确退出码 |
| pipeline / app / web | 复用共享流程的原本机队列和管理界面 |

## 6. 数据处理完整流程

1. 校验配置、同步来源、检查日/周 delivery ID。
2. 并发读取启用的 RSS；网页适配器使用浏览器发现链接，保留手动文章候选。
3. 日期窗口、标题、URL、来源黑白名单等规则先过滤；按来源轮转分配候选预算。
4. 用真实浏览器打开每个原文，等待正文、滚动、读取动态 DOM 和元数据，移除导航/页脚等非正文元素。原始 DOM 不送模型。
5. canonical 去参数、正文规范化 hash、SimHash/相似度去重，优先保留较高来源优先级和信息量。
6. 以标题相似度和时间邻近聚类，用配置权重评分；历史一致的正文排除，相似事件的疑似新事实保留给编辑确认。
7. 最多30个候选事件交给模型，最终最多16条日报/20条周报。
8. 重新打开入选原文，写作绑定逐字原文段落，截取实际 DOM 节点，再做一次图文核查；未通过不刊登。
9. 用已审核核心句组织概览；3项重点，其余关注；趋势必须满足多事件、跨日、经编辑确认更新，深读必须满足长度和实质内容线索。
10. 生成 HTML、EPUB；无合格内容不生成空刊；dry-run 不发送也不记为已发。
11. 正式发送先持久化发送占位，SMTP 接受后保存历史并再提交；任务结束。

## 7. LLM 在哪些阶段调用

仅三类：已评分候选的最终选题（一次）、逐事件中文写作（每项一次）、逐事件原文和截图复核（每项一次）。规则过滤、去重、初次聚类、评分、趋势门槛、深读候选、排版及邮件不调用模型。概览复用已审核核心句，避免额外生成事实。

模型通过结构化输出提供文章 ID、段落 ID 和引文。程序再次检查这些 ID/逐字引文及图片哈希。模型仍可能误解材料或独立性，不能保证新闻绝对无误。

## 8. 每天预计调用多少次 LLM

正常约 `1 + 2N`：8条17次、16条33次、20条41次。少量被拒选题会额外消耗写作/复核调用；网络或服务端限流最多重试3次。全局调用上限120，并受 token 预算限制。不是“500篇各做一次摘要”。

## 9. 如何控制 API 成本

模型只看约20–40个已评分事件，默认30；候选片段限长，历史只给相关短摘要；原文有长度上限；不引入 embeddings、向量库或训练模型；统一客户端检查 token 预算，优先使用返回的实际 usage，未知失败按估值计入预算。达到预算只保留已经完整核查的条目，不发送半审稿件。

默认预算180000 token，可调。图像 token 与模型分词存在误差，因此预算是保守的请求控制，不是账单硬封顶。真实费用取决于你配置的模型；未配置模型/价格前不报告虚构美元成本。可填输入/输出单价输出估算费用，日志保留实际 token。

## 10. GitHub Actions 如何运行

Ubuntu24.04、Python3.12，安装固定依赖、`playwright install --with-deps chromium` 和 CJK 字体，先测试，再运行一次 CLI，上传7天可读产物及脱敏统计。支持 schedule 与 workflow_dispatch，统一 concurrency，失败退出码传到 Actions。

状态仅 `data/state.json`；SMTP DATA 之前必须 commit/push `sending`。测试验证了真实本地 Git bare remote 的状态提交，且不会夹带其他暂存文件。正式远程 push 还未验收。正常一次投递两次状态提交；日报不监听 push，独立测试工作流只监听代码/配置变更，所以状态提交不会自触发循环。

独立 `Verify Python and Chromium` workflow 无需任何发信/模型密钥，可以先做真正 Ubuntu 验收。**该任务目前尚未在 GitHub 跑过。**

## 11. 需要配置哪些 GitHub Secrets

`OPENAI_API_KEY`、`SMTP_HOST`、`SMTP_PORT`、`SMTP_USERNAME`、`SMTP_PASSWORD`、`EMAIL_FROM`、`KINDLE_EMAIL`。

Variables：`OPENAI_MODEL`、`APPROVED_SENDER_CONFIRMED=true`（完成 Amazon 发件白名单后）。GitHub 自带的 `GITHUB_TOKEN` 用于状态提交，无需另建长期 token；仓库策略需允许工作流写入默认分支。具体菜单与 Gmail 设置见 README。

本次没有把用户提供的 Kindle 地址写入可发布 config/ZIP，收件地址只在私密配置/Secrets 注入。

## 12. 如何修改每天发送时间

当前：`30 23 * * *` 是北京时间每日07:30启动日报；`0 1 * * 6` 是周六09:00启动额外周报。

改 `.github/workflows/daily-brief.yml`，UTC = 北京时间减8小时；改周报表达式时同步 `scripts/actions_run.py` 的识别值。生成完成后才发送，GitHub排队、模型处理和 Kindle 入库都有延迟，不承诺准点收件。

## 13. 如何本地 dry-run

安装依赖及浏览器，注入 OPENAI_API_KEY 和 OPENAI_MODEL：

```bash
python -m briefing.daily_brief --dry-run --limit 10
```

只测试采集、不调用模型：`python -m briefing.daily_brief --collect-only --limit 10`。

当前本机 Fake-IP DNS 阻止了真实新闻采集；没有把失败结果写成成功。动态网页和完整生成链用隔离的本地测试服务器验证。

## 14. 如何手动强制重新发送

```bash
python -m briefing.daily_brief --force
python -m briefing.daily_brief --kind weekly --force
```

或 Actions 手动执行，`dry_run=false`、`force=true`。先核查发送结果，尤其 `uncertain/sending`。强制模式允许当天旧内容重新编排，但仍要求重新取得有效原文截图并通过核查。

## 15. 当前仍存在的限制与验收证据

### 已验证

- 22项本地测试通过（包括真实隔离浏览器→动态正文→真实段落截图→HTML/EPUB完整 builder 集成，以及强制重发与历史去重）。
- Python compileall 通过；保留界面的1段内联 JavaScript 通过 `node --check`。
- 核心逻辑涵盖 URL、hash、去重、聚类、历史/更新信号、评分、配置、防重复、SMTP 不确定结果、状态 push 失败先于邮件、Git 只提交状态、模型结构和预算、截图篡改拒绝。
- SMTP 和模型用测试替身；Git 状态测试使用本地 bare remote。它们不是线上服务验证。
- 浏览器测试在本机通过系统隔离 Edge 回退；尚无 Ubuntu Chromium 实测结果。

### 尚未完成

- 上传已指定仓库、GitHub Ubuntu Actions 运行、真实 LLM 内容质量验收、Gmail SMTP 与 Kindle 设备收录验收。
- 108源并非108个已稳定自动订阅的连接器。23个 RSS 默认尝试，人物/X/付费媒体等仍需逐源接入。当前外网采集因本机代理 Fake-IP 被地址保护拒绝，未建立线上成功率基线。

### 已知技术边界

- 多语言标题字面聚类可能漏合并或错合并；最终编辑可继续合并，但不能保证完全识别所有事件。
- 更新信号先用数字/动作词，模型对照短历史再确认；短历史不能覆盖所有背景。
- 趋势目前输出有证据计数和原链接的“持续观察线索”，不自动推断因果或预测；不足条件不生成。
- 深读根据长度、来源和内容线索筛选，仍是初版规则判断。
- 付费墙、验证码、网站结构变化和云端反爬可能降低覆盖；没有绕过机制。
- 截图会增加体积。邮件附 HTML 内嵌图及 EPUB，编码后上限24MB；超限停止，需调少条目/证据段落。
- EPUB 已做 ZIP/XML/图片引用检查，尚未通过完整 EPUBCheck 或真 Kindle 设备兼容性验收。
- SMTP 无法端到端保证 exactly-once；结果不明优先暂停，可能漏发，需要人工查验。
- runner超时、GitHub schedule延迟、默认分支保护、配额和服务限流都会影响无人值守运行。Git历史体积不会随状态保留期自动清理。
- 本地 pytest 默认临时目录曾遇 Windows权限限制；改用工作区的新临时目录重跑全部通过，没有修改系统权限。
- 当前沙箱无法使用 Windows Credential Manager/DPAPI 的用户凭据功能，Git 凭据管理器的设备登录也遇到 Windows TLS 凭据错误；公开仓库可读取，但推送未成功。已准备网页登录/上传路径，等待用户在 GitHub 页面完成登录。DPAPI 本地密钥界面仍需在用户正常 Windows 会话验收。

## 16. 下一阶段最值得做的三个优化

1. **先做线上验收与来源健康基线**：在指定私有仓库跑 Ubuntu smoke、10条真实 dry-run 和一次 Kindle 投递，连续观察一周逐源成功率，修复最重要地区的信息缺口。
2. **积累编辑质量样本**：人工标注重复/更新/误聚类案例，优先改善跨语言事件合并与引文支持判断，再决定是否需要少量 embeddings，而不是先上大型基础设施。
3. **改善恢复与运维体验**：增加可控的来源退避、可读的失败诊断，以及核查后复用已生成合格 EPUB 的补发入口；在实际额度和历史规模下评估长期存储方案。
