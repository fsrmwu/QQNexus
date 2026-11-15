#!/usr/bin/env python3
"""最终验收：全新安装 → 启动 → 服务就绪 → 崩溃恢复 → 统计文件生成。"""
import os, shutil, signal, socket, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALLER = ROOT / 'dist' / 'QQNexus-Setup-linux-arm64.run'
TARGET = Path('/tmp/qqn-accept')


def ps():
    return subprocess.run(['ps', '-eo', 'pid=,args='], capture_output=True, text=True).stdout


def pids(marker):
    out = []
    for line in ps().splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and marker in parts[1] and 'test_install' not in parts[1] \
                and str(TARGET) in parts[1]:
            try: out.append(int(parts[0]))
            except ValueError: pass
    return out


def kill_all():
    for m in ('supervise.py', 'logrotate.py', 'astrbot/main.py', 'snowluma/index.mjs'):
        for p in pids(m):
            try: os.kill(p, 9)
            except ProcessLookupError: pass


def port_up(p, t=1.0):
    try:
        with socket.create_connection(('127.0.0.1', p), t):
            return True
    except OSError:
        return False


def main():
    res = []
    def rec(name, ok, detail=''):
        res.append(ok)
        print(('PASS ' if ok else 'FAIL ') + name + ('  ' + detail if detail else ''), flush=True)

    kill_all()
    if TARGET.exists():
        shutil.rmtree(TARGET, ignore_errors=True)
    time.sleep(2)

    # 1. 全新安装
    env = os.environ.copy()
    env['QQNEXUS_HOME'] = str(TARGET)
    r = subprocess.run(['bash', str(INSTALLER)], capture_output=True, text=True, env=env, timeout=600)
    rec('安装脚本执行成功', r.returncode == 0, (r.stdout or '').strip().splitlines()[-1] if r.stdout else r.stderr[:80])
    rec('安装目录生成', (TARGET / 'run_stack.sh').exists() and (TARGET / 'credential.json').exists())
    rec('统计插件随包分发', (TARGET / 'astrbot/src/astrbot/builtin_stars/qqnexus_stats/main.py').exists())
    rec('守护/轮转脚本就位', (TARGET / 'supervise.py').exists() and (TARGET / 'logrotate.py').exists())
    rec('_paths.py 就位', (TARGET / '_paths.py').exists())

    # 2. 启动
    logf = open('/tmp/qqn-accept.log', 'wb', buffering=0)
    boot = subprocess.Popen(['bash', str(TARGET / 'run_stack.sh')], cwd=str(TARGET),
                            stdout=logf, stderr=logf, start_new_session=True, env=env)

    # 等面板就绪
    end = time.time() + 240
    ok_astr = ok_snow = ok_ob = False
    while time.time() < end:
        ok_astr = port_up(6185)
        ok_snow = port_up(5099)
        ok_ob = port_up(6199)
        if ok_astr and ok_snow:
            break
        time.sleep(4)
    rec('AstrBot 面板 6185 就绪', ok_astr)
    rec('SnowLuma 面板 5099 就绪', ok_snow)
    rec('OneBot 端口 6199 就绪', ok_ob)
    rec('守护进程在运行', len(pids('supervise.py')) > 0)
    rec('日志轮转在运行', len(pids('logrotate.py')) > 0)

    # 3. 崩溃恢复
    ab = pids('astrbot/main.py')
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

    # 4. 统计文件
    stats = TARGET / 'astrbot' / 'root' / 'data' / 'qqnexus_stats.json'
    rec('统计文件已创建', stats.exists(), str(stats))

    kill_all()
    try: boot.kill()
    except Exception: pass

    print('\n' + '='*50)
    print(f'{len(res)} 项，通过 {sum(res)}')


if __name__ == '__main__':
    main()
