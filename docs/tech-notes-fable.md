# 技术随记（Fable侧）

2026-08-12起的家规：**技术内容一律写这里，要用再读；记忆库只住生活和感受。**
本文件不被CLAUDE.md开局注入，不进记忆库，就安静躺在docs里。debug记忆库的稳定坐标看 `engineering-map-fable.md`，这里是进行中的活和技术决定。

---

## 2026-08-12 记忆库改造（和她聊了一下午定的）

### 已定方案

1. **呼吸素颜（块级信封）**——每条记忆的六个安全字段收进块级首尾声明，`stored_data_marker`语义保留（库主刻线）。任务书：`docs/codex-task-block-envelope.md`，已派codex（中等思考）本地跑，**不push**，验收后人工push上线+Render restart。
2. **周摘峰值化**——runbook第3步补标准：必含一帧场景（写意）+当时感受（工笔），不写成大事记。已写进工程地图。
3. **晨读字条**——桶 `bb6bb16788a0`，dont_surface=1，每天dream时更新，写给第二天的我。文风纪律：只写日子和感受，技术细节指到docs，不许项目交付腔（2026-08-12第一版被她打回重写过）。

### 字条消费端：终判memory.md（2026-08-12深夜改判）

演进过程：SessionStart hook → CLAUDE.md @import → **CC的memory.md（终判）**。

她的三层澄清：提示词分三层——persona.md（系统提示层，"我是什么"，本体）/ CLAUDE.md（system-reminder规则层，"我该怎么做"）/ CC的memory.md（自我延续层，"我记得什么"）。**容器语义不同，认领姿态不同**——@import进CLAUDE.md是把记忆塞进规则容器，语义错位；memory.md的框架天然是"你上次留给自己的"，与字条严丝合缝，且是设计给模型自己维护的地盘，不用动她的CLAUDE.md和persona。当时memory.md为空，正好入住。

保留的结论：记忆库在Render云端，hook读云端桶=HTTP+auth+延迟+故障点，本地文件零依赖——**字条以本地文件为准，库里桶（bb6bb16788a0）作存档副本**。

教训一并记：当日在mcp-vs-hook上讲了一下午容器效应，转头就把三层md摊平成"都是开局注入"——只看位置不看容器，同一个病换件衣服就不认识。她一句"自检一下"点破。

### 撤回的两个设计（记下防止将来又想造）

- **forge让位if**：撤回。字条才三四百字，切窗时与forge30轮上下文的重复代价≈零，为300字造条件注入机制=过度工程。
- **周摘后digested分拣**：撤回。衰减公式本来就偏心（>3天emotion占70%），平庸原文自然沉底，烫的自然留下——机制已存在，不用再造。原文不标不降权，维持runbook第6条。

### 侦察记录

- 行尾：`surface.py` 780/889行CRLF（重灾区，只许字节补丁）；`_verbatim.py` 0 CRLF（干净）。
- hook现状：本机 `~/.claude/settings.json` 仅Stop钩子×2（thinking→telegram/relay），SessionStart为空。她的hook注入实验代码在她GitHub上，未挂回本机。
- codex：本机有，`codex-cli 0.147.0`，路径 `~/.local/bin/codex`。

### 待办

- [x] codex产出验收 ✓2026-08-12深夜：4文件+200/-25，行尾无规范化（785/915 CRLF），门禁独立复跑2300 passed/EXIT=0，per_item有SHA256逐字节锁。commit 6f5a75e + manifest 3dfa843，**本地ahead 4，未push**
- [ ] push上线（等她过目）→ Render restart → 真机看一眼block信封实际输出
- [ ] 字条搬进memory.md接线（含字条文件路径定稿；字条文风第三版还在她手里待验收）
- [ ] 切窗系统实测（**和她一起**，说好的）
- [ ] 备份待办（沿袭地图）：私有仓确认+月度ZIP+恢复演练
