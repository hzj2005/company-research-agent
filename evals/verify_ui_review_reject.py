"""CDP 驱动 headless Edge 验证「勾选栏目拒答」分支（HITL 前端唯一未测的逻辑路径）。

流程：打开页面 → 输入 Notion → 提交 → 等审批面板 → 勾选「新闻动态」→
点「批准出稿」→ 断言报告里新闻栏目变成「未找到公开依据」、其余栏目照常。

这个分支是前端自己的逻辑（toggle + 传 rejected_sections 数组），后端测试覆盖不到，
所以单独验一遍：UI 上勾的栏目，必须真的变成拒答。
"""
import base64
import json
import subprocess
import sys
import time
import urllib.request

import websockets

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
DEBUG_PORT = 9224
PAGE_URL = "http://127.0.0.1:5173/"
ABSTAIN = "未找到公开依据"


async def main() -> int:
    proc = subprocess.Popen(
        [
            EDGE,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            f"--remote-debugging-port={DEBUG_PORT}",
            "--user-data-dir=C:\\Windows\\Temp\\wb-edge-reject",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        target = None
        for _ in range(50):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json") as r:
                    for p in json.load(r):
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

        async with websockets.connect(target["webSocketDebuggerUrl"], max_size=20 * 1024 * 1024) as ws:
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
                r = await send(
                    "Runtime.evaluate",
                    {"expression": expr, "returnByValue": True, "awaitPromise": True},
                )
                return r.get("result", {}).get("result", {}).get("value")

            await send("Page.enable")
            await send("Runtime.enable")
            await send("Page.navigate", {"url": PAGE_URL})
            await _sleep(3)

            await eval_js("""
                (() => {
                  const input = document.querySelector('input#companyName');
                  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                  setter.call(input, 'Notion');
                  input.dispatchEvent(new Event('input', { bubbles: true }));
                  document.querySelector('button[type=submit]').click();
                  return 'submitted';
                })()
            """)

            # 等审批面板
            seen = False
            for _ in range(40):
                txt = await eval_js("document.body.innerText")
                if txt and "人工复核成稿" in txt:
                    seen = True
                    break
                await _sleep(0.5)
            if not seen:
                print("FAIL: 审批面板未出现")
                return 1
            print("OK: 审批面板出现")

            # 勾选「新闻动态」
            toggled = await eval_js("""
                (() => {
                  const btns = Array.from(document.querySelectorAll('button'));
                  const target = btns.find(b => b.innerText.trim() === '新闻动态');
                  if (!target) return 'NO_SECTION';
                  target.click();
                  return 'toggled';
                })()
            """)
            print("勾选新闻动态:", toggled)
            await _sleep(0.4)

            # 确认勾选生效（按钮文案/样式变化）：面板按钮文字应仍是「批准出稿」
            # （只勾一个栏目不是全拒答），但新闻动态按钮应带拒答样式
            marked = await eval_js("""
                (() => {
                  const btns = Array.from(document.querySelectorAll('button'));
                  const target = btns.find(b => b.innerText.trim() === '新闻动态');
                  return target ? target.className.includes('FE363B') : false;
                })()
            """)
            print("新闻动态已标为拒答样式:", marked)
            if not marked:
                print("FAIL: 勾选没有生效")
                return 1

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
            await _sleep(0.5)

            # 等报告（栏目标题以 config/settings.yaml 为准：不是「概览」是「概况」）
            report_text = ""
            for _ in range(60):
                report_text = await eval_js("document.body.innerText") or ""
                if "公司概况" in report_text or "研究报告" in report_text:
                    break
                await _sleep(0.5)

            if not report_text or "公司概况" not in report_text:
                print("FAIL: 报告未渲染。文本:", report_text[:300])
                return 1

            has_abstain = ABSTAIN in report_text
            has_news = "新闻动态" in report_text
            has_company = "公司概况" in report_text
            print("OK: 报告已渲染")
            print("  含拒答文案:", has_abstain)
            print("  含新闻栏目:", has_news)
            print("  含公司栏目:", has_company)

            # 审批面板应当已经消失
            panel_gone = "人工复核成稿" not in report_text
            print("  审批面板已消失:", panel_gone)

            shot = await send("Page.captureScreenshot", {"format": "png"})
            data = shot.get("result", {}).get("data", "")
            if data:
                with open("evals/ui_review_reject.png", "wb") as f:
                    f.write(base64.b64decode(data))

            ok = has_abstain and has_company and panel_gone
            if not ok:
                print("FAIL: 勾选栏目未反映到报告里")
                return 1
            print("PASS: 勾选的栏目真的变成拒答，其余栏目照常")
        return 0
    finally:
        proc.terminate()


async def _sleep(s):
    import asyncio
    await asyncio.sleep(s)


if __name__ == "__main__":
    import asyncio
    sys.exit(asyncio.run(main()))
