#!/usr/bin/env python3
"""把启动器里配置的模型与人设同步写入 AstrBot v4.29+。

用法：
  python apply_provider.py --id deepseek --api-base https://api.deepseek.com/v1 \
      --model deepseek-chat --key sk-xxx [--system-prompt "你是..."]

v4.29 的配置分两层：
  provider_sources[]  连接信息（type / key[] / api_base / timeout）
  provider[]          模型条目（provider_source_id 指向上面的 id / model）
只改动自己管理的条目，不覆盖用户手动添加的其他 provider/persona。
"""
import argparse
import json
import shutil
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PERSONA_ID = 'qqnexus'            # 启动器管理的人设 id，固定复用
SOURCE_ID = 'qqnexus_source'      # provider_sources 条目 id
PROVIDER_ID = 'qqnexus_model'     # provider 条目 id


def data_dir() -> Path:
    for rel in ('astrbot/root/data', 'runtime/astrbot/data', 'data'):
        p = ROOT / rel
        if p.is_dir():
            return p
    raise SystemExit('找不到 AstrBot 数据目录')


def load_config(path: Path) -> dict:
    with path.open(encoding='utf-8-sig') as f:
        return json.load(f)


def save_config(path: Path, cfg: dict) -> None:
    bak = path.with_suffix('.json.bak')
    if not bak.exists():
        shutil.copy2(path, bak)
    tmp = path.with_suffix('.json.tmp')
    # AstrBot 用 utf-8-sig 读写，这里保持同样编码，避免下次读回时出错
    with tmp.open('w', encoding='utf-8-sig', newline='') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=4)
    tmp.replace(path)


def upsert(items: list, key: str, value: str, patch: dict) -> list:
    """按 key==value 更新，否则追加。"""
    for it in items:
        if isinstance(it, dict) and it.get(key) == value:
            it.update(patch)
            return items
    items.append(dict(patch, **{key: value}))
    return items


def apply_provider(d: Path, api_base: str, model: str, key: str) -> str:
    cfg_path = d / 'cmd_config.json'
    if not cfg_path.exists():
        return 'cmd_config.json 不存在'
    cfg = load_config(cfg_path)

    # 第一层：连接信息
    sources = cfg.get('provider_sources') or []
    upsert(sources, 'id', SOURCE_ID, {
        'provider': 'openai',
        'type': 'openai_chat_completion',
        'provider_type': 'chat_completion',
        'key': [key] if key else [],
        'api_base': api_base.rstrip('/'),
        'timeout': 120,
        'proxy': '',
        'custom_headers': {},
        'enable': True,
    })
    cfg['provider_sources'] = sources

    # 第二层：模型条目，指向上面那条连接
    providers = cfg.get('provider') or []
    upsert(providers, 'id', PROVIDER_ID, {
        'enable': True,
        'provider_source_id': SOURCE_ID,
        'model': model,
        'modalities': ['text', 'image', 'tool_use'],
        'custom_extra_body': {},
        'max_context_tokens': 1000000,
    })
    cfg['provider'] = providers

    # 设为默认使用的 provider
    ps = cfg.get('provider_settings') or {}
    ps['provider_id'] = PROVIDER_ID
    cfg['provider_settings'] = ps

    save_config(cfg_path, cfg)
    return 'provider 已写入：%s @ %s' % (model, api_base)


def apply_persona(d: Path, system_prompt: str) -> str:
    if not system_prompt or not system_prompt.strip():
        return '人设为空，跳过'
    db = d / 'data_v4.db'
    if not db.exists():
        return 'data_v4.db 不存在'
    try:
        con = sqlite3.connect(str(db), timeout=5)
        now = int(time.time())
        row = con.execute(
            'SELECT persona_id FROM personas WHERE persona_id=?', (PERSONA_ID,)
        ).fetchone()
        if row:
            con.execute(
                'UPDATE personas SET system_prompt=?, updated_at=? WHERE persona_id=?',
                (system_prompt, now, PERSONA_ID),
            )
        else:
            con.execute(
                '''INSERT INTO personas
                   (created_at, updated_at, persona_id, system_prompt,
                    begin_dialogs, tools, skills, custom_error_message, folder_id, sort_order)
                   VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (now, now, PERSONA_ID, system_prompt, '[]', 'null', 'null', '', 'null', 0),
            )
        con.commit()
        con.close()
        return '人设已写入 personas 表'
    except Exception as e:
        return '人设写入失败：%s' % e


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--id', default='default')
    ap.add_argument('--api-base', required=True)
    ap.add_argument('--model', required=True)
    ap.add_argument('--key', default='')
    ap.add_argument('--system-prompt', default='')
    args = ap.parse_args()

    d = data_dir()
    r1 = apply_provider(d, args.api_base, args.model, args.key)
    r2 = apply_persona(d, args.system_prompt)
    print(json.dumps({'ok': True, 'provider': r1, 'persona': r2}, ensure_ascii=False))


if __name__ == '__main__':
    main()
