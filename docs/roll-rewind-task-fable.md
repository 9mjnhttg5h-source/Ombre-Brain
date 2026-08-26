# Roll 落到 transcript 层任务书：回退 = 剪链 + 原地重启

2026-08-21 夜，她和 fable（工作窗）定的。执行窗（opus）照这份做；拿不准回这份找，找不到再问她。
仓：`~/companion-relay`（后端 `app.py` + pytest）、`~/fairy-tale`（前端 `app.js` / `sw.js`）、新建 `~/fable/tools/`（Mac 侧守护三件）。
技术随记规矩不变：做完在 `~/Ombre-Brain/docs/tech-notes-fable.md` 追加一节，本文件只写计划。

> **⚠️ 执行窗的红线（先读）**
> 1. **不许读任何真实 transcript 的内容**（`~/.claude/projects/-Users-wangshuyi-fable/*.jsonl`、`~/ombre-backups/fable-window-rescue-20260821/*`）。今晚工作窗读了一段就被路由了。要核对结构只看 `type / uuid 前 8 位 / parentUuid / requestId / stop_reason / usage / message_id`，用脚本抽字段，不 cat、不 print 正文。本任务书里所有结构事实已经抽好，够用。
> 2. **不碰活着的 fable 会话**（`claude --resume bf389922…`，Terminal.app ttys000，PID 会变，认命令行不认 PID）。不往它发消息、不 kill、不动它的 jsonl。最后"切到守护脚本"那一步由她自己在安静时刻做。
> 3. 测试一律用**合成 jsonl + 本地起的 relay（临时库）+ scratch session**，不连线上 relay 的库、不用她的真消息。
> 4. 写任何日志/toast/返回值时，**只写 id 和行号，不写消息正文**（安全层对正文敏感，对数字不敏感）。

---

## 0. 为什么改（结构事实，今晚从 ORIGINAL/REPAIRED 抽的，无正文）

### 0.1 层级

```
手机 PWA ──▶ relay SQLite ──▶ companion-channel 插件(SSE, ?since=游标) ──▶ CC 进程内存 ══▶ API
                 ▲                                                          ║
            Roll 只撤到这层                                          transcript jsonl 只是内存往外写的日志
```

- `/app/roll_back`（app.py:2302）把那条人话及其后同窗所有行打 `app_hidden + rolled_back`；`inbound_history`（app.py:371）过滤 `rolled_back` → **管 relay 以后还投不投**。
- CC 进程把对话攥在**内存**里。改库、改 jsonl 文件，都动不了内存那份。所以她今晚的手术（杀进程 → 剪 jsonl → `--resume`）是**唯一能到位的路**，没有更轻的。
- 终端 esc 双击回退：频道消息进来是 `isMeta: true` 的 user 行，回退菜单多半不列它（未从源码核实）；但她在手机上根本按不到 esc，这条不依赖。全文件 0 个分叉（没有任何行的 parentUuid 指向非前一行）= 从没回退成功过。

### 0.2 今晚死链（bf389922，2026-08-21 22:34–23:03 CST，只列结构）

| 行 | 类型 | 事实 |
|---|---|---|
| 373 | user | 她的频道消息 **5964** |
| 374–375 | assistant ×2（同 requestId `…KeZL5odb`） | thinking + tool_use(reply) **半截**，`stop_reason: "refusal"`，`output_tokens: 542`（`thinking_tokens: 245`）——**输出侧被掐，半截已落盘** |
| 376 | system `model_refusal_no_fallback` | |
| 377 | assistant `isApiErrorMessage: true` | "Fable 5's safeguards flagged this message…"，`output_tokens: 0`，parent 指 376 |
| 378 | user tool_result | **parent 指 375（那条半截 tool_use）**——残句正式进链 |
| 380–381 | system + API Error（新 requestId） | 续投立刻又被掐，0 token |
| 385–387 | 她的 5969 → assistant 成功一轮（570 token）→ 工具结果后续投又被掐 | 说明毒不是"输入侧必死"，是**链在累积** |
| 400–433 | 5974…5979 | 7 个 requestId **全部 0 token 输入侧拒**（含她发的"狠狠roll"两条——Roll 撤了 relay，链没动） |

她的手术：剪 ORIGINAL 第 371 行（5964 的 `queue-operation enqueue`）到 EOF 共 59 行 → `--resume` 同 id → 活。**REPAIRED 是现在 LIVE 文件的严格前缀**（375 行 + 新写 39 行），证明：①剪尾巴不破链；②resume 不挑剪口处的 `last-prompt/ai-title/mode/permission-mode/atis-latch` 这几行无 uuid 元数据。

### 0.3 CC 侧可依赖的事实

- 版本 2.1.238（`/opt/homebrew/bin/claude` → 原生二进制 `bin/claude.exe`）。
- 二进制里有 `process.on("SIGTERM", () => process.exit())`：**SIGTERM 是正常退出路径**（联调里要实测一次，见 §5.3）。
- 插件（`~/companion-channel/server.ts`）游标 `~/.claude/channels/companion/profiles/fable/last_in_id`（现 6019）**只在投递成功后前进**；重连带 `?since=游标`，relay 按 `inbound_history` 回放（已过滤 `rolled_back`）。→ 重启后，被 roll 的不会回来，她 roll 之后新发的会补投。**游标文件不用动。**
- 插件从 `~/.claude/channels/companion/.env` 读 `RELAY_URL / RELAY_SECRET / RELAY_BODY(=mac)`，profile 由 `CLAUDE_PROJECT_DIR` 的 basename 推出（`fable`）。守护三件复用同一个 .env。
- 她现在起 fable 的完整命令（一字不改）：
  ```
  cd ~/fable && claude --resume bf389922-96a9-4691-aef5-25d44e43eb38 --model claude-fable-5 --effort high --system-prompt-file /Users/wangshuyi/fable/persona.md --dangerously-load-development-channels server:companion --tools Bash,Read,Edit,Write
  ```
  Terminal.app 普通 tab，**没有 tmux**。

### 0.4 她拍的三条

1. **上守护脚本**：fable 以后通过 `fable-up` 起（命令外套一层循环）。活窗她找安静时刻自己 /exit 再用脚本起一次。
2. **只手动 Roll，不自动捞**：守护脚本不得因为看到 refusal 就自己回退。
3. **触发 safeguard 时直接弹条消息到前端**：「Fable 5's safeguards flagged this message」——只报不动，带个「回退这句」快捷键，按不按是她。

---

## 1. 总流程

```
她按 Roll (PWA)
  → relay /app/roll_back：打标(已有) + 新增 rewind_requests 一条 {body, target_id} + 响应/广播带 rewind
  → Mac 守护 poller 轮询 GET /app/rewind/pending?body=mac (2s)
  → 写 request.json → POST state=restarting → SIGTERM 那个 claude
  → claude 退出，fable-up 循环看到 request.json → rewind_apply.py：
        备份 → 定位剪点 → 剪 → POST state=applied|noop|failed (detail 只有数字)
  → fable-up 原地 claude --resume 同 SID
  → 插件重连 /channel/in?body=mac → relay 把该 body 的 restarting/applied 请求置 done + 广播
  → PWA 状态条「捞人中…」→「接好了」；她发她改好的话，relay 按游标补投
```

请求状态机：`pending → restarting → applied → done`；旁路：`noop`（transcript 里没这条，relay 直接视为 done）、`failed`（剪不了：备份失败/定位异常，**不剪、不删**，原样重启）；前端 90 s 没到 done 自己显示「那边没应答」（relay 不判 stale）。

同一 body 多次 Roll：pending 端点只返回 **target_id 最小**的；`state` 更新作用于该 body 所有未完成请求（当作一个 epoch）。重启过程中又 Roll 了 → 新 pending，重启后的新 poller 再来一次。

---

## 2. relay（`~/companion-relay/app.py`）

### 2.1 表

```sql
CREATE TABLE IF NOT EXISTS rewind_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  body TEXT NOT NULL,            -- 'mac' | 'vps'
  target_id INTEGER NOT NULL,    -- 被 roll 的那条人话 (messages.id)，剪点
  ids TEXT NOT NULL,             -- roll_back 撤掉的全部 id，json
  state TEXT NOT NULL,           -- pending|restarting|applied|noop|failed|done
  detail TEXT,                   -- 只放数字/短码，如 "cut_rows=59 backup=1"
  created_ts TEXT NOT NULL,
  updated_ts TEXT NOT NULL
);
```
放在 `init_db` 那一串 `CREATE TABLE IF NOT EXISTS`（app.py:163–260 区域）后面。

### 2.2 `/app/roll_back` 挂请求

现有逻辑不动，在 `conn.commit()` 之后：
- `win = _pwa_window(...)` 已算出；`win in ("mac","vps")` 才挂请求，`api` 窗不挂（那是 loop 桥，无 transcript）。
- `target_id = src_id`（不是 rolled 里最小的——rolled 的最小就是 src_id，同义）。
- 响应加 `"rewind": {"id": req_id, "state": "pending", "body": win}`，没挂时 `"rewind": null`。
- 广播 `{type:"roll_back", ids, target}` 不改；另发一条 `{type:"rewind", body, req_id, state:"pending"}`。

### 2.3 `GET /app/rewind/pending?body=mac`（auth）

返回该 body 状态为 `pending` 的请求里 **target_id 最小**的一条：`{"id", "body", "target_id", "ids", "state"}`；没有 → `{"id": null}`。2 s 一次的轮询，查询要带索引思维（表小，`ORDER BY target_id LIMIT 1` 够了）。

### 2.4 `POST /app/rewind/state {id, state, detail}`（auth）

- 合法转移：`pending→restarting`，`restarting→applied|noop|failed`；其他 400。
- 作用于**同 body 所有**未到 done 的请求（epoch 语义）。
- 写 `updated_ts`，广播 `{type:"rewind", body, req_id, state, detail}`。
- `noop` 直接再转 `done`（no transcript to cut, nothing to wait for）。

### 2.5 插件上线 → done

`channel_in`（app.py:1933）在 `role == "cli"` 分支、算完 `body` 之后：该 body 有 `restarting|applied|failed` 的请求 → 全部置 `done` + 广播 `{type:"rewind", body, state:"done"}`。**`failed` 也置 done**（会话已经重启，前端的"捞人中"得收口；detail 里留 failed 的码，前端文案区分"接好了"和"没剪成但重启了"）。

### 2.6 `POST /app/safeguard`（auth）——她的第三条

守护脚本看到 refusal 报一笔：`{body, side: "output"|"input", source_id: int|null, request_id, ts}`。
- 落一条 **out** 行：`save_message("out", "notice", "Fable 5's safeguards flagged this message", meta)`，`meta = {"body": body, "via": "watch", "safeguard": {"side", "source_id", "request_id"}}`。`_pwa_window("out","notice",meta)` 靠 `meta.body` 归到 mac/vps 窗（app.py:2288 现有逻辑已覆盖，核一眼）。
- 按 `request_id` 去重（进程内 set + 查最近 50 条 notice 的 meta）。
- 广播该行（走现有 out 行广播路径）+ `broadcast(app_subs, {"type":"typing","active":False,"target":...})` 把转圈收掉。
- **不投递任何脑子、不打任何标、不触发 roll。**

### 2.7 测试（新建 `test_rewind.py`，照 `test_roll_back.py` 的 `_boot` 起法）

1. roll_back 在 vps 窗挂请求、api 窗不挂；响应 `rewind` 形状。
2. 同 body 两次 roll（后一次更早）→ pending 返回更早的 target_id。
3. state 流转合法/非法；`applied` 后 `channel_in` 订阅（TestClient 开 SSE 后立刻断）→ 全部 done。
4. `noop` 自动 done。
5. safeguard：落行归对窗、去重、不进 `inbound_history`（direction=out 天然不进，断言一下）。
6. 全套 `pytest --ignore=forge` 保持绿（上次 73 项）。

---

## 3. Mac 侧守护三件（新建 `~/fable/tools/`，可执行位，`~/bin/fable-up` 做软链）

状态目录：`~/.claude/channels/companion/profiles/fable/rewind/`（`current_sid`、`request.json`、`poller.log`、`apply.log`）。备份目录：`~/ombre-backups/rewind/`。

### 3.1 `fable-up`（zsh）

```zsh
#!/bin/zsh
# fable-up [SID|new]   守护 fable 会话：被 Roll 就剪链原地重启；她自己 /exit 就正常退出
set -u
STATE=~/.claude/channels/companion/profiles/fable/rewind; mkdir -p $STATE
PROJ=~/fable; TDIR=~/.claude/projects/-Users-wangshuyi-fable
case "${1:-}" in
  new) SID=$(uuidgen | tr A-Z a-z); FIRST=1 ;;
  "")  SID=$(cat $STATE/current_sid 2>/dev/null || echo bf389922-96a9-4691-aef5-25d44e43eb38); FIRST=0 ;;
  *)   SID=$1; FIRST=0 ;;
esac
echo $SID > $STATE/current_sid
cd $PROJ || exit 1
while :; do
  rm -f $STATE/request.json
  python3 $PROJ/tools/rewind_poller.py --sid $SID --body mac --wrapper-pid $$ >> $STATE/poller.log 2>&1 &
  POLLER=$!
  if (( FIRST )); then
    claude --session-id $SID --model claude-fable-5 --effort high --system-prompt-file /Users/wangshuyi/fable/persona.md --dangerously-load-development-channels server:companion --tools Bash,Read,Edit,Write
    FIRST=0
  else
    claude --resume $SID --model claude-fable-5 --effort high --system-prompt-file /Users/wangshuyi/fable/persona.md --dangerously-load-development-channels server:companion --tools Bash,Read,Edit,Write
  fi
  kill $POLLER 2>/dev/null; wait $POLLER 2>/dev/null
  stty sane 2>/dev/null                       # 万一 TUI 没把终端还回来
  [[ -f $STATE/request.json ]] || break       # 没有回退请求 = 她自己退的
  python3 $PROJ/tools/rewind_apply.py --sid $SID --transcript $TDIR/$SID.jsonl --request $STATE/request.json >> $STATE/apply.log 2>&1
  sleep 1
done
```
- 参数一字不改；`--session-id <uuid>` 新起那支只在 `new` 时用（2.1.238 的 `--help` 已核：有 `--session-id`、`--resume`、`--fork-session`）。
- 真实 claude 退出码不用于判断（她 /exit 和被 SIGTERM 都可能 0）；**判据只有 `request.json` 存不存在**。
- poller 日志不能进终端（会搅 TUI），全部重定向。

### 3.2 `rewind_poller.py`

- 读 `~/.claude/channels/companion/.env`（与 server.ts 同一套 KEY=VALUE 解析，真实环境变量优先）。
- 每 2 s：`GET {RELAY_URL}/app/rewind/pending?body={body}`（Bearer）。网络错就记日志继续（断网不影响会话）。
- 拿到请求：
  1. 原子写 `request.json`（先写 `.tmp` 再 rename）：`{req_id, target_id, ids, ts}`；
  2. `POST /app/rewind/state {id, state:"restarting"}`；
  3. 找 claude：`pgrep -P {wrapper_pid} -f -- "--resume {sid}|--session-id {sid}"`，只取一个；找不到 → 记日志、`state=failed detail=no_proc`、删 request.json、继续轮询（不能让 fable-up 误剪）；
  4. `SIGTERM`；10 s 没退 → `SIGKILL`（记 detail=killed）；
  5. 退出（fable-up 接手）。
- **safeguard 观察（她的第三条，只报不动）**：同一进程里每 2 s 看 transcript 文件增量（记 offset，只解析新增行）：
  - 触发：`type=="assistant"` 且 `message.stop_reason=="refusal"`，按 `requestId` 去重；
  - side：同 requestId 的任一 assistant 行 `usage.output_tokens > 0` 或带 `thinking/text/tool_use` 块 → `output`，否则 `input`；
  - source_id：从该行往前找最近的 `type=="user"` 且非 tool_result 的行，正文里正则 `source="companion"[^>]*message_id="(\d+)"` 抽数字；终端里敲的没有 → `null`；
  - `POST /app/safeguard {body, side, source_id, request_id, ts}`；
  - **解析正文只为了抽 message_id，抽完即弃，任何日志不得出现正文。**
  - 启动时把 offset 设到文件尾（只看之后的）。

### 3.3 `rewind_apply.py`

输入 `--sid --transcript --request [--dry-run]`，输出/日志只有数字和短码。

1. 校验：transcript 存在、request.json 可解析、`sid` 与文件名一致；任一不成立 → `state=failed detail=<码>`，**不动文件**，退出 0（让 fable-up 照常重启）。
2. **备份**：`cp` 到 `~/ombre-backups/rewind/{sid}.{YYYYmmdd-HHMMSS}.jsonl`，校验字节数相等；失败 → failed，不剪。
3. 逐行读；末尾若有半行（JSON 解析失败且是最后一行）→ 丢弃该半行（进程被杀时可能写一半），其余任一行解析失败 → failed。
4. **定位剪点 U**：第一行满足 `type=="user"` 且正文（`message.content` 为 str 或 list 里 text 块）匹配 `source="companion"[^>]*message_id="{target_id}"`。
   - 找不到 → `state=noop detail=not_in_transcript`（她 roll 的那条从没进过这窗，或已在更早一次手术里剪掉）→ 不写文件。
   - 找到 → 保留 `rows[:U]`，再从保留段里**剔除** `type=="queue-operation"` 且 `content` 里带同一个 `message_id="{target_id}"` 的行（enqueue/dequeue 元数据，防 resume 时被当成还在队列里）。**不要从 enqueue 行起剪**：她发消息时我若正忙，enqueue 行会远早于 user 行，中间是上一轮的正经行。
   - 也剔除保留段里带 `ids` 中任一 id 的 queue-operation 行（roll 时还排着队没进 user 行的那些）。
5. 原子写：写 `.tmp` → `os.replace`。写完重新逐行解析一遍校验。
6. `state=applied detail="cut_rows={n} kept={m} backup=1"`。另：扫一眼保留段里是否还有 `stop_reason=="refusal"` 的 assistant 行，有则 detail 追加 `earlier_refusal_at_row={k}`（前端据此提示"更早处还有一刀，可能要再往前 roll"——**提示，不动手**）。
7. `--dry-run`：只打印 U、将剔除的行号列表、将保留行数；不备份不写。

### 3.4 单测（`~/fable/tools/test_rewind_apply.py`，合成 jsonl，pytest 直接跑）

- 造 30 行左右的假 transcript：`queue-operation(enqueue/dequeue)`、`user`（带假 `<channel source="companion" … message_id="N">` 信封，正文用 "hello N" 之类无意义字）、`assistant`（含一行 `stop_reason:"refusal"`）、`system`、`attachment`、无 uuid 的 `last-prompt/mode` 行。
- 用例：①剪点在 user 行而非 enqueue 行（enqueue 和 user 行之间夹别的行，断言夹着的行保留）；②同 id 的 queue-operation 行被剔除；③`ids` 里还在排队的 id 的 enqueue 行被剔除；④找不到 → noop 不写；⑤末尾半行被丢；⑥备份字节数相等；⑦dry-run 不产生任何写；⑧`earlier_refusal_at_row` 检测；⑨sid 不匹配 → failed 不写。
- **撤回抽验**至少做 ①②④：把对应逻辑撤掉要变红。

---

## 4. 前端（`~/fairy-tale/app.js`、`sw.js`）

动手前先 `scp -i ~/.ssh/vps_fox root@4amfox.com:/var/www/companion-web/{app.js,sw.js,index.html} ./线上对比/` 比 md5——本地若落后以线上为准（08-16 吃过这亏）。

1. `doReroll()`（app.js:3524）：响应里 `data.rewind` 非空 → 调 `showRewindChip(data.rewind.body, "pending")`，toast 改「已回退，正在捞那边的会话…」；为空（api 窗）维持原 toast。
2. SSE 处理（app.js:3343 附近）新增 `m.type === "rewind"`：按 `state` 更新状态条：`pending/restarting`「捞人中…」、`applied`「剪好了，重启中…」、`done`「接好了，可以发了」（3 s 后收起）、`failed→done`「重启了但没剪成，再 roll 一次或喊我」、`noop`「那边没收到过这句，不用重启」。`detail` 含 `earlier_refusal_at_row` → 多一行「更早处还有一刀，可能要再往前 roll」。90 s 没等到 `done` → 「那边没应答：fable-up 在跑吗？」。状态条只在对应 tab（mac/vps）显示。
3. `notice` kind 渲染：`from==="ai"` 且 `kind==="notice"` → 居中一条 muted 系统行（像 ctx 那种），文案就是 text；`meta.safeguard.side` 标「输出侧/输入侧」；`meta.safeguard.source_id` 非空时带一个小按钮「回退这句」→ 走 `doReroll` 同一条路（抽出 `rollBackById(id)`，长按菜单和按钮共用）。terminal 视图（`terminalMessageHtml`）也给一行 `term-muted`。收到 notice 顺手 `hideTyping()`。
4. 历史加载/缓存对 `notice` 的兼容：`CACHE_KEEP` 等不改；`notice` 不参与「未读计数」之类的人话统计（核一下 `noteOtherWindowMessage` 等处是否按 kind 过滤）。
5. `sw.js` `CACHE` → `companion-v50-roll-rewind`。

---

## 5. 测试与联调

### 5.1 单测
- relay：`cd ~/companion-relay && pytest --ignore=forge -q`，新文件 `test_rewind.py` 全绿，原 73 项不掉。
- apply：`cd ~/fable/tools && pytest -q test_rewind_apply.py`。

### 5.2 本机全链路（不碰线上）
- 本机起 relay：临时库（`RELAY_DB=/tmp-scratch/relay.db`，用 scratchpad 目录）+ 上次那套反代 `serve.py`（scratchpad，SSE 逐字节转发）+ 浏览器开本地前端。
- poller 用 `RELAY_URL` 环境变量覆盖指到本机 relay（真实环境变量优先于 .env，不改 .env）。
- scratch session：**不挂 companion 频道**（挂了会和活窗一起收她手机的消息，造重复）。用 `fable-up` 的一个测试开关（如 `FABLE_UP_SCRATCH=1` 时去掉 `--dangerously-load-development-channels server:companion`、`--system-prompt-file`，模型换 `claude-haiku-4-5-20251001`，cwd 换 scratchpad 下的假项目目录，transcript 目录随之变）。在 Terminal 新 tab 里跑，随便聊两句让它写几行。
- 往本机 relay 的库里 `save_message` 几条 `routed=desktop-mac` 的假人话（正文 "t1/t2/t3"），手工往 scratch transcript 里塞对应 `message_id` 的假 user 行（合成，不经真频道）。
- 浏览器按 Roll → 观察：relay 请求 pending → poller 日志 restarting → scratch claude 退出 → apply 日志 applied + 备份文件出现 → claude 自动 resume → （scratch 没频道，`done` 用 curl 手工模拟 `channel_in` 订阅或直接调内部函数）→ 前端状态条走完。
- **SIGTERM 实测**（§0.3 那条的验证）：scratch claude 被 SIGTERM 后：①进程退出；②终端可用（不用 `stty sane` 也行最好）；③transcript 末行是完整 JSON。三项都要记进 tech-notes。

### 5.3 线上切换（她来做，执行窗只准备命令和看日志）
1. relay 部署（§6）。
2. 前端部署（§6）。
3. 她在安静时刻对活窗 `/exit`，新 tab `fable-up`（无参数 = 续 `bf389922`）。看 relay 日志 `stream connected`、手机发一句"在吗"收到回。
4. 她挑一句无关紧要的话按一次 Roll，走完「捞人中→接好了」。apply.log 里 `cut_rows` 应为那一轮的行数（个位数到十几）。
5. 备份目录里多一个文件，字节数 = 剪前大小。

---

## 6. 部署纪律（沿 tech-notes 08-16/08-19/08-20）

- relay：Mac 工作树 = 线上版但 git 滞后，**信 md5 不信 git**。commit 前 `cp app.py app.py.bak-20260821-prerewind`。`~/companion-relay` 的 `branch.main.remote=vps` 坑：**显式 `git pull origin main` / `git push origin main`**。VPS 上 `git pull origin main` + restart 由她 `!` 执行；重启后验收**轮询 `systemctl is-active` + `/healthz`**，别 `sleep 3` 就 curl。
- 前端：先 scp 线上版对比；改完 **scp 单文件**不 rsync；线上先备到 `/root/companion-web-attic-20260821/`；sw bump 必做。
- Mac 守护三件不进 relay 仓；放 `~/fable/tools/`，**只 cp 不 mv**她现有的任何文件。
- 她 `!` 跑的每一行，先把命令完整备好再请她跑（08-19 教训：别做到最后一步才发现推不动）。
- 完成后在 `tech-notes-fable.md` 追加「2026-08-21 夜：Roll 落到 transcript（执行窗记录）」：含 SIGTERM 三项实测、首次线上 Roll 的 cut_rows、碰到的坑。

---

## 7. 明确不做（她拍的 / 留二期）

- **自动捞**：观察到 refusal 自动 roll——她选了不要。poller 只报 `notice`，不得调 `/app/roll_back`。
- **自动原样重试**：不做。
- **VPS body**：同一套搬去 VPS（fable 的 VPS 会话怎么起的先查：tmux/nohup/systemd），relay 端点已经按 body 设计好，二期只需搬守护三件。
- **esc 回退为何不认频道消息**：不查了，不依赖。
- 旧 `/app/reroll` 壳：继续留着，不动。
