#!/usr/bin/env python3
"""用 AstrBot 的 umo_aliases / umo_senders 回填 qqnexus_stats.json 里缺失的群名与人名。

统计插件只在新消息到达时才写名字，历史条目会一直是空。这个脚本把已经存在于
AstrBot 数据库里的名字补齐，界面就不必显示纯号码了。
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / 'astrbot' / 'root' / 'data' / 'data_v4.db'
STATS = ROOT / 'astrbot' / 'root' / 'data' / 'qqnexus_stats.json'


def norm(s) -> str:
    return (s or '').strip()


def main() -> None:
    if not DB.exists() or not STATS.exists():
        print(json.dumps({'ok': False, 'msg': 'db 或 stats 不存在'}, ensure_ascii=False))
        return

    stats = json.loads(STATS.read_text(encoding='utf-8-sig'))
    groups = stats.get('groups') or {}
    privates = stats.get('privates') or {}

    con = sqlite3.connect('file:%s?mode=ro' % DB, uri=True, timeout=3)
    con.row_factory = sqlite3.Row

    # 群名：umo 形如 <platform>:GroupMessage:<group_id>
    group_names = {}
    try:
        for r in con.execute("SELECT umo, auto_name FROM umo_aliases"):
            umo = norm(r['umo'])
            name = norm(r['auto_name'])
            if not name or ':GroupMessage:' not in umo:
                continue
            gid = umo.rsplit(':', 1)[-1]
            if gid:
                group_names.setdefault(gid, name)
    except Exception:
        pass

    # 人名：优先 umo_senders 里该会话最近一次的 sender_name
    sender_names = {}
    try:
        for r in con.execute(
            "SELECT umo, sender_id, sender_name FROM umo_senders ORDER BY id DESC"
        ):
            sid = norm(r['sender_id'])
            name = norm(r['sender_name'])
            if sid and name and name != sid:
                sender_names.setdefault(sid, name)
    except Exception:
        pass
    con.close()

    filled_g = filled_p = 0
    for gid, info in groups.items():
        if not norm(info.get('name')) and gid in group_names:
            info['name'] = group_names[gid]
            filled_g += 1
    for uid, info in privates.items():
        if not norm(info.get('name')) and uid in sender_names:
            info['name'] = sender_names[uid]
            filled_p += 1

    if filled_g or filled_p:
        stats['groups'] = groups
        stats['privates'] = privates
        tmp = STATS.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(STATS)

    print(json.dumps({
        'ok': True, 'groups_filled': filled_g, 'privates_filled': filled_p,
        'group_names_known': len(group_names),
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
