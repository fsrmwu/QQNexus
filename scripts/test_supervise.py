#!/usr/bin/env python3
"""在单次运行内验证守护进程：启动 → 等健康 → 杀子进程 → 验证自动恢复。"""
import os, signal, socket, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUP = ROOT / 'scripts' / 'supervise.py'


def port_up(p, t=1.0):
    try:
        with socket.create_connection(('127.0.0.1', p), t):
            return True
    except OSError:
        return False


def wait_port(p, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if port_up(p):
            return True
        time.sleep(1)
    return False


def find_child(marker):
    out = subprocess.run(['ps', '-eo', 'pid=,args='], capture_output=True, text=True).stdout
    pids = []
    for line in out.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and marker in parts[1] and 'test_supervise' not in parts[1]:
            pids.append(int(parts[0]))
    return pids


def main():
    results = []
    def rec(name, ok, detail=''):
        results.append((name, ok, detail))
        print(('PASS ' if ok else 'FAIL ') + name + ('  ' + detail if detail else ''))

    # 先清理旧进程
    for p in find_child('supervise.py') + find_child('astrbot/main.py') + find_child('snowluma/index.mjs'):
        try: os.kill(p, 9)
        except ProcessLookupError: pass
    time.sleep(2)

    logf = open(ROOT / 'logs' / 'supervise-test.log', 'ab', buffering=0)
    sup = subprocess.Popen([sys.executable, str(SUP)], cwd=str(ROOT),
                           stdout=logf, stderr=logf, start_new_session=True)
    rec('守护进程启动', sup.poll() is None, f'pid={sup.pid}')

    ok6185 = wait_port(6185, 120)
    ok5099 = wait_port(5099, 30)
    rec('AstrBot 端口就绪', ok6185, '6185')
    rec('SnowLuma 端口就绪', ok5099, '5099')

    # 杀掉 AstrBot
    ab = find_child('astrbot/main.py')
    rec('找到 AstrBot 进程', len(ab) > 0, str(ab))
    if ab:
        for p in ab:
            try: os.kill(p, 9)
            except ProcessLookupError: pass
        print('  已强杀 AstrBot', ab)
        # 等它恢复（退避最多 30s + 启动 ~40s）
        recovered = False
        end = time.time() + 150
        time.sleep(8)
        while time.time() < end:
            if port_up(6185):
                recovered = True
                break
            time.sleep(3)
        rec('AstrBot 被杀后自动恢复', recovered)

    # 守护自身还活着
    rec('守护进程仍存活', sup.poll() is None)

    # 收尾
    try:
        os.killpg(os.getpgid(sup.pid), 15)
    except Exception:
        pass
    time.sleep(3)
    for p in find_child('astrbot/main.py') + find_child('snowluma/index.mjs') + find_child('supervise.py'):
        try: os.kill(p, 9)
        except ProcessLookupError: pass

    print('\n' + '='*50)
    pas = sum(1 for _, ok, _ in results if ok)
    print(f'{len(results)} 项，通过 {pas}')

asyncio_none = None
if __name__ == '__main__':
    main()
