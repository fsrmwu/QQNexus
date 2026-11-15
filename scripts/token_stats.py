#!/usr/bin/env python3
"""读取 AstrBot 的 Token 用量（provider_stats 表），输出 JSON。

用法：python3 token_stats.py [db路径]
只读打开（mode=ro），不干扰 AstrBot 正常写入。
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def find_db():
    for rel in (
        'astrbot/root/data/data_v4.db',      # 安装布局
        'runtime/astrbot/data/data_v4.db',   # 开发布局
        'data/data_v4.db',
    ):
        p = ROOT / rel
        if p.exists():
            return p
    return None


def empty():
    return {'input': 0, 'cached': 0, 'output': 0, 'total': 0,
            'calls': 0, 'model_count': 0, 'by_model': []}


def main():
    db = Path(sys.argv[1]) if len(sys.argv) > 1 else find_db()
    if not db or not db.exists():
        print(json.dumps(empty()))
        return
    try:
        con = sqlite3.connect('file:%s?mode=ro' % db, uri=True, timeout=3)
        con.row_factory = sqlite3.Row
        agg = con.execute("""
            SELECT
              COALESCE(SUM(token_input_other),0)  AS input,
              COALESCE(SUM(token_input_cached),0) AS cached,
              COALESCE(SUM(token_output),0)       AS output,
              COUNT(*)                            AS calls,
              COUNT(DISTINCT provider_model)      AS models
            FROM provider_stats
        """).fetchone()
        rows = con.execute("""
            SELECT provider_model AS model,
                   COALESCE(SUM(token_input_other+token_input_cached+token_output),0) AS total,
                   COUNT(*) AS calls
            FROM provider_stats
            GROUP BY provider_model
            ORDER BY total DESC
            LIMIT 8
        """).fetchall()
        con.close()

        inp = int(agg['input'] or 0)
        cac = int(agg['cached'] or 0)
        out = int(agg['output'] or 0)
        print(json.dumps({
            'input': inp, 'cached': cac, 'output': out,
            'total': inp + cac + out,
            'calls': int(agg['calls'] or 0),
            'model_count': int(agg['models'] or 0),
            'by_model': [
                {'model': r['model'] or '(未知)', 'total': int(r['total'] or 0),
                 'calls': int(r['calls'] or 0)}
                for r in rows
            ],
        }, ensure_ascii=False))
    except Exception as e:
        print(json.dumps(dict(empty(), error=str(e)), ensure_ascii=False))


if __name__ == '__main__':
    main()
