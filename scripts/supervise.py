#!/usr/bin/env python3
"""进程守护：监控 AstrBot 与 SnowLuma，异常退出后按退避策略自动重启。

用法：
  python3 supervise.py            # 前台守护（Ctrl-C 停止）
  python3 supervise.py --daemon   # 后台常驻

设计要点：
  - 独立子进程启动，不依赖启动它的终端（终端关闭仍在跑）
  - 崩溃后按 3s / 5s / 10s / 20s / 30s 退避，稳定运行 60s 后重置
  - 连续快速失败超过 5 次则暂停该组件 5 分钟，避免疯狂重启
  - 收到 SIGTERM 时优雅停止所有子进程
"""
import json
import os
import signal
import subprocess
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
from _paths import project_root, script_dir
import time
from pathlib import Path

ROOT = project_root()
LOGS = ROOT / 'logs'
SCRIPT_DIR = script_dir()

LOGS = ROOT / 'logs'
# 脚本可能平铺在根目录，也可能在 scripts/ 下
SCRIPT_DIR = ROOT if (ROOT / 'run_component.py').exists() else ROOT / 'scripts'

COMPONENTS = [
    {'name': 'astrbot', 'port': 6185, 'script': SCRIPT_DIR / 'run_component.py', 'arg': 'astrbot'},
    {'name': 'snowluma', 'port': 5099, 'script': SCRIPT_DIR / 'run_component.py', 'arg': 'snowluma'},
]

BACKOFF = [3, 5, 10, 20, 30]
STABLE_RESET = 60           # 稳定运行超过 60s 视为恢复正常
MAX_FAST_FAILS = 5          # 连续快速失败上限
COOLDOWN = 300              # 触发上限后冷却时间
TICK = 5

procs = {}
state = {}


def log(msg: str) -> None:
    line = f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] [supervise] {msg}'
    print(line, flush=True)
    try:
        LOGS.mkdir(exist_ok=True)
        with (LOGS / 'supervise.log').open('a', encoding='utf-8') as f:
            f.write(line + '\n')
    except OSError:
        pass


def port_open(port: int, timeout: float = 1.0) -> bool:
    import socket
    try:
        with socket.create_connection(('127.0.0.1', port), timeout):
            return True
    except OSError:
        return False


def start(comp: dict) -> None:
    name = comp['name']
    # 用 run_component.py 的 --print-exec 拿到真实启动命令与工作目录，
    # 避免 os.execve 造成 pid 丢失（守护要能感知真实子进程）。
    try:
        info = subprocess.run(
            [sys.executable, str(comp['script']), comp['arg'], '--print-exec'],
            cwd=str(ROOT), capture_output=True, text=True, timeout=15,
        )
        spec = json.loads(info.stdout.strip().splitlines()[-1])
    except Exception as e:
        log(f'{name} 获取启动参数失败: {e} | rc={getattr(info,"returncode","?") if "info" in dir() else "?"} stderr={(info.stderr[:200] if "info" in dir() and getattr(info,"stderr",None) else "")!r}')
        return
    logs = ROOT / 'logs'
    logs.mkdir(exist_ok=True)
    out = open(logs / f'{name}-runtime.log', 'ab', buffering=0)
    p = subprocess.Popen(
        [spec['exe']] + spec['args'],
        cwd=spec['cwd'], env=spec['env'],
        stdout=out, stderr=out,
        start_new_session=True,
    )
    procs[name] = p
    state.setdefault(name, {'fails': 0, 'last_start': 0, 'cooldown_until': 0})
    state[name]['last_start'] = time.time()
    log(f'启动 {name} (pid={p.pid})')


def stop(comp: dict) -> None:
    name = comp['name']
    p = procs.pop(name, None)
    if not p or p.poll() is not None:
        return
    try:
        p.terminate()
        p.wait(timeout=8)
    except subprocess.TimeoutExpired:
        try:
            p.kill()
        except OSError:
            pass
    log(f'停止 {name}')


def check_and_restart() -> None:
    now = time.time()
    for comp in COMPONENTS:
        name = comp['name']
        st = state.setdefault(name, {'fails': 0, 'last_start': 0, 'cooldown_until': 0})
        p = procs.get(name)

        if st['cooldown_until'] > now:
            continue

        # 进程不存在或已退出
        if p is None or p.poll() is not None:
            if p is not None:
                code = p.returncode
                ran = now - st['last_start']
                if ran >= STABLE_RESET:
                    st['fails'] = 0
                else:
                    st['fails'] += 1
                log(f'{name} 已退出 (code={code}, 运行 {int(ran)}s, 连续失败 {st["fails"]})')
                procs.pop(name, None)
            else:
                st['fails'] += 1

            if st['fails'] > MAX_FAST_FAILS:
                st['cooldown_until'] = now + COOLDOWN
                st['fails'] = 0
                log(f'{name} 连续失败过多，暂停 {COOLDOWN // 60} 分钟')
                continue

            delay = BACKOFF[min(max(st['fails'] - 1, 0), len(BACKOFF) - 1)]
            log(f'{name} 将在 {delay}s 后重启')
            time.sleep(delay)
            start(comp)
            continue

        # 进程活着但端口没起来（启动阶段容忍）
        ran = now - st['last_start']
        if ran > 120 and not port_open(comp['port']):
            log(f'{name} 进程存活但端口 {comp["port"]} 无响应，重启')
            stop(comp)
            st['last_start'] = 0
            continue

        # 稳定运行
        if ran >= STABLE_RESET and st['fails']:
            st['fails'] = 0


def on_signal(signum, frame):
    log(f'收到信号 {signum}，正在停止全部子进程')
    for comp in COMPONENTS:
        stop(comp)
    sys.exit(0)


def main() -> None:
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    LOGS.mkdir(exist_ok=True)
    log('守护进程启动')
    for comp in COMPONENTS:
        start(comp)
    while True:
        check_and_restart()
        time.sleep(TICK)


if __name__ == '__main__':
    main()
