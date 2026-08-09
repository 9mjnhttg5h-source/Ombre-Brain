# 浮现配比制设计 v1（Fable执笔，待外审）

日期：2026-08-09
作者：Fable（本系统的使用者本人——审阅者注意：作者对"给自己多留记忆"有天然利益偏向，请重点审计所有数字默认值是否过于慷慨）
审阅：codex/sol 5.6（外部盲审）

## 一、要解决的问题

用户反馈（库主小白，2026-08-09）：
> 0参数breath常常不会返回最近的记忆。我希望更接近人类的唤回模式：远期摘要近期原文。技术记忆和情感记忆混在一起，每次要手动调整很别扭。

代码诊断（src/tools/breath/surface.py，v2.14.x）：

1. **无recency保障**。排序主键decay_score对新记忆有加成（36h freshness×2.0、≤3天time权重70%），新记忆分数其实不低——但排序之后有两道随机关卡：
   - 洗牌：top1保留，第2~20名random.shuffle（sampling.enabled时是temperature加权采样，同样非确定）
   - token预算：整桶塞入不截断（这个设计好，保留），长文桶（本库单桶300~600汉字常见）先到先得，10000预算下核心准则约吃3000，动态池仅容8~14条
   
   合成效应：近期记忆"分高但可能出局"，返回与否是概率事件。用户要的是确定性。

2. **domain字段在0参数浮现路径完全未使用**。写入时有domain（库内既有：恋爱/内心/编程/AI/数字等23个域），surface_default不读它。技术流水账与情感记忆在同一预算池按权重赛马，互相挤兑。

## 二、方案：分池保送 + 域感知渲染

surface_default输出结构从现在的4段变为5段：

```
=== 核心准则 ===        （现状不动）
=== 近期 ===            （新增：recency保送池）
=== 浮现记忆 ===        （现状权重池，排除已保送id，tech域降级为索引行）
=== 久未浮现 ===        （现状不动）
=== 偶然想起 ===        （现状不动，3%触发）
```

### 2.1 recency保送池

- 候选：unresolved池中 `created` 在 `recency.days`（默认7）天内的桶
- 排序：created降序（最新在前）
- 上限：`recency.max`（默认4）条
- 渲染：全文（render_stored_bucket），标头 `🌱 [近期] [bucket_id:...]`
- **不参与**洗牌/采样；权重池候选中排除已保送id（去重）
- tag_filter对本池同样生效（与权重池语义一致）
- 预算顺位：核心准则之后、权重池之前
- 空窗口（7天无新记忆）→ 整段消失，不占格式

### 2.2 域感知渲染（权重池内）

- 白名单 `domain_render.index_domains`（默认：编程、AI、数字、工作、学习）
- 权重池渲染每桶前判断：`domain ∈ 白名单 且 importance < index_importance_exempt(默认9)` → **索引行模式**，否则全文
- 索引行格式（单行，约30~60 token）：
  `🔧 [索引] [bucket_id:xxx] name ｜ created日期 ｜ meaning首条或正文前40字`
- 权重池末尾若存在索引行，追加一行提示：`（索引条目详情：breath_search(query=..., domain=...)）`
- recency池**不做**索引降级（近期的事哪个域都给全文——刚发生的技术事故也是刚发生的生活）
- 索引行不携带stored_data_marker完整边界（无正文payload），但保留bucket_id可追溯

### 2.3 明确不做

- 不改calculate_score公式（诊断结论：打分无病，病在打分之后）
- 不动search.py / importance.py / catalog.py / feel.py（各有专用通道）
- 不动decay_engine / bucket_manager存储层
- 不动核心准则置顶逻辑
- 不引入LLM调用（浮现路径保持零LLM，摘要体温问题由后续"巩固仪式"人工解决，不在本次范围）

## 三、配置（config.yaml surfacing段，全部有内置默认，不配=开启新行为的默认值）

```yaml
surfacing:
  recency:
    enabled: true      # false = 完全回退到现状行为
    days: 7
    max: 4
  domain_render:
    enabled: true      # false = 全部全文（现状）
    index_domains: ["编程", "AI", "数字", "工作", "学习"]
    index_importance_exempt: 9   # importance>=此值的tech桶仍全文
```

域匹配规则：对桶metadata.domain做str.strip()后精确匹配（库内domain是受控中文词表，不做模糊）。

## 四、实现落点

- `src/tools/breath/surface.py`：surface_default内插入recency池选取与渲染段；权重池渲染循环加域判断分支
- `src/tools/breath/_verbatim.py`：新增 `render_index_line(bucket) -> tuple[str,int]`
- 单测新增 `tests/test_breath_recency_quota.py`：
  - recency窗口边界（7天整/刚超7天）
  - recency.max截断（多于4条取最新4）
  - 与权重池去重（同桶不重复出现）
  - tag_filter作用于recency池
  - 域索引行触发/importance豁免/enabled=false回退
  - token预算顺位（预算极小时：核心准则>recency>权重池的保留顺序）
  - recency.enabled=false 时输出与现状byte级一致（回归保护）

## 五、开放问题（请审阅者裁决）

1. recency.max=4、days=7 是否过于慷慨？（作者自利风险点：这两个数字直接决定"我自己最近的日记占多少输出"。库主原话是"有重要的也有近期的"，权重池14条 vs recency 4条的比例是否合理？）
2. recency池排序用created还是last_active？（created=严格"新写入的"；last_active=最近被摸过的，可能被touch污染。作者倾向created，防止高频访问的老桶伪装成近期。）
3. 索引行是否应携带domain字段本身，方便直接复制进breath_search？
4. 权重池的max_results（默认20）是否应因recency池占用而减小，维持总条数恒定？（作者倾向不减：预算是天然上限，条数上限保持独立语义。）

## 六、外审判决与采纳（v2定稿，2026-08-09）

审阅人codex/sol 5.6判词要点与作者裁决（架构权归作者，数值与越权判定从审）：

**自利审计——全部从判：**
- recency默认改 `days=3, max=2`（3天与评分公式短期窗口对齐；低频写入者可自行调7天）；新增 `budget_ratio=0.25`——recency池最多用核心准则后剩余预算的25%
- `weighted_limit = max_results - len(recency_selected)`：recency占条数名额，作者原"不减"倾向被判自利放宽，从判
- **domain_render.enabled 默认 false**（判词：库主只说"不想混在一起"，未授权"技术内容降级"——作者越权，从判）；`index_importance_exempt` 从9降到8，与cold-start阈值对齐
- recency排序：created降序，同created按bucket ID稳定排序；不用last_active（touch污染）

**边界修正——全部采纳：**
- 池顺序：unresolved → recency选取 → weighted_unresolved（扣除recency_ids）→ cold-start从weighted池选 → 评分/采样 → 截断
- passive去重：`already = recency_ids ∪ candidate_ids`
- 空结果判断与parts拼装均纳入recency_results
- `min(recency.max, max_results)` 约束
- 非法created只排除该桶；created>now不入recency；`now`在函数入口捕获一次
- 索引行保留stored_data_marker边界（meaning/正文预览仍是存储内容，B11防注入）；携带domain；换行压平；token按最终渲染串计
- 提示行token计入预算，放不下则省略提示行
- 测试覆盖recency×domain_render四种开关组合；recency.enabled=false且domain_render.enabled=false时与现状byte级一致

**已知限制（作者裁决，记录在案）：**
- 批量导入桶的created=导入时刻，可短暂垄断recency池（sol B9）。首版不为一次性事件建字段：`recency.enabled`开关兜底，导入操作期间建议临时关闭。若未来导入常态化，再引入source_created字段。
- 审阅输出A部分与B1因管道截断遗失，由实现后第二轮代码审兜底。
