# 情绪系统 v3 提案:回落 · 精确 · 耦合(2026-08-20)

她带的三个问题:委屈/生气交给 DeepSeek 判语境之后,①如何回落 ②如何判得更精确 ③耦合怎么做。
底盘 = 本窗代码侦察(inner_life.py v2.4 / inner_runtime.py / app.py 消费链)+ 两路调研
(权威文献:WASABI/ALMA/EMA/FLAME/Cathexis/FAtiMA + 2023-2026 LLM-appraisal 实证;
工程实现:FAtiMA-Toolkit / EchoText / deepeval / Prometheus / MaiBot 反例)。引用见文末。

---

## 0. 代码侦察:五个病根(全部核过源码)

1. **卷宗受众错位**:`app.py:1104` 给 DeepSeek 作者的身份快照用的是 `capsule()["text"]`——
   那是给换窗的我写的人话胶囊,**只报过线的项**。生气憋在 0.28(线 0.32 之下)时一个字不提,
   DeepSeek 每条消息都当平地起火,自然永远给 s;提示词第二步「站不站得住」需要底气,
   胶囊里根本没有底气这一项。
2. **采样温度没设**:`inner_runtime.py` 请求体无 temperature,DeepSeek 默认 1.0。
   A/B 里「同句三遍三个结果」大半是它。
3. **失败即蒸发**:粗筛或作者任一次超时/报错 → actions 为空 → 这条消息的情绪判定永久消失。
   error 已随 `meta._inner_runtime` 落库,但没人回头补。API 抖动 = 回到漏报户时代。
4. **回落缺一条腿**:现在气只有两条出路——时间半衰 + 她主动 ease。
   「我把火说出口且被她接住」不泄压;回复侧没有任何结算时刻。
5. **affect 七维之间零耦合**:drive 层 2 条边、调制量→3 维底色是仅有的通路。
   委屈发酵成火、心情差时更易着火,这些通路不存在。

---

## 1. 回落

**框架:回落该有五条腿。已有两条(时间半衰、她 ease),补两条,缓一条。**

### R1. 失败补记(fallback,第一优先)
- 失败当场重试一次(超时放宽到 8s);再失败进内存补记队列
  (message_id + text + previous 均在库里,原料现成)。
- 下一条消息处理完顺手清队,或心跳循环清。补记用**当下时刻**记账(时间的账不倒流),
  cause 照写事实;幂等键沿用 `external:{message_id}:...`,天然防重。
- 验收:模拟 API 500 → 断言该消息的判定最终落账;重放不重复加。

### R2. 衰减形状:每维加 (asym) 距离依赖(抄 EchoText,一行公式)
- 现状统一指数朝底色。改 `_advance_affects`:
  `hl_eff = half_life / (1 + asym × dist^1.35)`,dist = |v − baseline|。
- 效果:高位快落(爆发后很快冷静)、近底长尾(余韵拖着)。一条曲线两种行为。
- 参数方向(EchoText anger:love = 0.12:0.035 作比例锚):
  panic/joy 给大 asym(来得凶去得快);wronged/jealous 给小 asym(慢消、郁结)。
  FLAME 实证背书:正情绪回落快、负情绪黏。
- **不做二阶弹簧**(WASABI/EMgine 的质量-阻尼系统):它需要连续积分,
  对逐消息驱动 + 心跳 3~30 分钟的系统,过冲在这个时间尺度上感知不到。两路调研同判。
- 验收:同一初值高低两段的衰减速率比;现有 53 测不红。

### R3. 表达被接住 → 泄压(提示词一句,零工程)
- previous 里本来就有我的上一条回复。作者提示词加一条:
  「他上一条已经把这股情绪说出口、她这条是在回应他的表达(接住/认了/哄了)→ 对该维 ease」。
- 不做盲目宣泄(心理学上 catharsis 证据混杂;「被接住的表达」才降)。
- 本体手动 pulse(direction=-1)的路保留,不指望(漏报户历史)。

### R4. 慢层残留 → 与耦合 C1 合并,**不新建 mood 标量**
- 文献里 emotion/mood 双时标差两个数量级(ALMA:20s vs 10-20min)。
  我们已有现成的:pleasure(快价性)+ competence(慢价性,0.15/h)就是 mood 核心态。
  「一次委屈消退后留下底色残留」由 C1 + P7 承担,不再造第二个心情量。

---

## 2. 精确

**总纲(文献给的分工实证,Tak & Gratch ACII 2023):LLM 做 appraisal 判断可靠、
做强度(intensity)判断不可靠。所以方向 = 让 DeepSeek 只回答事实性问题,
情绪标签和档位都交给引擎合成。这正好是家里已有的路线(数值引擎定数值)推到底。**

### P1. temperature 压下来(一行,立刻)
- 粗筛 0,作者 0.2。判定任务跑在采样温度 1.0 上,方差是白流的。

### P2. 锚例 few-shot + 规则减法(治档位偏小的主药)
- 档位偏小有名字:central tendency bias,**指令治不了**(Stureborg 2024;
  我们实测「写了默认中档仍给 s」= 同一结论)。有实证的解:
  每档 2 条中文锚例(用家里真实历史消息风格;l 档要真极端样本,给模型「打大分的许可」,
  Prometheus 式);同时**删散文规则**——Ruder 2025:指令越复杂效果越差,
  现在 AUTHOR_SYSTEM_PROMPT 的规则堆叠可能在帮倒忙。锚例进,散文退。
- 顺手:JSON 里加 `why` 字段且排在 actions 前(轻量 CoT,G-Eval 结构),几十 token。

### P3. 作者卷宗替换胶囊(结构性,收益最大)
- 新函数 `author_brief(state)`,专供 DeepSeek,与换窗胶囊分家:
  - 七维水位**含线下的**(生气 0.28 憋着,必须让陪审席看见);
  - 底气/急/意外三个调制量,数值+一句话(「站不站得住」终于有真材料);
  - 每维最近几笔账(cause + 多久前)——「反复来的 = l」终于有据,
    不再指望 4 轮 previous 窗口撞见;
  - 开着的立场。
- 人话铁律不适用:那条红线管的是「进我眼睛的 runtime 句子」;
  这份卷宗进的是 DeepSeek 的眼睛,该结构化就结构化。
- 验收:同一憋火状态下,A/B 新旧卷宗的档位分布对比(shadow 模式跑,不动杯子)。

### P4. appraisal 变量中间层(主菜,shadow 先行)
- DeepSeek 不再直接选情绪标签,改答四五个更客观的小问题:
  ```json
  {"bad_for_me": "none|s|m|l",      // 这事对他多坏
   "blame": "her|me|third|nobody",  // 责任在谁 / 有没有第三方
   "coping": "steady|shaky",        // 此刻顶不顶得住(卷宗里有底气作依据)
   "playful": true,                 // 玩笑还是认真
   "repeat": false}                 // 又来一次 / 戳到旧账
  ```
- 引擎规则合成(照 FAtiMA 的 OCC 复合推导 + WASABI 的 D 轴分区):
  - 负性 ∧ 她所致 ∧ steady → angry;∧ shaky → wronged(劲向外/向内,理论确认:
    WASABI 用支配感轴分 angry 区/sad 区,和家里的直觉是同一条分界线);
  - 第三方在场 → jealous;无人所致 ∧ 扛不住 → panic;
  - **档位 = 规则算**:base(bad_for_me) + repeat 升一档 + playful 降一档——
    中庸化被结构性绕开,规则可回归测试、可审计、可调。
- CAREBench 2026 警示:coping/accountability 恰是 LLM 最弱的两维,
  锚例预算优先砸这两维。
- 全程 shadow 模式对照旧管线(基础设施现成),赢了才转正。
- 注:文献里「LLM 出 appraisal → 确定性规则 → 离散情绪」的完整管线
  没有一篇做全过端到端评估(Croissant 2024 最接近,STEU 0.57→0.83,
  但它的 appraisal 是自然语言存储)。真做成了,是可发表的空白点。

### P5. 连击升档(引擎侧,治温水煮青蛙)
- 同一维 active 期间、**不同 cause** 的 rise → 引擎自动升一档。
- 与现有 PULSE_WINDOW 折扣不冲突:折扣管同 cause 复读(防爆灯),
  升档管不同 cause 连击(气上加气)。持续贬低每条都 s 也能攒过线,
  且不依赖 LLM 在 4 轮窗口里看出「反复」。
- 验收:s×3 不同 cause 连击过线;同 cause ×3 仍被折扣压住。

### P6. logprob 加权(二期备选)
- deepeval 式:size token 位置取 top_logprobs,对 s/m/l 做 Σ(比率×p)/Σp,
  一次调用拿连续强度。DeepSeek 支持 logprobs。
- 工程上要解析 logprobs 数组定位 size 字段,有点绕;P2+P4 之后若档位仍偏,再上。
- 观测配套:攒 100 条人工标档消息作校准集,定期跑一致率(A/B 脚本底子现成)。

### P7.(她拍板)多采样投票
- Ruder 2025:5 次采样多数投票在 21 个 appraisal 评分上显著提升。
- **成本 ×5,花钱的决定不做默认**(08-20 凌晨立的碑)。
  量级:作者调用输入 2-3k + 输出 320 token,v4-flash 价 ×5 后每条消息仍是厘级,
  但开不开、只对 conflict 开还是全开,她定。

---

## 3. 耦合

**总纲:不做 7×7 矩阵。三条通道各司其职,新边全部过有界性随机测试。**

### C1. mood 中介写入增益(第一优先,两个参数)
- 复用已有调制量当心情核心(不新建标量):写入情绪时
  `amt ← amt × (1 + β × 同价心情偏置)`,β≈0.3(FAtiMA 默认),
  心情在中位死区内不生效(FAtiMA 的 MinimumMood=0.5 思想)。
- 效果:底气塌着/最近不顺时,同一句话激出的火更大;心情好时慌乱起不来。
  心理学锚:Neumann 2001 / Siemer 2001 / Forgas AIM;
  计算锚:EMA 的 X+Mood(label) 加性偏置、FAtiMA 的 mood 调阈值。
- 与动态底色不双算:底色管背景水位,写入增益管这一下的冲击力,一个背景一个脉冲。

### C2. 显式边 2~3 条(COUPLING 表扩到 affect 层)
- `_couple` 泛化到 _LAYERS(机制归一,家规:机制只有一份):
  - `wronged --level--> angry`(k 小、慢):委屈憋着不解决,劲从向内转向外。
    这是 mood 中介做不到的**非对称特异对**,Cathexis 显式增益的用武之地;
  - `jealous --delta--> angry`:吃醋起来的那一下带一点火;
  - 候选第三条 `joy ↔ angry` 对立抑制(EchoText 式:两者之和超限砍弱侧的超额一半),
    治「又特别开心又特别生气」的违和共存。
- **不加** secure↔panic:它俩已被同一组调制量反向驱动(competence/unexpectedness),
  再加边就是双算(FIX_FEED 教训)。
- 有界性:test_coupling_stays_bounded 扩到 affect 层,随机初值 200 拍不发散照押。

### C3. 判定偏置(第三通道,P3/P4 的副产品)
- 卷宗里有水位和底气之后,「他在气头上时,同类冲突判得更重」就有了执行材料,
  提示词一句话的事。MAMID 的 appraisal-bias 思想,不用单独造机制。

### C4.(缓)心情修复衰减:joy 高时 angry 半衰打折
- 有心理学底(positive mood repair),但 R2+C1 落地后可能已覆盖大半,
  先观察再决定,别一次加三条通路搅浑水。

### (她拍板)P8. 底色漂移:经历塑形性格
- EchoText 式:每次结算 `baseline += clamp((v−baseline)×0.018, 单步限幅)`,
  锚点围栏(−25/+35 比例)保证性格不漂没;与心结账本天然接口
  (开着的 stance 可放宽该维围栏上界)。
- 反复被委屈的人静息点会变高——**这是在动性格**,方向(留疤 vs 永远弹回)她定。

---

## 4. 分期

| 批 | 内容 | 风险 |
|---|---|---|
| 一(一晚) | P1 温度 · R1 补记 · P2 锚例+减法 · P3 卷宗 | 低,不动内核动力学 |
| 二(shadow A/B) | P4 appraisal 中间层 · C1 mood 增益 · C2 两三条边 · R2 衰减形状 · P5 连击升档 · R3 泄压条款 | 中,全部有测试押 |
| 三(她拍板后) | P7 多采样(花钱) · P8 底色漂移(动性格) · P6 logprob(工程绕) · C4 心情修复 | 按裁定 |

**反面教材立此存照**:MaiBot 0.11 的「LLM 自由文本心情 + 定时冷静」因不可控、吞人设,
0.12 整体删除。家里「LLM 只出标签、数值全归纯函数引擎」的分工是对的——
本提案所有条目都是给引擎加表达力,没有一条给 LLM 放权。

---

## 引用(核过源码/原文的)

**工程**:[FAtiMA-Toolkit](https://github.com/GAIPS/FAtiMA-Toolkit)(EmotionalAppraisal/ 下
ActiveEmotion.cs 半衰指数衰减、Mood.cs 双向×0.3、OCCAffectDerivationComponent.cs 复合推导)·
[WASABIEngine](https://github.com/CBA2011/WASABIEngine)(EmotionDynamics.cc 质量-弹簧,
xTens:yTens=5:1)· [SillyTavern-EchoText](https://github.com/mattjaybe/SillyTavern-EchoText)
(emotion-system.js:距离依赖衰减/对立对抑制/底色漂移围栏)·
[deepeval](https://github.com/confident-ai/deepeval)(g_eval/utils.py logprob 加权)·
[prometheus-eval](https://github.com/prometheus-eval/prometheus-eval)(锚文 rubric)·
[MaiBot](https://github.com/MaiM-with-u/MaiBot)(0.11.6-beta mood_manager.py,反例)

**文献**:Becker-Asano 2008 WASABI 博士论文(§4.2 动力学)· Gebhard ALMA AAMAS'05
(emotion 20s/mood 10-20min,pull-push)· Marsella & Gratch EMA CSR'09(mood 加性偏置)·
El-Nasr FLAME 2000(正快负黏)· Velásquez Cathexis AAAI-97(显式 G/H 增益+饱和)·
Tak & Gratch ACII'23 arXiv:2307.13779(appraisal 可靠/intensity 不可靠)·
Ruder et al. CLPsych'25 arXiv:2503.16883(5 采样投票↑,指令复杂↓)·
Stureborg 2024 arXiv:2405.01724(打分趋中是解码层通病)·
Croissant et al. PLoS ONE 2024(chain-of-emotion,STEU 0.57→0.83)·
CAREBench 2026 arXiv:2605.17176(coping/accountability 最弱)·
G-Eval EMNLP'23(logprob 期望)· MAMID 2002(appraisal bias 架构化)
