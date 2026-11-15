#!/usr/bin/env python3
"""Real panel HTTP + browser checks. Does not log in or simulate QQ events."""
import asyncio,json,pathlib,socket,time,urllib.request
from playwright.async_api import async_playwright
ROOT=pathlib.Path('/workspace/QQNexus'); OUT=ROOT/'reports'

async def main():
    result={'tested_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'mode':'real-local-services','panels':{},'qq_login_verified':False,'real_onebot_connection_verified':False,'llm_reply_verified':False}
    async with async_playwright() as pw:
        browser=await pw.chromium.launch()
        for name,port in [('astrbot',6185),('snowluma',5099)]:
            url=f'http://127.0.0.1:{port}/'
            with urllib.request.urlopen(url,timeout=5) as r:
                http_info={'status':r.status,'content_type':r.headers.get('Content-Type'),'x_frame_options':r.headers.get('X-Frame-Options'),'csp':r.headers.get('Content-Security-Policy')}
            ctx=await browser.new_context(viewport={'width':1280,'height':800},device_scale_factor=1)
            pg=await ctx.new_page()
            errors=[]; assets=[]; failures=[]
            pg.on('pageerror',lambda e: errors.append(str(e)))
            pg.on('response',lambda r: assets.append({'url':r.url,'status':r.status}) if r.request.resource_type in ('script','stylesheet') else None)
            pg.on('requestfailed',lambda q: failures.append({'url':q.url,'error':q.failure}))
            await pg.goto(url,wait_until='domcontentloaded',timeout=60000)
            await pg.wait_for_timeout(2200)
            await pg.screenshot(path=str(OUT/f'{name}-real-panel.png'),full_page=False)
            body=(await pg.locator('body').inner_text())[:4000]
            item={'url':url,'final_url':pg.url,'http':http_info,'title':await pg.title(),'body':body,'browser_errors':errors,'assets':assets,'request_failures':failures,'screenshot':f'{name}-real-panel.png'}
            result['panels'][name]=item
            print(name,'HTTP',http_info['status'],'title=',item['title'],'errors=',len(errors),'assets=',len(assets),'body=',body[:400].replace('\n',' | '),flush=True)
            await ctx.close()
        await browser.close()
    try:
        with socket.create_connection(('127.0.0.1',6199),timeout=3):result['astrbot_onebot_listener']=True
    except OSError:result['astrbot_onebot_listener']=False
    (OUT/'real-panels-smoke.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print('Saved real-panels-smoke.json. Login/QQ/LLM remain unverified.',flush=True)

asyncio.run(main())
