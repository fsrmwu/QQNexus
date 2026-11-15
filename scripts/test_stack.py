#!/usr/bin/env python3
"""端到端验证 run_stack.sh 启动链：守护接管 + 服务就绪 + 崩溃恢复。"""
import os, signal, socket, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def ps():
    return subprocess.run(['ps', '-eo', 'pid=,args='], capture_output=True, text=True).stdout


def pids(marker):
    out = []
    for line in ps().splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and marker in parts[1] and 'test_stack' not in parts[1]:
            try: out.append(int(parts[0]))
            except ValueError: pass
    return out


def port_up(p, t=1.0):
    try:
        with socket.create_connection(('127.0.0.1', p), t):
            return True
    except OSError:
        return False


def kill_all():
    for m in ('supervise.py', 'logrotate.py', 'astrbot/main.py', 'snowluma/index.mjs'):
        for p in pids(m):
            try: os.kill(p, 9)
            except ProcessLookupError: pass


def main():
    res = []
    def rec(name, ok, detail=''):
        res.append(ok)
        print(('PASS ' if ok else 'FAIL ') + name + ('  ' + detail if detail else ''), flush=True)

    kill_all()
    time.sleep(2)

    # 直接调用 run_stack.sh（前台，但脚本内部 setsid 拉起子进程）
    env = os.environ.copy()
    p = subprocess.Popen(['bash', str(ROOT / 'scripts' / 'run_stack.sh')],
                         cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, env=env)

    # 等 run_stack 打印出两个面板地址（内部已 wait_port）
    out_lines = []
    end = time.time() + 240
    ready = False
    while time.time() < end:
        line = p.stdout.readline()
        if not line:
            if p.poll() is not None:
                break
            time.sleep(0.3)
            continue
        out_lines.append(line.rstrip())
        if 'SnowLuma:' in line:
            ready = True
            break
    rec('run_stack 打印面板地址', ready, out_lines[-1] if out_lines else '')

    rec('AstrBot 端口 6185', port_up(6185))
    rec('OneBot 端口 6199', port_up(6199))
    rec('SnowLuma 端口 5099', port_up(5099))

    sup = pids('supervise.py')
    lr = pids('logrotate.py')
    rec('守护进程在运行', len(sup) > 0, str(sup))
    rec('日志轮转在运行', len(lr) > 0, str(lr))

    # 崩溃恢复：杀 AstrBot，看守护是否拉起
    ab = pids('astrbot/main.py')
    rec('找到 AstrBot 进程', len(ab) > 0, str(ab))
    if ab:
        for x in ab:
            try: os.kill(x, 9)
            except ProcessLookupError: pass
        print('  已强杀 AstrBot', ab, flush=True)
        time.sleep(8)
        recovered = False
        end = time.time() + 150
        while time.time() < end:
            if port_up(6185):
                recovered = True
                break
            time.sleep(3)
        rec('AstrBot 崩溃后自动恢复', recovered)

    rec('守护进程仍存活', len(pids('supervise.py')) > 0)

    # 清理
    kill_all()
    try:
        p.kill()
    except Exception:
        pass

    print('\n' + '='*46)
    print(f'{len(res)} 项，通过 {sum(res)}')


if __name__ == '__main__':
    main()
