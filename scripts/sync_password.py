#!/usr/bin/env python3
"""把 AstrBot 面板密码重置为 credential.json 里记录的那一份。

在面板里改过密码之后，credential.json 里的明文就失效了（面板只存哈希，无法反推），
所以这里用 credential.json 的明文重新计算哈希写回 cmd_config.json，
让「本机记录的密码」重新可用。
"""
import json
import shutil
import sys
import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'astrbot' / 'src'))

from astrbot.core.utils.auth_password import (  # noqa: E402
    hash_dashboard_password,
    hash_md5_dashboard_password,
)

CRED = ROOT / 'credential.json'
CFG = ROOT / 'astrbot' / 'root' / 'data' / 'cmd_config.json'


def main() -> None:
    if not CFG.exists():
        raise SystemExit('找不到 cmd_config.json')
    cred = json.load(CRED.open(encoding='utf-8-sig'))
    pwd = cred.get('astrbot_password') or ''
    if not pwd:
        raise SystemExit('credential.json 里没有 astrbot_password')

    cfg = json.load(CFG.open(encoding='utf-8-sig'))
    bak = CFG.with_suffix('.json.bak-pwd-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    shutil.copyfile(CFG, bak)

    dash = cfg.setdefault('dashboard', {})
    dash['username'] = cred.get('astrbot_user') or dash.get('username') or 'astrbot'
    dash['pbkdf2_password'] = hash_dashboard_password(pwd)
    dash['password'] = hash_md5_dashboard_password(pwd)
    dash['password_storage_upgraded'] = True
    dash['password_change_required'] = False

    with CFG.open('w', encoding='utf-8-sig', newline='') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=4)

    print('面板密码已重置为 credential.json 中的值（备份: %s）' % bak.name)


if __name__ == '__main__':
    main()
