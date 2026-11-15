"""统一的安装根目录探测，三个脚本共用。

安装根必须满足：位于 scripts/ 之外，且含下列任一标志目录。
"""
from pathlib import Path

MARKERS = ('src', 'vendor', 'runtime', 'astrbot', 'snowluma', 'python')


def project_root() -> Path:
    """返回真正的项目/安装根目录。

    只认 scripts/ 的上一级，且必须同时具备 credential.json 与标志目录，
    避免把 /tmp 这类碰巧含有同名目录的父级误判为根。
    """
    here = Path(__file__).resolve().parent          # .../scripts
    parent = here.parent
    has_cred = (parent / 'credential.json').exists()
    has_marker = any((parent / d).is_dir() for d in MARKERS)
    if has_cred and has_marker:
        return parent
    # 脚本被平铺在安装根时（无 scripts 子目录）
    if (here / 'credential.json').exists() and any((here / d).is_dir() for d in MARKERS):
        return here
    return parent


def script_dir() -> Path:
    """返回脚本所在目录（scripts/ 或安装根，取决于是否平铺）。"""
    here = Path(__file__).resolve().parent
    return here
