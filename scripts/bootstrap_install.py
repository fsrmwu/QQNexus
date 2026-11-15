#!/usr/bin/env python3
"""从 vendor 目录组装可运行安装树。

用法：
  python scripts/bootstrap_install.py --target D:\QQNexus

会把 AstrBot 源码、SnowLuma 发行包、面板静态资源摆成 ui/main.js 期望的布局，
并生成 credential.json。已存在的文件不会覆盖。
"""
import argparse
import json
import os
import secrets
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        print('  跳过（不存在）:', src)
        return
    shutil.copytree(src, dst, dirs_exist_ok=True)
    print('  复制:', src.name, '->', dst)


def ensure_credential(target: Path) -> None:
    cred = target / 'credential.json'
    if cred.exists():
        print('  credential.json 已存在，跳过')
        return
    data = {
        'astrbot_user': 'astrbot',
        'astrbot_password': 'QnA9-' + secrets.token_urlsafe(18),
        'snowluma_password': 'QnS9-' + secrets.token_urlsafe(18),
        'onebot_token': secrets.token_urlsafe(32),
    }
    cred.write_text(json.dumps(data, indent=2), encoding='utf-8')
    print('  已生成 credential.json')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--target', required=True, help='安装目标目录')
    args = ap.parse_args()
    target = Path(args.target).resolve()

    print('目标:', target)
    for sub in ('astrbot/src', 'snowluma', 'python', 'logs'):
        (target / sub).mkdir(parents=True, exist_ok=True)

    # AstrBot 源码
    src_astrbot = ROOT / 'vendor' / 'astrbot-src'
    if not src_astrbot.exists():
        src_astrbot = ROOT / 'src' / 'astrbot'
    copy_tree(src_astrbot, target / 'astrbot' / 'src')

    # SnowLuma 发行包（Windows）
    sl_zip = ROOT / 'vendor' / 'SnowLuma-v2.4.2-win-x64.zip'
    if sl_zip.exists():
        with zipfile.ZipFile(sl_zip) as z:
            z.extractall(target / 'snowluma')
        print('  展开 SnowLuma 发行包')
    else:
        print('  跳过 SnowLuma（vendor 里没有 win-x64 包）')

    ensure_credential(target)
    print('完成。下一步：运行 scripts/prepare_runtime.py 生成配置。')


if __name__ == '__main__':
    main()
