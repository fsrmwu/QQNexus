#!/usr/bin/env python3
"""Build a single offline installer. Streams into tar.gz so peak memory stays flat.

Layout inside the payload:
  QQNexus/credential.json, run_stack.sh, stop_stack.sh, run_component.py, prepare_runtime.py
  QQNexus/snowluma/           SnowLuma complete runtime (bundled node)
  QQNexus/astrbot/src/        AstrBot source tree
  QQNexus/astrbot/venv/       AstrBot python environment
  QQNexus/astrbot/root/       AstrBot data root (loopback config)
  QQNexus/astrbot/dashboard.zip
"""
import os, tarfile, pathlib, hashlib, json, io, shutil

R = pathlib.Path('/workspace/QQNexus')
OUT = R / 'dist' / 'QQNexus-Setup-linux-arm64.run'
TGZ = R / 'dist' / 'QQNexus-linux-arm64.tar.gz'
OUT.parent.mkdir(parents=True, exist_ok=True)

INSTALLER = b'''#!/bin/sh
# QQNexus offline installer. Contains all runtimes; never downloads anything.
set -e
LINE_END=$(awk '/^__PAYLOAD__$/ { print NR + 1; exit }' "$0")
WORK=$(mktemp -d 2>/dev/null || echo /tmp/qqnexus-install)
mkdir -p "$WORK" && cd "$WORK"
tail -n +"$LINE_END" "$0" | tar -xzf -
TARGET="${QQNEXUS_HOME:-$HOME/.local/share/QQNexus}"
echo "Installing to: $TARGET"
mkdir -p "$TARGET"
cp -a ./QQNexus/. "$TARGET/"
chmod +x "$TARGET"/*.sh
mkdir -p "$HOME/.local/bin"
printf '#!/bin/sh\ncd "$(dirname "$0")" >/dev/null 2>&1 || true\nexec bash "%s/run_stack.sh" "$@"\n' "$TARGET" > "$HOME/.local/bin/qqnexus-start"
printf '#!/bin/sh\nexec bash "%s/stop_stack.sh" "$@"\n' "$TARGET" > "$HOME/.local/bin/qqnexus-stop"
printf '#!/bin/sh\nbash "%s/stop_stack.sh" || true\nrm -rf "%s" "$HOME/.local/bin/qqnexus-start" "$HOME/.local/bin/qqnexus-stop"\necho uninstalled\n' "$TARGET" "$TARGET" > "$TARGET/uninstall.sh"
chmod +x "$HOME/.local/bin/qqnexus-start" "$HOME/.local/bin/qqnexus-stop" "$TARGET/uninstall.sh"
cd / && rm -rf "$WORK"
echo "Done.  start: qqnexus-start   stop: qqnexus-stop   remove: $TARGET/uninstall.sh"
exit 0
__PAYLOAD__
'''

# 打包时排除：缓存、日志、数据库会话数据、node_modules
SKIP_DIRS = {'__pycache__', '.git', 'node_modules', '.cache', 'temp', 'logs'}

def norm(path: pathlib.Path, arc: str):
    return tarfile.TarInfo(arc)

def add_file(tf, path: pathlib.Path, arc: str):
    ti = tf.gettarinfo(str(path), arcname=arc)
    ti.uid = ti.gid = 0; ti.uname = ti.gname = 'root'
    mode = path.stat().st_mode
    if mode & 0o100:
        ti.mode = 0o755
    with path.open('rb') as f:
        tf.addfile(ti, f)

def add_tree(tf, root: pathlib.Path, arc_prefix: str, skip_names=()):
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        rel_dir = pathlib.Path(dirpath).relative_to(root)
        arc_dir = (pathlib.Path(arc_prefix) / rel_dir).as_posix()
        tf.addfile(tarfile.TarInfo(arc_dir) if False else _dirinfo(tf, arc_dir))
        for name in filenames:
            if name in skip_names:
                continue
            p = pathlib.Path(dirpath) / name
            if p.is_symlink() or not p.is_file():
                continue
            add_file(tf, p, (pathlib.Path(arc_prefix) / rel_dir / name).as_posix())
            count += 1
    return count

def _dirinfo(tf, arc):
    ti = tarfile.TarInfo(arc if arc.endswith('/') else arc + '/')
    ti.type = tarfile.DIRTYPE; ti.mode = 0o755; ti.uid = ti.gid = 0; ti.uname = ti.gname = 'root'
    return ti

def main():
    with tarfile.open(TGZ, 'w:gz', compresslevel=3, format=tarfile.GNU_FORMAT) as tf:
        total = 0
        # 1) 顶层脚本与凭据
        for name in ('credential.json', 'run_stack.sh', 'stop_stack.sh',
                     'run_component.py', 'prepare_runtime.py',
                     'supervise.py', 'logrotate.py', '_paths.py', 'token_stats.py',
                     'apply_provider.py'):
            add_file(tf, R / name if (R / name).exists() else R / 'scripts' / name,
                     'QQNexus/' + name)
            total += 1
        # 2) SnowLuma 完整运行时
        total += add_tree(tf, R / 'runtime' / 'snowluma', 'QQNexus/snowluma')
        print('snowluma staged')
        # 3) AstrBot 源码
        total += add_tree(tf, R / 'src' / 'astrbot', 'QQNexus/astrbot/src')
        print('astrbot source staged')
        # 4) AstrBot 依赖环境
        total += add_tree(tf, R / 'runtime' / 'astrbot-venv', 'QQNexus/astrbot/venv')
        total += add_tree(tf, R / 'runtime' / 'python-standalone', 'QQNexus/astrbot/python')
        print('astrbot venv staged')
        # 5) AstrBot 数据根（保留配置，清掉运行期数据库与日志）
        root = R / 'runtime' / 'astrbot'
        total += add_tree(tf, root, 'QQNexus/astrbot/root')
        print('astrbot data root staged')
        # 6) 面板静态资源 zip
        zip_path = R / 'vendor' / 'AstrBot-v4.29.4-dashboard.zip'
        if zip_path.exists():
            add_file(tf, zip_path, 'QQNexus/astrbot/dashboard.zip'); total += 1
        print('files:', total)

    digest = hashlib.sha256()
    with TGZ.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            digest.update(chunk)
    with OUT.open('wb') as out:
        out.write(INSTALLER)
        with TGZ.open('rb') as src:
            shutil.copyfileobj(src, out, 1 << 20)
    os.chmod(OUT, 0o755)
    (R / 'dist' / 'SHA256SUMS').write_text(
        f'{digest.hexdigest()}  {TGZ.name}\n')
    print('payload sha256:', digest.hexdigest())
    print('installer:', OUT, round(OUT.stat().st_size / 1048576, 1), 'MB')

if __name__ == '__main__':
    main()
