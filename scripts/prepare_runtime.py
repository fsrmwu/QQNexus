"""First-run setup: create credentials and loopback-only config. Offline."""
from pathlib import Path
import json, secrets, zipfile, os, sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import project_root

ROOT = project_root()

cred = ROOT / 'credential.json'
if cred.exists():
    c = json.loads(cred.read_text())
else:
    c = {
        'astrbot_user': 'astrbot',
        'astrbot_password': 'QnA9-' + secrets.token_urlsafe(18),
        'snowluma_password': 'QnS9-' + secrets.token_urlsafe(18),
        'onebot_token': secrets.token_urlsafe(32),
    }
    cred.write_text(json.dumps(c, indent=2))
    os.chmod(cred, 0o600)

# AstrBot：数据根目录固定在安装目录内，面板与 OneBot 只监听回环
astr_root = ROOT / 'astrbot' / 'root'
(astr_root / 'data').mkdir(parents=True, exist_ok=True)
cfg = astr_root / 'data' / 'cmd_config.json'
if not cfg.exists():
    cfg.write_text(json.dumps({
        'dashboard': {'host': '127.0.0.1', 'port': 6185},
        'platform': [{
            'id': 'qqnexus_snowluma', 'type': 'aiocqhttp', 'enable': True,
            'ws_reverse_host': '127.0.0.1', 'ws_reverse_port': 6199,
            'ws_reverse_token': c['onebot_token'],
        }],
    }, indent=2))

# 面板静态资源：优先用已解压的 dist；缺失时从内置 zip 展开
ROOT_DIR = Path(__file__).resolve().parent.parent
cand_dists = [
    ROOT / 'astrbot' / 'src' / 'astrbot' / 'dashboard' / 'dist',   # 安装布局
    ROOT_DIR / 'src' / 'astrbot' / 'astrbot' / 'dashboard' / 'dist',  # 开发布局
]
dist = next((d for d in cand_dists if (d / 'index.html').exists()), cand_dists[0])
if not (dist / 'index.html').exists():
    cand_zips = [
        ROOT / 'astrbot' / 'dashboard.zip',
        ROOT_DIR / 'vendor' / 'AstrBot-v4.29.4-dashboard.zip',
    ]
    zpath = next((z for z in cand_zips if z.exists()), None)
    if zpath is None:
        raise SystemExit('Bundled dashboard archive missing')
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
        prefix = 'dist/' if 'dist/index.html' in names else ''
        dist.mkdir(parents=True, exist_ok=True)
        for info in z.infolist():
            name = info.filename[len(prefix):] if prefix else info.filename
            if not name:
                continue
            if '..' in Path(name).parts or Path(name).is_absolute():
                raise SystemExit('unsafe archive entry')
            target = dist / name
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(info))

# SnowLuma：面板端口 + 指向 AstrBot 的反向 WebSocket 客户端
snow_cfg = ROOT / 'snowluma' / 'config'
snow_cfg.mkdir(parents=True, exist_ok=True)
rt = snow_cfg / 'runtime.json'
if not rt.exists():
    rt.write_text(json.dumps({
        'webuiPort': 5099, 'webuiHost': '127.0.0.1', 'hookAutoLoad': False,
        'logMaxTotalMb': 128, 'logRetainDays': 7,
    }, indent=2))
ob = snow_cfg / 'onebot.json'
if not ob.exists():
    ob.write_text(json.dumps({'networks': {
        'httpServers': [], 'httpClients': [], 'wsServers': [],
        'wsClients': [{
            'name': 'qqnexus-astrbot', 'enabled': True,
            'url': 'ws://127.0.0.1:6199/ws', 'role': 'Universal',
            'accessToken': c['onebot_token'], 'messageFormat': 'array',
            'reportSelfMessage': False, 'reconnectIntervalMs': 3000,
        }],
    }}, indent=2))

print('首次配置完成：只监听 127.0.0.1，凭据已保存到 credential.json')
