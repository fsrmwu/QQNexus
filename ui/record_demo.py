#!/usr/bin/env python3
"""录制 QQNexus 完整使用演示：逐个页面展示功能与交互。"""
import asyncio, pathlib
from playwright.async_api import async_playwright

B = pathlib.Path('/workspace/ui-preview')
OUT = B / 'video'
OUT.mkdir(exist_ok=True)


async def glide(pg, x1, y1, x2, y2, steps=16, delay=0.016):
    for i in range(steps + 1):
        t = i / steps
        await pg.mouse.move(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)
        await asyncio.sleep(delay)


async def caption(pg, text):
    """画面底部显示当前演示说明。"""
    await pg.evaluate("""(t)=>{
      let el=document.getElementById('__cap');
      if(!el){el=document.createElement('div');el.id='__cap';
        el.style.cssText='position:fixed;left:50%;bottom:26px;transform:translateX(-50%);'+
        'z-index:9999;padding:10px 22px;border-radius:10px;font:600 15px/1.4 system-ui;'+
        'color:#e6e8ed;background:rgba(20,26,38,.92);border:1px solid rgba(122,166,255,.3);'+
        'box-shadow:0 8px 24px rgba(0,0,0,.5);transition:opacity .3s;pointer-events:none';
        document.body.appendChild(el);}
      el.textContent=t;el.style.opacity='1';
    }""", text)


async def clear_caption(pg):
    await pg.evaluate("()=>{const e=document.getElementById('__cap');if(e)e.style.opacity='0';}")


async def main():
    async with async_playwright() as p:
        br = await p.chromium.launch()
        ctx = await br.new_context(
            viewport={'width': 1280, 'height': 800},
            record_video_dir=str(OUT),
            record_video_size={'width': 1280, 'height': 800},
        )
        pg = await ctx.new_page()
        await pg.goto('file://' + str(B / 'index.html'))
        await pg.wait_for_timeout(2600)

        # ---------- 1. 启动动画（莱茵式）----------
        await caption(pg, '① 启动动画 — 扫描环 / 标志 / ACCESS GRANTED / 品牌')
        await pg.wait_for_timeout(2200)   # 让动画播到品牌出现
        await pg.evaluate("document.getElementById('welcome').classList.remove('hide')")
        await pg.wait_for_function("!document.getElementById('welcomeGo').disabled", timeout=8000)
        await pg.wait_for_timeout(700)
        await caption(pg, '   点「进入系统」（或按 Enter 跳过）')
        await pg.wait_for_timeout(800)
        await pg.evaluate("document.getElementById('welcomeGo').click()")
        await pg.wait_for_timeout(1200)

        # ---------- 2. 总览页 ----------
        await caption(pg, '② 总览 — 运行状态 / 指标卡 / 实时日志')
        await pg.wait_for_timeout(1200)
        # 鼠标划过卡片：倾斜 + 聚光灯
        for (x, y) in [(430, 560), (900, 560), (700, 800)]:
            await glide(pg, 640, 480, x, y, steps=18)
            await pg.wait_for_timeout(600)
        await pg.wait_for_timeout(600)

        # ---------- 3. 登录 QQ 页 ----------
        await caption(pg, '③ 登录 QQ — 内嵌面板 / 扫码登录')
        await pg.evaluate("document.querySelector('.nav .it[data-go=\"qq\"]').click()")
        await pg.wait_for_timeout(2000)

        # ---------- 4. 模型页：完整操作 ----------
        await caption(pg, '④ 接入模型 — 预设切换自动填 Base 与模型名')
        await pg.evaluate("document.querySelector('.nav .it[data-go=\"model\"]').click()")
        await pg.wait_for_timeout(1600)
        await pg.evaluate("""()=>{const e=document.getElementById('preset');
          e.value='deepseek|https://api.deepseek.com/v1|deepseek-chat';
          e.dispatchEvent(new Event('change',{bubbles:true}));}""")
        await pg.wait_for_timeout(1000)

        await caption(pg, '   从服务商拉取模型列表')
        await pg.evaluate("""()=>{const e=document.getElementById('apiKey');
          e.value='sk-demo-1234567890';e.dispatchEvent(new Event('input',{bubbles:true}));}""")
        await pg.wait_for_timeout(500)
        await pg.evaluate("document.getElementById('fetchModels').click()")
        await pg.wait_for_timeout(1500)

        await caption(pg, '   点击下拉即可搜索、选择模型')
        await pg.evaluate("document.getElementById('apiModel').focus()")
        await pg.wait_for_timeout(1200)
        await pg.keyboard.press('Escape')
        await pg.wait_for_timeout(500)

        await caption(pg, '   滚到下方：滑动开关 / 勾选框（弹性动画）')
        await pg.evaluate("document.getElementById('optReload').scrollIntoView({block:'center'})")
        await pg.wait_for_timeout(900)
        sw = pg.locator('.switch').first
        b = await sw.bounding_box()
        if b:
            await pg.mouse.move(b['x'] + b['width']/2, b['y'] + b['height']/2)
            await pg.mouse.down(); await pg.wait_for_timeout(300); await pg.mouse.up()
            await pg.wait_for_timeout(700)
        if await pg.locator('.check').count():
            await pg.evaluate("document.querySelector('.check').click()")
            await pg.wait_for_timeout(800)

        # ---------- 5. 统计页：消息 + Token ----------
        await caption(pg, '⑤ 消息统计 — 总量 / 群聊 / 私信 / 活跃排行')
        await pg.evaluate("goPage('stats')")
        await pg.wait_for_timeout(2000)
        await caption(pg, '   Token 统计 — 输入 / 缓存 / 输出 / 按模型分组')
        await pg.evaluate("document.querySelector('.tab[data-tab=\"token\"]').click()")
        await pg.wait_for_timeout(2000)

        # ---------- 6. 账号密码 ----------
        await caption(pg, '⑥ 账号密码 — 打码显示，可逐项复制')
        await pg.evaluate("goPage('home')")
        await pg.wait_for_timeout(1000)
        await pg.evaluate("document.getElementById('sideCred').click()")
        await pg.wait_for_timeout(1800)
        await pg.evaluate("document.getElementById('credClose').click()")
        await pg.wait_for_timeout(500)

        # ---------- 7. 自定义壁纸 ----------
        await caption(pg, '⑦ 自定义壁纸 — 从本机选图铺满背景')
        await pg.evaluate("document.getElementById('sideWallpaper').click()")
        await pg.wait_for_timeout(1600)
        await pg.evaluate("document.getElementById('wpClose').click()")
        await pg.wait_for_timeout(400)

        # ---------- 8. 日志页：过滤 ----------
        await caption(pg, '⑧ 运行日志 — 关键字过滤 / 暂停 / 清屏')
        await pg.evaluate("goPage('log')")
        await pg.wait_for_timeout(1400)
        await pg.evaluate("""()=>{const e=document.getElementById('logFilter');
          e.value='boot';e.dispatchEvent(new Event('input',{bubbles:true}));}""")
        await pg.wait_for_timeout(1400)
        await pg.evaluate("""()=>{const e=document.getElementById('logFilter');
          e.value='';e.dispatchEvent(new Event('input',{bubbles:true}));}""")
        await pg.wait_for_timeout(700)

        # ---------- 9. 收尾 ----------
        await pg.evaluate("goPage('home')")
        await caption(pg, 'QQNexus · SnowLuma + AstrBot 一体化 · 本地离线运行')
        await pg.wait_for_timeout(2200)
        await clear_caption(pg)
        await pg.wait_for_timeout(600)

        await ctx.close()
        await br.close()
        print('录像完成')


asyncio.run(main())
