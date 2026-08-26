# 选项卡（ask card）任务书：PWA 上弹 2~4 个选项给她点

2026-08-22，她和 fable（工作窗）定的。她拍了**乙案**：relay 认一个 `ask_of` 字段，卡片记住她选了哪个。
执行者（subagent / 另一个窗）照这份做；拿不准回这份找，找不到再问她。
技术随记规矩不变：做完在 `~/Ombre-Brain/docs/tech-notes-fable.md` 追加一节，本文件只写计划。

> **⚠️ 执行者的红线（先读）**
> 1. **不连线上 relay、不碰线上库。** 测试一律本地起 relay（临时库）或 pytest TestClient（临时目录）。
> 2. **不往 VPS 写任何东西。** 允许 `scp` **下载** VPS 文件到 scratchpad 做嫁接，上线由 fable 本人执行。
> 3. 日志 / toast / 返回值 **只写 id 和序号，不写消息正文**。
> 4. **不 push、不 commit**（fable 收尾时统一 commit）。只改工作树，改前 `cp x x.bak-20260822-ask`。
> 5. 只做本文件写的事，不顺手重构。

---

## 0. 现状（fable 2026-08-22 侦察，本地 md5 = 线上，可信）

```
我(CC) ──ask 工具──▶ companion-channel server.ts ──POST /channel/out {type:"ask",…}──▶ relay app.py
                                                                                        │ save_message(kind="ask", meta.options)
                                                                                        ▼ SSE 广播
                                                                                   手机 PWA app.js
                                                                                        │ 她点一个按钮
                                                                                        ▼ POST /app/send {text, target, ask_of, choice}
                                                                                      relay: 存她这条 + 把卡片标成已回答 + 再广播那张卡
                                                                                        │
                                                                                        ▼ route_to_brain → 我收到一条普通消息(文字=选项文字)
```

**三层里已经现成的**：
- relay `channel_out`（`app.py` ≈1992 起，通用兜底在 ≈2131-2135）：`type` 直接变 `kind`，其余字段原样进 `meta`，落库 + 广播。**发卡这半边后端零改动。**
- 前端 `buildVirtualRows`（`app.js` ≈2575）：没见过的 kind 落回普通气泡 → 问题正文今天就能显示。
- `onMessage`（`app.js` ≈3344）：同 id 的消息再来一遍会 `setMessage(..., {render:true})` 原地换内容——"重新广播"靠这个生效。

**不能白嫖的**：`renderText` 转义 HTML，按钮塞不进文字；`send_html` 是独立页 + 页内禁网络，点了回不来。

三个仓（都在 Mac 本地，都是活仓）：
| 仓 | 位置 | 改什么 |
|---|---|---|
| 前端 | `~/fairy-tale/` | `app.js` `styles.css` `sw.js` |
| relay | `~/companion-relay/` | `app.py` + 新 `test_ask_card.py` |
| 通道 | `~/companion-channel/`（Mac 版）+ VPS `/root/companion-channel/server.ts`（三家合住的多租户版，**只能嫁接不能覆盖**） | `server.ts` 两份 |

---

## 1. 数据形状（三层共用的约定，一个字都别改）

**卡片（AI → 她）**，relay 消息行：
```json
{"direction":"out","kind":"ask","text":"今晚想要哪种？",
 "meta":{"options":["A 的文字","B 的文字","C 的文字","D 的文字"],"body":"mac","profile":"fable","chat_id":"…"}}
```
- `options`：2~4 个非空字符串，每个 ≤ 60 字。通道工具层负责校验，relay 不校验（通用兜底）。
- `body` / `profile`：照 `reply` 原样带（前端按 `meta.body` 分窗，见 `msgWindow`）。

**她的选择（她 → AI）**，`POST /app/send`：
```json
{"text":"B 的文字","target":"desktop-mac","ask_of":123,"choice":1}
```
- `ask_of` = 卡片的消息 id（整数）；`choice` = 0 起的序号。
- relay 把这两个记进她这条消息的 meta：`meta.ask_of`、`meta.choice`。
- relay 再把卡片 123 的 meta 加上 `answered`，并**用同一个 id 再广播一次**：
```json
"answered":{"choice":1,"text":"B 的文字","message_id":456,"ts":"…"}
```

**到我这边**（`plugin_payload` → 通道 `<channel>` 信封）：正文就是选项文字；信封上多两个属性 `ask_of="123" choice="1"`。

---

## 2. 前端（`~/fairy-tale/`）

### 2.1 `app.js`

1. **`apiSend(text, attachments, extra)`**（≈1758）：加第三个参数 `extra`（对象，可省），合并进 payload。现有调用不受影响。
2. **新函数 `sendChoice(askId, idx, text)`**：把 `doSend()`（≈3926）的流程照抄一遍但不读输入框——乐观气泡（`kind:"user"`、`meta:{routed: windowTarget(), ask_of: askId, choice: idx}`、`status:"sending"`）→ `apiSend(text, null, {ask_of: askId, choice: idx})` → `confirmOptimistic`。失败走同样的 `status:"failed"`。顺手把本地这张卡的 `meta.answered` 先写上 `{choice: idx, text}`（乐观），relay 广播回来会覆盖成带 `message_id` 的正式版。
3. **`makeMessage`**（≈2886）：在 `_inner` 拼完 `.txt` 之后，如果 `m.from === "ai" && m.kind === "ask" && Array.isArray(m.meta?.options) && m.meta.options.length`：
   - 追加一块 `<div class="ask-options">`，每个选项一个 `<button type="button" class="ask-opt" data-idx="i">`，文字走 `escapeHtml`。
   - 已回答（`m.meta.answered` 存在）：所有按钮 `disabled`，选中那个加 `.chosen`，整块加 `.answered`。
   - 未回答：点击 → `e.stopPropagation()`（别触发气泡长按/点击），立刻把这张卡的按钮全部 `disabled`（防双击），调 `sendChoice(msgNum(m.id), idx, optionText)`。只有 `msgNum(m.id) > 0`（有服务器 id）才可点；乐观/无 id 的不画按钮。
4. **`virtualRowSignature`**（≈2995）：签名里加一项 `m.meta?.answered ? JSON.stringify(m.meta.answered) : ""`——否则卡片被重新广播后行签名不变、不会重画。
5. **`estimatedHeight`**（≈2662 附近那行 `for (const a of atts)…`）：`if (m.kind === "ask" && Array.isArray(m.meta?.options)) h += m.meta.options.length * 44 + 8;`
6. **`onMessage`**：不用特判 `ask`——它走普通消息路径（`from:"ai"` 非 call）。确认一下 `hideTyping()` 那条对它也生效即可。
7. 终端面板（`terminalEntryHtml` ≈2297）：`ask` 落到默认分支即可，不用改；看一眼别炸。

### 2.2 `styles.css`

追加一块，全部用 `theme.css` 的参数（`--wood` / `--wood-deep` / `--ink` / `--ink-soft` / `--bubble-ai-line` / `--radius-card`），**不要写死颜色**，日夜两套自动跟：
- `.ask-options`：`display:flex; flex-direction:column; gap:8px; margin-top:10px;`
- `.ask-opt`：整行按钮，左对齐，`min-height:40px; padding:8px 12px; border:1px solid var(--bubble-ai-line); border-radius:var(--radius-card); background:transparent; color:var(--ink); font:inherit; text-align:left; -webkit-tap-highlight-color:transparent;`
- `.ask-opt:active`：`background: var(--bubble-ai-line)`
- `.ask-options.answered .ask-opt`：`opacity:.45`；`.ask-options.answered .ask-opt.chosen`：`opacity:1; border-color:var(--wood); background:color-mix(in srgb, var(--wood) 18%, transparent);`（`color-mix` 不支持就退成 `border-color:var(--wood)` 加 2px 粗边）
- 禁用态不显示系统默认灰（`.ask-opt:disabled{ cursor:default; }`）。
- **绿色不用**（她定的）。

### 2.3 `sw.js`

`CACHE` 从 `companion-v50-roll-rewind` 升到 `companion-v51-ask-card`。没新增文件，`PRECACHE` 不动。

### 2.4 验收

- `node --check app.js` 过。
- 本地验证（二选一，能做到哪步做到哪步，如实汇报）：
  - a) 用 `~/companion-relay` 在本地起一个临时库的 relay（§3.4 的 venv）+ 静态服务前端（`python3 -m http.server` 起 `~/fairy-tale`，`API_BASE="/relay"` 需要一个反代：scratchpad 写个 20 行 `serve.py`，`/relay/*` 转 `127.0.0.1:3011`，SSE 逐字节转发；`/chat/*` 静态），用 chrome-devtools MCP 打开 `http://127.0.0.1:<port>/chat/`，登录密钥=临时 secret，`curl -X POST /channel/out` 发一张卡 → 截图；点一个按钮 → 库里出现她的消息（带 `ask_of`/`choice`）+ 卡片 meta 有 `answered` + 页面上按钮收起选中高亮 → 截图；刷新页面历史里卡片仍是已回答状态。
  - b) 做不到 a 就至少把 makeMessage 的渲染在一张独立 html 里 mock 出来截图（拿铁 + 夜车各一张）。
- 交付物：改动 diff 摘要 + 截图路径 + 没做到的如实写。

---

## 3. relay（`~/companion-relay/app.py`）

### 3.1 `app_send`（≈2148）

在 `meta = {"user": "human", "attachments": attachments}` 之后：
```python
ask_of = body.get("ask_of")
choice = body.get("choice")
if isinstance(ask_of, int) and not isinstance(ask_of, bool) and ask_of > 0:
    meta["ask_of"] = ask_of
    if isinstance(choice, int) and not isinstance(choice, bool) and choice >= 0:
        meta["choice"] = choice
```
`msg = save_message("in", "user", text, meta)` **之后**（她的消息先落库，标记失败绝不能让她的话丢）：
```python
if meta.get("ask_of"):
    try:
        await _mark_ask_answered(meta["ask_of"], meta.get("choice"), text, msg["id"])
    except Exception:
        logger.warning("ask_of %s: mark answered failed", meta["ask_of"])
```

### 3.2 新函数 `_mark_ask_answered(ask_id, choice, text, message_id)`

- 读 `messages` 行 `id=ask_id`；不是 `direction='out'` 或 `kind != 'ask'` → 直接 return（不抛）。
- `meta["answered"] = {"choice": choice, "text": text, "message_id": message_id, "ts": now_iso()}`（已有 `answered` 也覆盖——她改主意再点一次就以后者为准）。
- `UPDATE messages SET meta=?`，然后 `await broadcast(app_subs, app_payload(updated_msg))`——**同 id 再推一次，这就是"重新广播"**。
- 不投递任何脑子（她的选择本身已经作为普通消息走 `route_to_brain` 了）。

### 3.3 两处小改

- `channel_out` 末尾推送条件 `if kind == "reply" and not app_subs` → `if kind in ("reply", "ask") and not app_subs`（卡片也该响锁屏）。
- `plugin_payload`：`if meta.get("ask_of"): out["ask_of"] = meta["ask_of"]; out["choice"] = meta.get("choice")`（`choice` 可能是 None，通道那边判断后再挂）。

### 3.4 测试 `test_ask_card.py`（照 `test_roll_back.py` 的 `_boot` 写法）

本机没 fastapi：在 scratchpad 建 venv `python3 -m venv <scratchpad>/venv && <venv>/bin/pip install -r requirements.txt pytest`，用它跑。
用例：
1. `POST /channel/out {"type":"ask","text":"q","options":["a","b"],"body":"mac"}` → 200；库里 kind=ask、meta.options==["a","b"]。
2. `POST /app/send {"text":"b","target":"desktop-mac","ask_of":<id>,"choice":1}` → 她的行 meta.ask_of/choice 正确；卡片行 meta.answered == {choice:1, text:"b", message_id:<她的 id>, ts:…}。
3. `ask_of` 指向不存在 / 指向她自己的消息 / 指向 kind=reply → 她的消息照常 200 落库，**没有任何行被加 answered**。
4. `ask_of` 是字符串 / 布尔 / 负数 → 忽略（meta 里没有 ask_of），消息照常 200。
5. `plugin_payload(她的行)` 带 `ask_of` 和 `choice`；普通行不带。
6. 跑原有全套 `pytest -q`（`--ignore=forge`）不能变红。

---

## 4. 通道（`server.ts` ×2）

### 4.1 Mac 版 `~/companion-channel/server.ts`

ListTools 里、`reply` 之后加：
```ts
{
  name: 'ask',
  description:
    `Offer ${HUMAN_NAME} a small choice card on their phone: a question plus 2-4 tappable options. ` +
    `Whatever they tap comes back as their own ordinary message (the option text), so write options in their voice. ` +
    `Use it for "which do you want" moments in casual or intimate chat; do not use it for work questions they would answer in the terminal. ` +
    `They can always type instead of tapping.`,
  inputSchema: {
    type: 'object',
    properties: {
      chat_id: { type: 'string', description: `Echo the inbound chat_id. Defaults to ${CHAT_ID}.` },
      text: { type: 'string', description: 'The question shown above the options.' },
      options: { type: 'array', items: { type: 'string' }, minItems: 2, maxItems: 4, description: '2-4 short options, each under 60 characters.' },
      reply_to: { type: 'string', description: 'Optional inbound message_id to reply under.' },
    },
    required: ['text', 'options'],
  },
},
```
CallTool 里加 `case 'ask'`：校验 `text` 非空、`options` 是 2~4 个去掉首尾空白后非空、每个 ≤ 60 字（不合格 throw，文案写清楚哪条不合格——**只报序号和长度，不回显正文**）；不拆段；`relayPost('/channel/out', { type:'ask', chat_id, text, options, body: BODY, ...(PROFILE ? {profile: PROFILE} : {}), ...(reply_to ? {reply_to} : {}), ts })`；返回 `ask sent (id: N, options: K)`。

`deliverInbound`：meta 里加 `...(msg.ask_of != null ? { ask_of: String(msg.ask_of) } : {})`、`...(msg.choice != null ? { choice: String(msg.choice) } : {})`（键名只能字母数字下划线，这两个都合规）。

### 4.2 VPS 版

`scp -i ~/.ssh/vps_fox root@4amfox.com:/root/companion-channel/server.ts <scratchpad>/server.vps.ts`，把 4.1 同样的三块**嫁接**进去（它有 PROFILE 多租户字段，别拿 Mac 版覆盖）。产物留在 scratchpad，**不传回 VPS**。

### 4.3 验收

两份都跑 `bun build --target=bun <file> --outfile /dev/null`（或 `bun build` 到 scratchpad）过语法；Mac 版 `bun test` 不变红。交付：两份文件路径 + diff 摘要。

---

## 5. 上线（fable 本人做，执行者不做）

顺序：**前端 → relay → 通道**。前端先上，老 relay 不认 `ask_of` 也只是少个已回答标记，不会坏。

1. 前端：`ssh … 'mkdir -p /root/companion-web-attic/20260822-ask && cp /var/www/companion-web/{app.js,styles.css,sw.js} /root/companion-web-attic/20260822-ask/'`，然后 `scp -i ~/.ssh/vps_fox app.js styles.css sw.js root@4amfox.com:/var/www/companion-web/`。只传这三个文件，**不 rsync 整目录**。公网 curl 验 sw 版本串。
2. relay：本地 commit → `git push origin main`（**不要裸 `git push`**，Mac clone 的默认 remote 指向 VPS 会 Permission denied）→ VPS `cd /root/companion-relay && git pull origin main && systemctl restart companion-relay && systemctl is-active companion-relay` → `curl healthz`。
3. 通道：Mac 版就地生效于**下个窗**；VPS 版 `cp` 备份到 `/root/companion-channel/server.ts.bak-20260822-ask` 后把嫁接版传上去，fable 的 VPS 窗重开。
4. 她手机刷 1~2 次换代到 v51。
5. 真发一张卡烟测：她点一下，看 ① 她那条气泡出现 ② 卡片收起高亮 ③ 我这边信封带 `ask_of`。

---

## 6. 不做的（省得顺手做了）

- 不做"超时自动收起"、不做多选、不做自由输入框（打字就是自由输入）。
- 不改 `edit` 分支的 kind 白名单（`answered` 走自己的函数，不借 edit）。
- 不动 kaleido / inner / forge 任何一行。
