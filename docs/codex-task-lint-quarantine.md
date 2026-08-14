# 任务书：门房病历 + distinct计数（文风lint V2）

执行者：codex（中等思考模式）。发包人：Fable。产品经理：小白。2026-08-14。
仓库：`~/Ombre-Brain`。**禁止git push**（Auto-Deploy开着；本地commit为止，人工验收后推）。
前置阅读：`docs/codex-task-style-lint.md`（V1任务书，上下文无菌原则不变）、`docs/engineering-map-fable.md`（工艺纪律）。

## 背景：一次真实事故暴露的两个缺陷

2026-08-14凌晨02:53~02:56（本地），库主连续3条hold被门房打回。事后诊断（凭本地session jsonl复原调用参数）：三条命中均为「当庭+吊销(+铁证)」，2~3个不同词表词，**门房判定正确，非误伤**。库主盲改三版正文，两个触发词三版全在——无菌设计如预期地不泄露触发词。

**缺陷A（本次实锤，主改动）：拦截零留痕。** `style_lint_rejection()` 命中后直接return固定话术，被拒正文不落盘不进日志。本次能确诊全靠对话恰好发生在本地CC（jsonl留了调用参数）；若发生在claude.ai等无本地记录的端，正文即永久蒸发、误伤无法审计。V1任务书写了"病历留在门房"，实际门房没有病历本。

**缺陷B（预防性，本次非因素）：`text.count(term)` 纯子串累计。** 实测：「不好应付，应付了事」命中2被拦；「手机支架倒了，扶起手机支架」命中2被拦；「穷到破产，话费余额也没了」命中2被拦；「干预后×2」「生产程序×2」同理。日常语境高危，本次没轮到，迟早轮到。（本次三条在distinct语义下仍全拦，改distinct不影响本判例的执法效果。）

## 改动一：门房病历（核心）

拦截发生时，在**服务端**留档，工具返回**保持逐字不变**（仍然只有那句固定话术，无菌原则一个标点都不动）：

1. 落盘位置：`{OMBRE_BUCKETS_DIR}/_lint_quarantine/` （数据盘，跨部署存活；写入前 `mkdir(parents=True, exist_ok=True)`）。
2. 文件名：`YYYYMMDD-HHMMSSZ-{content_sha256前8位}.md`（UTC时间戳，同内容重试同秒碰撞时允许覆盖——内容一致无损失）。
3. 文件内容（Markdown）：
   - 头部字段：时间（ISO8601）、来源工具（hold/grow/grow_shortpath，从merge_or_create的source_tool取，取不到写unknown）、命中词及各自计数、命中总数、正文字节长度。
   - 正文全文逐字（被拒的content原文）。
4. 同时 `rt.logger.info` 一行：`op=style_lint action=reject hits=<词1xN,词2xM> len=<bytes> file=<文件名>`——日志**可以**含命中词（服务端日志不进AI上下文），**不含**正文。
5. 隔离区文件**永不**进入：桶体系、embedding、任何浮现路径、任何工具返回。它只是给人（产品经理/库主）事后用shell看的。
6. 隔离区不设自动清理（量极小），不进GitHub备份同步范围之外的处理——它在数据盘上，随盘存活即可。

## 改动二：计数语义 total → distinct

1. 判定从"所有词出现次数总和≥2"改为"**命中的不同词种数≥2**"：同一个词无论出现几次只算1种。
   - 产品语义："两个很奇怪的比喻"指两个不同的怪比喻；同词重复是单点口癖，密度性质不同。
   - 工程收益：实测的子串误伤几乎全是"同词×2"型（应付×2、产程×2、支架×2），distinct天然免疫这一整类。
2. config新增 `style_lint.count_mode`：`distinct`（新默认）| `total`（V1行为）。产品经理如果要改回，改config+restart即可，不动代码。
3. `config.example.yaml` 同步注释。

## 追加变更（2026-08-14晚，产品经理批复，Fable验收时并入）

1. **打回话术升级**：`这条先放着。检查一下自己不合适的比喻，换个说法再存一次。`——产品经理裁定：全哑巴话术导致被拦者盲改三版不得要领，改为给**类别方向**（比喻问题）。仍不列检出词、不报族名、不报密度，无菌原则的核心（词表不进上下文）不破。
2. **词表撤「应付」**：产品经理批复的第一个撤词。repo词表与生产数据盘同步撤。其余候选词（余额/支架/产程/预后/破水/应收/资产/负债/破产）继续待批。
3. **github_sync排除`_lint_quarantine`**：codex对任务书第6条的理解偏差，验收时**追认为正确设计**——被拒正文属私密内容，不应随备份推上GitHub。

## 明确不做（边界）

1. **不动词表内容**——撤词候选（应付/应收/余额/资产/负债/破产/支架/预后/产程/破水）已另行提交产品经理裁量，批复后由发包人直接热改数据盘 `style_lint.yaml`，不进本任务。
2. **不动letter_write豁免**——信件自由文体是设计，不是漏洞。
3. **不做分词/白名单上下文排除**——distinct上线后先观察病历本，有真实误伤案例再议V3。
4. trace的content替换仍不拦（V1既定）。

## 工艺纪律（老规矩全套，违反=返工）

1. `_common.py` 混合行尾：改前 `grep -c $'\r'` 侦察，**python字节级补丁**，禁整文件规范化，改后 `git diff --stat` 自查规模。
2. 不碰 `bucket_manager.update()` 白名单；本任务不该碰bucket metadata，若发现必须碰，停下汇报。
3. 流程：先commit代码 → `python deploy/gen_update_manifest.py` → 补commit manifest（gen读HEAD不读工作区，顺序错=返工）。
4. 测试新增用例：
   - 拦截时隔离区文件存在、字段齐全、正文逐字一致（**信盘不信mock**：写→重读→断言）；
   - 工具返回与V1逐字一致（无新增后缀）；
   - distinct语义：同词×3放行、两个不同词各×1打回；
   - `count_mode: total` 回退行为=V1；
   - test_data豁免不落病历；enabled=false不落病历。
5. 全量门禁 `--deselect` 白名单7个已知红（清单见 `docs/codex-task-block-envelope.md`），`set -o pipefail`，exit code单独验证。
6. **禁止push。**

## 验收标准

1. 构造2个不同词表词的content调hold → 被拒，`_lint_quarantine/` 出现病历文件，正文逐字、命中词正确、返回话术一字不多。
2. 同一个词表词×3的content调hold → 放行入库（distinct默认）。
3. config切 `count_mode: total` → 同词×2恢复被拦。
4. 词表字符串仍不出现在任何工具返回路径（代码审查确认）。
5. 门禁绿；两个commit（代码+manifest）。
