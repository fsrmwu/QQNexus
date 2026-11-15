#!/usr/bin/env python3
"""Start a pinned local component with paths resolved relative to this install.

No network access: repositories, dependencies and dashboard assets are all bundled.
"""
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
from _paths import project_root, script_dir

ROOT = project_root()

# 安装根目录：脚本可能被平铺到安装根，也可能留在 scripts/ 下，向上找到含 credential.json 的一级
if len(sys.argv) < 2 or sys.argv[1] not in ('astrbot', 'snowluma'):
    raise SystemExit('Usage: run_component.py astrbot|snowluma [--print-exec]')
component = sys.argv[1]

creds_path = ROOT / 'credential.json'
if not creds_path.exists():
    raise SystemExit('credential.json missing; reinstall the package')
credentials = json.loads(creds_path.read_text())
env = os.environ.copy()

if component == 'astrbot':
    base = ROOT / 'astrbot'
    # 只有安装布局的关键文件真的存在，才走安装布局
    install_exe = base / 'venv' / 'bin' / 'python'
    if install_exe.is_file():
        cwd = base / 'src'
        exe = install_exe
        dist = base / 'src' / 'astrbot' / 'dashboard' / 'dist'
        astr_root = base / 'root'
        pyhome = base / 'python'
    else:
        # 开发布局：src/astrbot + runtime/astrbot-venv
        cwd = ROOT / 'src' / 'astrbot'
        exe = ROOT / 'runtime' / 'astrbot-venv' / 'bin' / 'python'
        dist = cwd / 'astrbot' / 'dashboard' / 'dist'
        astr_root = ROOT / 'runtime' / 'astrbot'
        pyhome = None
    args = [str(exe), '-u', str(cwd / 'main.py'), '--webui-dir', str(dist)]
    env.update(
        ASTRBOT_ROOT=str(astr_root),
        ASTRBOT_DASHBOARD_INITIAL_PASSWORD=credentials['astrbot_password'],
        PYTHONUTF8='1', PYTHONUNBUFFERED='1',
    )
    if pyhome and pyhome.is_dir():
        env['PYTHONHOME'] = str(pyhome)
else:
    cwd = ROOT / 'snowluma'
    if not (cwd / 'node').is_file():
        cwd = ROOT / 'runtime' / 'snowluma'
    exe = cwd / 'node'
    args = [str(exe), str(cwd / 'index.mjs')]
    env.update(
        SNOWLUMA_WEBUI_HOST='127.0.0.1', SNOWLUMA_WEBUI_PORT='5099',
        SNOWLUMA_UPDATE_CHECK='0', SNOWLUMA_HOOK_AUTOLOAD='0',
        SNOWLUMA_WEBUI_BOOTSTRAP_PASSWORD=credentials['snowluma_password'],
    )

if not exe.is_file():
    raise SystemExit('Bundled runtime missing: ' + str(exe))

# 供守护进程使用：只打印启动规格，不实际启动
if '--print-exec' in sys.argv:
    import json as _json
    print(_json.dumps({
        'exe': str(exe), 'args': args[1:], 'cwd': str(cwd),
        'env': {k: v for k, v in env.items() if k.startswith(('ASTRBOT_', 'SNOWLUMA_', 'PYTHON'))},
    }))
    raise SystemExit(0)

logs = ROOT / 'logs'
logs.mkdir(exist_ok=True)
fd = os.open(logs / (component + '-runtime.log'), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
os.dup2(fd, 1)
os.dup2(fd, 2)
os.close(fd)
os.chdir(cwd)
os.execve(str(exe), args, env)
