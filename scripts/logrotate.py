#!/usr/bin/env python3
"""日志轮转：按大小切分，保留最近 N 份，压缩旧的。

用法：
  python3 logrotate.py            # 处理一次（可放进 cron / 定时任务）
  python3 logrotate.py --watch    # 常驻，每 30 分钟检查一次
"""
import gzip
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # 项目根
LOGS = ROOT / 'logs'

MAX_BYTES = 8 * 1024 * 1024      # 单文件超过 8MB 就切
KEEP = 5                          # 每种日志保留 5 份历史
INTERVAL = 30 * 60                # watch 模式检查间隔（秒）

# 这些前缀的日志参与轮转；其余（如安装日志）原样保留
MANAGED = ('astrbot-runtime', 'snowluma-runtime', 'astrbot.out', 'astrbot.err',
           'snowluma.out', 'snowluma.err', 'run')


def rotate_one(path: Path) -> bool:
    """切分单个日志。返回是否发生了轮转。"""
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return False
    if size < MAX_BYTES:
        return False

    stamp = time.strftime('%Y%m%d-%H%M%S')
    archived = path.with_name(f'{path.name}.{stamp}.gz')

    # 先 gzip 压缩旧内容，再清空原文件（保持文件句柄有效）
    try:
        with path.open('rb') as src, gzip.open(archived, 'wb', compresslevel=6) as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
        # 原地清空，避免进程需要重启才能继续写
        with path.open('wb'):
            pass
    except Exception as e:
        print(f'[logrotate] {path.name} 轮转失败: {e}', file=sys.stderr)
        return False

    print(f'[logrotate] 已归档 {archived.name} ({size // 1024} KB)')
    prune(path)
    return True


def prune(path: Path) -> None:
    """删除超出 KEEP 的旧归档。"""
    pattern = f'{path.name}.*.gz'
    archives = sorted(path.parent.glob(pattern), key=lambda p: p.name)
    for old in archives[:-KEEP]:
        try:
            old.unlink()
            print(f'[logrotate] 清理旧归档 {old.name}')
        except OSError:
            pass


def run_once() -> int:
    if not LOGS.is_dir():
        return 0
    count = 0
    for f in LOGS.iterdir():
        if not f.is_file() or f.suffix == '.gz':
            continue
        if any(f.name.startswith(p) for p in MANAGED):
            if rotate_one(f):
                count += 1
    return count


def main() -> None:
    if '--watch' in sys.argv:
        print(f'[logrotate] 常驻模式，每 {INTERVAL // 60} 分钟检查一次')
        while True:
            run_once()
            time.sleep(INTERVAL)
    else:
        n = run_once()
        print(f'[logrotate] 完成，轮转 {n} 个文件')


if __name__ == '__main__':
    main()
