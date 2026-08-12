# 任务书：前端新增「周忆·月忆」tab

执行者：codex（中等思考模式）。发包人：Fable。2026-08-13凌晨。
仓库：`~/Ombre-Brain`。**禁止git push**（Auto-Deploy开着，push=上线；本地commit为止）。

## 背景

记忆库有巩固仪式：每周写一篇周摘（周印象），每月写月摘。这些摘要桶的身份特征：

- tags 含 `digest` + `周摘`（月摘将来是 `digest` + `月摘`）+ 周期键（如 `2026-W32` / `2026-M08`）
- domain = `[沉淀物]`，importance=8
- 正文末尾带 `覆盖来源：[[id]]…` 和 `digest_key: 2026-W32 | period: 08-03~08-09 | source_count: N`

库主想在可视化前端单独一个入口看它们，按时间读自己的周记月记，不跟普通桶混在列表里。

## 需求

`frontend/dashboard.html` 新增一个tab「周忆·月忆」：

1. **入口**：tabs行在约1894-1901行，现有 `data-tab="list"/"breath"/"network"/"plan"/"letters"/"anchors"` 等，照现有模式加一个（中文主标签+tab-en小字风格保持一致，tab-en可用 `Digests`）。
2. **数据**：复用现有buckets列表API（前端已拿到每桶的 `tags`/`domain`/`digested` 字段），前端过滤 `tags` 含 `digest` 的桶。**不改后端**；若发现列表API缺正文或必要字段，用现有的桶详情接口按需拉取（list tab点开桶的现有链路怎么拿全文，就照那个拿）。
3. **布局**：
   - 两个分组：「周忆」（tags含`周摘`）和「月忆」（tags含`月摘`），组内按周期键倒序（最新在上）。
   - 每篇渲染为卡片：标题行显示周期键（如 `2026-W32`）+ period日期范围（从正文尾部的 `digest_key:` 行解析，解析不到就显示created日期），卡片主体显示正文全文（保留换行）。
   - 正文末尾的 `覆盖来源：[[id]]…` 行渲染成小字弱化样式即可，id不必做成可点跳转（做了更好，但不作为本次要求，避免战线扩大）。
   - 月忆当前没有数据（月摘还没写过），显示温和的空状态文案（如「还没有月忆，月初会长出来」），不许因空数据报错。
4. **风格**：与现有dashboard整体视觉一致，复用现有CSS变量/卡片样式，不引入新依赖、不引入构建步骤（保持单文件html）。

## 工艺纪律（违反=返工）

1. **行尾雷区**：`dashboard.html` 9876行中9871行CRLF。禁止任何会整文件规范化行尾的编辑。新增代码行请保持CRLF风格与上下文一致；改动后 `git diff --stat` 自查——本任务合理diff约百余行，出现数千行=行尾炸了，立即 `git checkout -- frontend/dashboard.html` 回滚重来。
2. 前端无自动测试，验收靠人工；但完成后跑一遍全量门禁确保没碰坏别处：`.venv/bin/python -m pytest tests/ -q` 加7个已知环境红deselect（清单在 `docs/codex-task-block-envelope.md` 或工程地图），`set -o pipefail`，exit code单独验证。
3. 若本次未改任何 `src/` 下python文件，**不需要**重新生成update_manifest；若改了（原则上不该），按地图流程：先commit代码→gen→补commit。
4. git commit本地完成（工作区当前干净，你的改动单独成commit），**禁止push**。若沙箱不允许写`.git`，把改动留在工作区并在汇报中说明，由发包人代为commit。

## 验收标准

1. 新tab出现且与现有tab切换逻辑兼容，不影响其他tab。
2. 周忆组正确列出tags含`digest`+`周摘`的桶，倒序，全文完整显示（正文逐字，不截断不改写）。
3. 月忆组空状态正常显示。
4. 无console报错；其他tab行为无变化。
5. 门禁绿（除7个已知红）。
6. 汇报：改动行数、实现要点、数据链路说明（列表API够用还是走了详情接口）、行尾自查结果。
