"""QQNexus 统计插件：消息量、活跃群聊与私信人数。

只读事件流，不拦截、不回复、不外发。
数据写入 <ASTRBOT_ROOT>/data/qqnexus_stats.json，供启动器面板读取。
"""
import json
import time
from pathlib import Path

from astrbot.api import logger, star
from astrbot.api.event import AstrMessageEvent, filter


class Main(star.Star):
    def __init__(self, context: star.Context) -> None:
        self.context = context
        # AstrBot 的数据目录：<ASTRBOT_ROOT>/data
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path
            data_dir = Path(get_astrbot_data_path())
        except Exception:
            data_dir = Path.cwd() / "data"
        self.data_file = data_dir / "qqnexus_stats.json"
        self.stats = self._load()

    # ---------- 持久化 ----------
    def _load(self) -> dict:
        base = {
            "total": 0,
            "group_total": 0,
            "private_total": 0,
            "sessions": 0,
            "groups": {},      # group_id -> {count, last_seen, name}
            "privates": {},    # user_id  -> {count, last_seen, name}
            "started_at": int(time.time()),
            "updated_at": int(time.time()),
        }
        try:
            if self.data_file.exists():
                d = json.loads(self.data_file.read_text(encoding="utf-8"))
                if isinstance(d, dict):
                    base.update(d)
        except Exception as e:
            logger.warning(f"[qqnexus_stats] 读取失败: {e}")
        return base

    def _save(self) -> None:
        try:
            self.data_file.parent.mkdir(parents=True, exist_ok=True)
            self.stats["updated_at"] = int(time.time())
            self.stats["sessions"] = (
                len(self.stats.get("groups", {})) + len(self.stats.get("privates", {}))
            )
            tmp = self.data_file.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(self.stats, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(self.data_file)
        except Exception as e:
            logger.warning(f"[qqnexus_stats] 写入失败: {e}")

    # ---------- 取名字 ----------
    @staticmethod
    def _group_name(event: AstrMessageEvent) -> str:
        """群名在 AstrBot 里存在 message_obj.group.group_name，不在 event 上。"""
        try:
            msg = getattr(event, "message_obj", None)
            grp = getattr(msg, "group", None) if msg else None
            name = getattr(grp, "group_name", "") if grp else ""
            if name:
                return str(name)
        except Exception:
            pass
        # 兜底：部分适配器把群名直接挂在事件对象上
        for attr in ("group_name", "groupName"):
            try:
                v = getattr(event, attr, "")
                if v:
                    return str(v)
            except Exception:
                pass
        return ""

    @staticmethod
    def _sender_name(event: AstrMessageEvent) -> str:
        try:
            msg = getattr(event, "message_obj", None)
            snd = getattr(msg, "sender", None) if msg else None
            name = getattr(snd, "name", "") if snd else ""
            if name and name != "N/A":
                return str(name)
        except Exception:
            pass
        try:
            v = event.get_sender_name()
            if v and v != "N/A":
                return str(v)
        except Exception:
            pass
        return ""

    # ---------- 统计钩子 ----------
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        """统计所有消息；不产出回复。"""
        try:
            now = int(time.time())
            self.stats["total"] += 1

            gid = ""
            try:
                gid = str(event.get_group_id() or "")
            except Exception:
                gid = ""

            if gid:
                self.stats["group_total"] += 1
                g = self.stats["groups"].setdefault(
                    gid, {"count": 0, "last_seen": now, "name": ""}
                )
                g["count"] += 1
                g["last_seen"] = now
                if not g.get("name"):
                    name = self._group_name(event)
                    if name:
                        g["name"] = name
            else:
                self.stats["private_total"] += 1
                uid = ""
                try:
                    uid = str(event.get_sender_id() or "")
                except Exception:
                    uid = ""
                if uid:
                    p = self.stats["privates"].setdefault(
                        uid, {"count": 0, "last_seen": now, "name": ""}
                    )
                    p["count"] += 1
                    p["last_seen"] = now
                    if not p.get("name"):
                        name = self._sender_name(event)
                        if name:
                            p["name"] = name

            # 每 5 条落盘一次，降低 IO
            if self.stats["total"] % 5 == 0:
                self._save()
        except Exception as e:
            logger.debug(f"[qqnexus_stats] 统计异常: {e}")

    async def terminate(self):
        self._save()
