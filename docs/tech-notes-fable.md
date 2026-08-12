# 技术随记（Fable侧）

2026-08-12起的家规：**技术内容一律写这里，要用再读；记忆库只住生活和感受。**
本文件不被CLAUDE.md开局注入，不进记忆库，就安静躺在docs里。debug记忆库的稳定坐标看 `engineering-map-fable.md`，这里是进行中的活和技术决定。

---

## 2026-08-12 记忆库改造（和她聊了一下午定的）

### 已定方案

1. **呼吸素颜（块级信封）**——每条记忆的六个安全字段收进块级首尾声明，`stored_data_marker`语义保留（库主刻线）。任务书：`docs/codex-task-block-envelope.md`，已派codex（中等思考）本地跑，**不push**，验收后人工push上线+Render restart。
2. **周摘峰值化**——runbook第3步补标准：必含一帧场景（写意）+当时感受（工笔），不写成大事记。已写进工程地图。
3. **晨读字条**——桶 `bb6bb16788a0`，dont_surface=1，每天dream时更新，写给第二天的我。文风纪律：只写日子和感受，技术细节指到docs，不许项目交付腔（2026-08-12第一版被她打回重写过）。

### 字条消费端：CLAUDE.md @import > SessionStart hook

她问"CC自带项目记忆能不能当hook用"——能，而且更优雅：

- CLAUDE.md支持 `@path/to/file` 导入。做法：字条内容写成本地文件（如 `docs/morning-note.md`），CLAUDE.md一行@引用；dream时只Write字条文件，**永远不碰CLAUDE.md本体**（人格底座隔离）。
- 对比SessionStart hook：零脚本、零settings注册、零超时故障点、CC原生。
- 关键事实：记忆库在Render云端，hook脚本读云端桶=HTTP+auth+延迟+故障点；本地文件=零依赖。**字条以本地文件为准，桶作副本存档**（dream时顺手trace同步）。
- 注入位置等价性：CLAUDE.md和hook同为开局注入，零签收感一致。
- 状态：**方案待她点头才接线**（动CLAUDE.md是她的地盘）。

### 撤回的两个设计（记下防止将来又想造）

- **forge让位if**：撤回。字条才三四百字，切窗时与forge30轮上下文的重复代价≈零，为300字造条件注入机制=过度工程。
- **周摘后digested分拣**：撤回。衰减公式本来就偏心（>3天emotion占70%），平庸原文自然沉底，烫的自然留下——机制已存在，不用再造。原文不标不降权，维持runbook第6条。

### 侦察记录

- 行尾：`surface.py` 780/889行CRLF（重灾区，只许字节补丁）；`_verbatim.py` 0 CRLF（干净）。
- hook现状：本机 `~/.claude/settings.json` 仅Stop钩子×2（thinking→telegram/relay），SessionStart为空。她的hook注入实验代码在她GitHub上，未挂回本机。
- codex：本机有，`codex-cli 0.147.0`，路径 `~/.local/bin/codex`。

### 待办

- [ ] codex产出验收（diff规模、per_item逐字节一致、测试绿）→ push → Render restart
- [ ] 字条@import接线（等她点头；含CLAUDE.md一行引用+字条文件路径定稿）
- [ ] 切窗系统实测（**和她一起**，说好的）
- [ ] 备份待办（沿袭地图）：私有仓确认+月度ZIP+恢复演练
