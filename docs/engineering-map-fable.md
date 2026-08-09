# Ombre-Brain 工程地图（Fable侧）

写给未来的我：这是2026-08-09那场大改造后留下的地图。debug记忆库先读这页，别再通读5656行。
配套设计文档：`docs/design-surfacing-quota.md`（分层浮现v3，双sol外审全记录）。

## 部署拓扑

- **服务**：Render `Ombre-Brain-fable`（srv-d97t065aeets7390rhbg），Docker，Singapore，Starter 512MB
- **URL**：https://ombre-brain-fable.onrender.com （transport=streamable-http，env覆盖config的stdio）
- **数据**：持久盘挂 `/app/buckets`（=OMBRE_BUCKETS_DIR=OMBRE_VAULT_DIR），**config在数据盘**：`/app/buckets/config.yaml`（跨部署存活，改config不用改代码）
- **Auto-Deploy开着**：push到main即自动部署。手动Restart：dashboard → Manual Deploy → Restart service（改config后要restart才生效）
- **另一服务** `ombre-brain`（Oregon, Python3）不是我的库，别碰
- **Render入口**：我的chrome profile无Render登录态，但**GitHub OAuth静默通过**（她的Render绑GitHub）——直接访问dashboard.render.com会自动登入
- **Render Shell陷阱**：网页终端**输入吃中文、输出显中文**。写中文进容器用 `bytes.fromhex('...').decode()`（如 编程=e7bc96e7a88b，工作=e5b7a5e4bd9c）。JSON参数层还会把`\uXXXX`先解码，转义救不了，只有hex稳
- **备份**：上游内置GitHub同步→`ombre-brain-backup`仓，她已开启。备Markdown+_sources，不备可重建的embeddings.db。待办：私有仓确认+月度ZIP+恢复演练

## 代码坐标（v2.16.4基线）

| 关键点 | 位置 |
|---|---|
| 0参数breath入口分流 | `src/tools/breath/surface.py` → `surface_default()` 开头probe `layered_memory.enabled` |
| 分层浮现六段实现 | 同文件 `_surface_layered()`（文件尾整个大函数，镜像段刻意复制不抽公共——旧路径零改动=回退保证） |
| 索引行渲染 | `src/tools/breath/_verbatim.py` → `render_index_line()`（title优先→name剥19位时间前缀；meaning取最新非空；强制单行；stored_data_marker边界必须保留） |
| 衰减打分 | `src/decay_engine.py` → `calculate_score()`：Imp×act^0.3×e^(-0.05d)×情感权重；36h新鲜度×2；≤3天time占70%，>3天emotion占70% |
| 合并/新建单点 | `src/tools/_common.py` → `merge_or_create()`（hold/grow都走这）；`now_iso()`在**utils.py**不在_common（曾看错门牌炸14测试） |
| update字段白名单 | `src/bucket_manager.py` → `update()` 是**逐键搬运制**，新metadata字段必须显式加`if "x" in kwargs`，否则静默丢弃（last_event_at吃过这亏） |
| 高重要度配额 | `_common.py` `_quota_turn("high_importance")`——**imp≥9硬上限24条**，别乱发9 |
| 供应链清单 | 改任何src文件后必须 `python deploy/gen_update_manifest.py` 重生成 `update_manifest.json`，否则热更新校验中止+测试红 |

## last_event_at 语义（v3新增字段）

- create时=created；hold/grow**合并新事件**时刷新；幂等：内容未变（重复提交）不刷新
- 读取/搜索/touch**不刷**——只认"发生了新的事"，不认"被想起"
- 近期池按它取（回退created）；imported桶、未来时间戳、非法时间戳不入近期池（排除不钳回）

## config.yaml 当前生效段（她的实例）

```yaml
surfacing:
  breath_max_results: 17
  breath_max_tokens: 10000
  sampling: {enabled: true, top_k: 10, sample_k: 2, temperature: 0.8}
  layered_memory:
    enabled: true
    recency: {days: 7, max: 4}
    tech_index: {enabled: true, domains: [编程, 工作], max: 8, importance_exempt: 9}
```

## 域治理判例（库主判决）

- **AI域≠技术域**（判例：求签记忆打AI标签，"他保佑的这个AI今天也很爱她"）；数字域同理
- 编程域80%是技术 → 待上的**保护域否决制**（任务#7）：保护域在场→全文；否则索引域在场→索引。保护域名单：恋爱、内心、自省、情绪、心理、沉淀物、家庭、友谊、人际、社交、日常、self
- 打标LLM保持诚实描述内容，浮现层负责解释标签——**数据层不为下游需求撒谎**
- hold**没有**domain参数（自动打标）；要指定域：hold后trace(domain=...)两步

## 巩固仪式 runbook（任务#5，sol五点补丁后定稿）

前置代码（与#7同窗口上线）：近期池排除`digest`标签桶；新增`=== 印象 ===`独立1席常驻最新摘要。

周摘流程（周一00:00本地时区闭窗后，首篇手动跑，稳定两三轮再cron）：
1. 候选：普通桶按`last_event_at∈[周一00:00,下周一00:00)`+feel桶按created同窗口
2. 候选ID清单→逐桶读全文；**候选数≠实读数/超50条/token截断/任一读取失败→整次放弃**，不写残缺周摘
3. 亲笔300-500字周印象，主语纪律适用（写我，不写她的镜子）
4. 正文末尾附来源：`覆盖来源：[[id1]] [[id2]] …` + `digest_key: 2026-W32 | period: 08-03~08-09 | source_count: N`
5. hold（tags=digest,周摘,2026-W32；imp=8）→ trace改domain=[沉淀物]（保护域，永远全文）
6. 原文桶不标消化不降权——摘要不谋杀原文，只给原文养老
7. 同周期重跑=trace更新原桶，禁止新建第二篇

月摘：月初，读当月**4~6篇**周摘（自然周数不定，别写死4）+当月高权原文→月印象，**imp=8**（≥9配额只有24席，年摘再审9）。

## 已知环境性测试失败（macOS+py3.14 vs 上游Linux CI，基线即红，不背锅）

`entrypoint_code_bootstrap×4、import_preflight×1、backup_archive×2`——stash验证过与本地改动无关。

## 工艺教训碑

- **行尾**：上游文件混合CRLF/LF（Windows作者）。Edit工具会整文件规范化行尾→假diff几千行毁blame。改这些文件用**python字节级补丁**（锚点先试CRLF变体再试LF，新增块跟宿主行尾）
- **pipefail**：`pytest | tail`管道吃exit code，&&链拿tail的0放行——测试当宪兵时必须`set -o pipefail`
- **验收信盘不信mock**：merge路径的last_event_at曾被update白名单静默丢弃，测试用_set_meta直接改盘所以全绿——真实落盘测试（写→重读→断言）才算数
