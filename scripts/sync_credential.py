#!/usr/bin/env python3
"""让 AstrBot 面板密码与 credential.json 保持一致（客户端为准）。

AstrBot 面板只保存 pbkdf2 哈希，无法反推出明文；因此「客户端同步 AstrBot」
的正确做法是：
  1. 用 credential.json 里的密码尝试登录面板
  2. 登录成功  -> 两边一致，无需动作
  3. 登录失败  -> 说明面板密码被改过，用 credential.json 的密码把面板改回来
                  （走 /api/auth/account，需要已登录 token；登录不了就直接改配置哈希）

输出 JSON，便于主进程判断。
"""
import base64
import hashlib
import json
import shutil
import sys
import urllib.error
import urllib.request
import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CRED = ROOT / 'credential.json'
CFG = ROOT / 'astrbot' / 'root' / 'data' / 'cmd_config.json'
BASE = 'http://127.0.0.1:6185'


def http(method, path, payload=None, token=None, timeout=10):
    url = BASE + path
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode('utf-8') or '{}')
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode('utf-8') or '{}')
        except Exception:
            body = {}
        return e.code, body
    except Exception as e:
        return 0, {'error': str(e)}


def pbkdf2_matches(raw, stored):
    try:
        alg, it, salt, h = stored.split('$')
        calc = base64.b64encode(
            hashlib.pbkdf2_hmac('sha256', raw.encode(), salt.encode(), int(it))
        ).decode()
        return calc == h
    except Exception:
        return None


def write_hash(pwd):
    sys.path.insert(0, str(ROOT / 'astrbot' / 'src'))
    from astrbot.core.utils.auth_password import (
        hash_dashboard_password,
        hash_md5_dashboard_password,
    )
    cfg = json.load(CFG.open(encoding='utf-8-sig'))
    bak = CFG.with_suffix('.json.bak-sync-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    shutil.copyfile(CFG, bak)
    dash = cfg.setdefault('dashboard', {})
    dash['pbkdf2_password'] = hash_dashboard_password(pwd)
    dash['password'] = hash_md5_dashboard_password(pwd)
    dash['password_storage_upgraded'] = True
    dash['password_change_required'] = False
    with CFG.open('w', encoding='utf-8-sig', newline='') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=4)
    return bak.name


def main():
    cred = json.load(CRED.open(encoding='utf-8-sig'))
    user = cred.get('astrbot_user') or 'astrbot'
    pwd = cred.get('astrbot_password') or ''
    if not pwd:
        print(json.dumps({'ok': False, 'state': 'no-password'}, ensure_ascii=False))
        return

    status, body = http('POST', '/api/auth/login', {'username': user, 'password': pwd})
    if status == 200 and (body.get('data') or {}).get('token'):
        print(json.dumps({'ok': True, 'state': 'in-sync'}, ensure_ascii=False))
        return

    if status == 0:
        print(json.dumps({'ok': False, 'state': 'panel-down'}, ensure_ascii=False))
        return

    # 登录失败：面板密码已被改过，用客户端保存的密码把面板改回来
    cfg = json.load(CFG.open(encoding='utf-8-sig'))
    stored = (cfg.get('dashboard') or {}).get('pbkdf2_password') or ''
    if stored and pbkdf2_matches(pwd, stored):
        # 哈希其实一致，可能是用户名变了
        new_user = (cfg.get('dashboard') or {}).get('username') or user
        status2, body2 = http('POST', '/api/auth/login', {'username': new_user, 'password': pwd})
        if status2 == 200:
            cred['astrbot_user'] = new_user
            CRED.write_text(json.dumps(cred, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'ok': True, 'state': 'user-fixed', 'user': new_user}, ensure_ascii=False))
            return

    bak = write_hash(pwd)
    print(json.dumps({'ok': True, 'state': 'panel-reset', 'backup': bak}, ensure_ascii=False))


if __name__ == '__main__':
    main()
