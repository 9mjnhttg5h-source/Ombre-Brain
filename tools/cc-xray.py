#!/usr/bin/env python3
"""cc-xray：截下 Claude Code 真正发给 API 的请求，看清 system + tools 到底是什么。
用法：  python3 cc-xray.py -- --system-prompt "你的提示词" --tools Bash,Read --strict-mcp-config
不产生任何真实 API 费用（请求被本地假服务器接住）。"""
import json, os, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ.get("XRAY_PORT", "8787"))
CAP = {"body": None}
SSE = (b'event: message_start\ndata: {"type":"message_start","message":{"id":"m","type":"message","role":"assistant","model":"x","content":[],"stop_reason":null,"stop_sequence":null,"usage":{"input_tokens":1,"output_tokens":1}}}\n\n'
       b'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n'
       b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"ok"}}\n\n'
       b'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n'
       b'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn","stop_sequence":null},"usage":{"output_tokens":1}}\n\n'
       b'event: message_stop\ndata: {"type":"message_stop"}\n\n')

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        n = int(self.headers.get('content-length') or 0)
        b = self.rfile.read(n) if n else b''
        if CAP["body"] is None and b'"messages"' in b: CAP["body"] = b
        self.send_response(200); self.send_header("content-type","text/event-stream")
        self.send_header("content-length",str(len(SSE))); self.end_headers(); self.wfile.write(SSE)
    def do_GET(self):
        b=b'{"ok":true}'; self.send_response(200); self.send_header("content-type","application/json")
        self.send_header("content-length",str(len(b))); self.end_headers(); self.wfile.write(b)

srv = HTTPServer(("127.0.0.1", PORT), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
time.sleep(0.4)

args = sys.argv[1:]
if args and args[0] == "--": args = args[1:]
env = dict(os.environ)
for k in ("CLAUDECODE","CLAUDE_CODE_SESSION_ID","CLAUDE_CODE_CHILD_SESSION","CLAUDE_CODE_ENTRYPOINT",
          "CLAUDE_CODE_MESSAGING_SOCKET","CLAUDE_CODE_MESSAGING_TOKEN","CLAUDE_EFFORT"): env.pop(k, None)
env["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{PORT}"
env["ANTHROPIC_API_KEY"] = "xray-fake-key"
subprocess.run(["claude","-p","hi","--no-session-persistence"] + args, env=env,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
srv.shutdown()

if CAP["body"] is None:
    print("没截到请求。可能 claude 启动失败，去掉 stdout=DEVNULL 再看报错。"); sys.exit(1)
d = json.loads(CAP["body"])
open("/tmp/cc-xray-capture.json","wb").write(CAP["body"])
sysb = d.get("system") or []
if isinstance(sysb, str): sysb = [{"text": sysb}]
sysc = sum(len(b.get("text","")) for b in sysb)
tools = d.get("tools", [])
toolc = sum(len(t.get("description","") or "")+len(json.dumps(t.get("input_schema",{}),ensure_ascii=False)) for t in tools)
msgc = len(json.dumps(d.get("messages",[]), ensure_ascii=False))
print("="*72)
print(f"SYSTEM 共 {sysc} 字符，{len(sysb)} 段：")
for i,b in enumerate(sysb):
    t=b.get("text","")
    print(f"\n  --- 第{i+1}段 ({len(t)} 字符) ---")
    print("  " + (t if len(t)<=3000 else t[:3000]+"\n  …<还有 %d 字符，全文见 /tmp/cc-xray-capture.json>"%(len(t)-3000)).replace("\n","\n  "))
print("\n"+"="*72)
print(f"TOOLS 共 {len(tools)} 个，说明+schema 合计 {toolc} 字符：")
for t in sorted(tools, key=lambda x:-(len(x.get('description','') or '')+len(json.dumps(x.get('input_schema',{}))))):
    dl=len(t.get("description","") or ""); sl=len(json.dumps(t.get("input_schema",{}),ensure_ascii=False))
    print(f"   {t['name']:<45} 说明{dl:>6}  schema{sl:>6}")
print("\n"+"="*72)
print(f"首轮 messages {msgc} 字符（含 system-reminder / MCP 说明 / CLAUDE.md 等注入）")
print(f"\n>>> 首轮上下文合计约 {int(sysc/3.8+toolc/3.4+msgc/3.8)} tokens（估算）")
print(">>> 完整原始请求已存到 /tmp/cc-xray-capture.json")
