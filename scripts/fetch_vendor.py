import concurrent.futures,hashlib,json,pathlib,urllib.request,time
ROOT=pathlib.Path('/workspace/QQNexus'); V=ROOT/'vendor'
HEADERS={'User-Agent':'QQNexus-build','Accept':'application/vnd.github+json'}
def api(url):
 with urllib.request.urlopen(urllib.request.Request(url,headers=HEADERS),timeout=40) as r:return json.load(r)
lock={'components':{},'assets':[]}
jobs=[]
for key,repo,tag in [('astrbot','AstrBotDevs/AstrBot','v4.29.4'),('snowluma','TomyJan/SnowLuma','v2.4.2')]:
 commit=api(f'https://api.github.com/repos/{repo}/commits/{tag}')['sha']
 lock['components'][key]={'repo':repo,'tag':tag,'commit':commit}
 jobs.append({'name':key+'-'+commit+'.tar.gz','url':f'https://codeload.github.com/{repo}/tar.gz/{commit}','component':key,'role':'source'})
 print('PIN',key,tag,commit,flush=True)
for key,meta,chosen in [('astrbot',json.loads((V/'astr-release.json').read_text()),['AstrBot-v4.29.4-dashboard.zip']),('snowluma',json.loads((V/'snow-releases.json').read_text())[0],['checksums.sha256','release.json','SnowLuma-v2.4.2-linux-arm64.tar.gz','SnowLuma-v2.4.2-win-x64.zip'])]:
 for a in meta['assets']:
  if a['name'] in chosen:jobs.append({'name':a['name'],'url':a['browser_download_url'],'asset_url':a['url'],'component':key,'role':'release','expected_digest':a.get('digest')})
def download(job):
 dest=V/job['name']; tmp=dest.with_suffix(dest.suffix+'.part')
 if dest.exists():
  digest=hashlib.sha256(dest.read_bytes()).hexdigest()
  if not job.get('expected_digest') or job['expected_digest']=='sha256:'+digest:
   print('CACHED',job['name'],flush=True)
   return {**job,'sha256':digest,'size':dest.stat().st_size}
 for attempt in range(3):
  try:
   h=hashlib.sha256();size=0
   url=job.get('asset_url',job['url'])+'?qqnexus='+str(int(time.time()))
   with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'QQNexus-build','Accept':'application/octet-stream'}),timeout=60) as r, tmp.open('wb') as f:
    while chunk:=r.read(1024*1024):f.write(chunk);h.update(chunk);size+=len(chunk)
   digest='sha256:'+h.hexdigest()
   if job.get('expected_digest') and digest!=job['expected_digest']:raise RuntimeError('checksum mismatch')
   tmp.replace(dest)
   result={**job,'sha256':h.hexdigest(),'size':size}
   print('SAVED',job['name'],size,'bytes',h.hexdigest(),flush=True)
   return result
  except Exception as e:
   print('RETRY',job['name'],str(e),flush=True);time.sleep(2)
 raise RuntimeError('Download failed: '+job['name'])
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
 for entry in pool.map(download,jobs):lock['assets'].append(entry)
(ROOT/'vendor-lock.json').write_text(json.dumps(lock,ensure_ascii=False,indent=2))
print('ALL VENDOR FILES SAVED',flush=True)
