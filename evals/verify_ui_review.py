"""CDP 驱动 headless Edge 验证前端审批面板（HITL）完整交互流。

流程：打开页面 → 输入 Notion → 提交 → 等 review_required 面板出现 →
截图 → 点「批准出稿」→ 等报告渲染 → 截图 → 断言报告非空。

这是临时验证脚本，验证完即删（或留在 evals/ 供复用）。
"""
import json
import subprocess
import sys
import time
import urllib.request

import websockets

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
DEBUG_PORT = 9223
PAGE_URL = "http://127.0.0.1:5173/"

async def main() -> int:
    # 启动 headless Edge（CDP 端口）
    proc = subprocess.Popen(
        [
            EDGE,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            f"--remote-debugging-port={DEBUG_PORT}",
            "--user-data-dir=C:\\Windows\\Temp\\wb-edge-review",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        # 等 CDP 就绪
        target = None
        for _ in range(50):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json") as r:
                    pages = json.load(r)
                for p in pages:
                    if p.get("type") == "page":
                        target = p
                        break
                if target:
                    break
            except Exception:
                pass
            time.sleep(0.2)
        if not target:
            print("FAIL: 拿不到 CDP target")
            return 1

        ws_url = target["webSocketDebuggerUrl"]
        async with websockets.connect(ws_url, max_size=20 * 1024 * 1024) as ws:
            msg_id = 0

            async def send(method, params=None):
                nonlocal msg_id
                msg_id += 1
                await ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
                while True:
                    resp = json.loads(await ws.recv())
                    if resp.get("id") == msg_id:
                        return resp

            async def eval_js(expr):
                r = await send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
                return r.get("result", {}).get("result", {}).get("value")

            # 导航到页面
            await send("Page.enable")
            await send("Runtime.enable")
            await send("Page.navigate", {"url": PAGE_URL})
            await asyncio_sleep(3)

            # 输入公司名并提交
            await eval_js("""
                (() => {
                  const input = document.querySelector('input#companyName');
                  if (!input) return 'NO_INPUT';
                  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                  setter.call(input, 'Notion');
                  input.dispatchEvent(new Event('input', { bubbles: true }));
                  return 'typed';
                })()
            """)
            await asyncio_sleep(0.3)
            await eval_js("""
                (() => {
                  const btn = document.querySelector('button[type=submit]');
                  if (!btn) return 'NO_BTN';
                  btn.click();
                  return 'clicked';
                })()
            """)

            # 等审批面板出现（最多 20s）
            review_seen = False
            for _ in range(40):
                txt = await eval_js("document.body.innerText")
                if txt and "人工复核成稿" in txt:
                    review_seen = True
                    break
                await asyncio_sleep(0.5)

            if not review_seen:
                body = await eval_js("document.body.innerText")
                print("FAIL: 审批面板未出现。页面文本:", (body or "")[:400])
                return 1

            print("OK: 审批面板已出现")
            panel_text = await eval_js("document.body.innerText")
            # 打印面板关键内容
            for line in panel_text.splitlines():
                if any(k in line for k in ("人工复核", "批准", "拒答", "栏目", "Notion", "检索")):
                    print("  |", line.strip())

            # 点「批准出稿」
            clicked = await eval_js("""
                (() => {
                  const btns = Array.from(document.querySelectorAll('button'));
                  const approve = btns.find(b => b.innerText.includes('批准出稿'));
                  if (!approve) return 'NO_APPROVE';
                  approve.click();
                  return 'clicked';
                })()
            """)
            print("点批准:", clicked)
            await asyncio_sleep(0.5)

            # 等报告出现
            report_seen = False
            for _ in range(60):
                txt = await eval_js("document.body.innerText")
                if txt and ("研究报告" in txt or "公司概览" in txt or "References" in txt):
                    report_seen = True
                    break
                await asyncio_sleep(0.5)

            if not report_seen:
                body = await eval_js("document.body.innerText")
                print("FAIL: 报告未出现。页面文本:", (body or "")[:400])
                return 1

            report_text = await eval_js("document.body.innerText")
            print("OK: 报告已渲染")
            has_heading = any(k in report_text for k in ("研究报告", "公司概览", "行业", "财务", "新闻"))
            print("  含栏目标题:", has_heading)
            # 截图留证
            shot = await send("Page.captureScreenshot", {"format": "png"})
            import base64
            data = shot.get("result", {}).get("data", "")
            if data:
                with open("evals/ui_review_flow.png", "wb") as f:
                    f.write(base64.b64decode(data))
                print("  截图: evals/ui_review_flow.png")

        return 0
    finally:
        proc.terminate()


async def asyncio_sleep(s):
    import asyncio
    await asyncio.sleep(s)


if __name__ == "__main__":
    import asyncio
    sys.exit(asyncio.run(main()))
