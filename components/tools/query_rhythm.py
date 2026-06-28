"""user_rhythm 查询工具。

允许 LLM 查询某个用户的作息分布数据和手动记录的习惯。
"""

from __future__ import annotations

from typing import Annotated, Any

from src.app.plugin_system.base import BaseTool
from src.app.plugin_system.api import log_api

logger = log_api.get_logger("user_rhythm.query_tool")

_TOOL_DESCRIPTION = """查询指定用户的消息时间分布数据及手动记录的习惯。

该工具返回用户的消息时间分布统计数据（如最活跃时段、各时段占比等）以及手动记录的习惯列表。
其中 available 字段表示数据是否充足（需至少7天且200条消息）。
当 available=false 时，统计数据参考价值极其有限，你在表达时应保持不确定性。
所有数据均为客观统计，如何解读（是否认为是"夜猫子"）由你基于完整数据自行判断。
"""


class QueryUserRhythmTool(BaseTool):
    """查询用户作息分布与习惯的工具类。"""

    tool_name = "query_user_rhythm"
    tool_description = _TOOL_DESCRIPTION

    async def execute(
        self,
        target_user: Annotated[str, "目标用户的昵称、备注名或 user_id（支持模糊匹配）"],
    ) -> tuple[bool, dict[str, Any]]:
        """执行查询。
        
        Args:
            target_user: 目标用户标识（昵称/备注名/user_id）
            
        Returns:
            (True, 数据字典) 或 (False, 错误信息字典)
        """
        from ..configs.config import UserRhythmConfig
        from ...core.analyzer import RhythmAnalyzer
        from ...core.store import get_rhythm_store
        from ...core.user_resolver import resolve_person_id
        from src.app.plugin_system.api import database_api
        from src.core.models.sql_alchemy import PersonInfo

        config = self.plugin.config
        if not isinstance(config, UserRhythmConfig):
            config = UserRhythmConfig()

        # 解析用户 person_id（跨平台模糊匹配）
        person_id = await resolve_person_id(target_user)

        if not person_id:
            return False, {
                "error": "未找到匹配的用户",
                "query": target_user,
            }

        # 获取用户昵称（用于展示）
        try:
            person = await database_api.get_by(PersonInfo, person_id=person_id)
            nickname = str(getattr(person, "nickname", None) or target_user)
        except Exception:
            nickname = target_user

        store = get_rhythm_store()

        # 1. 尝试从缓存获取快照
        snapshot = await store.get_snapshot(person_id)

        if snapshot:
            logger.info(f"从缓存加载快照: person_id={person_id[:8]}...")
            stats = {
                "total_messages": snapshot["total_messages"],
                "active_days": snapshot["active_days"],
                "data_span_days": snapshot["data_span_days"],
                "hour_counts": snapshot["hour_counts"],
                "slot_pct": snapshot["slot_pct"],
                "peak_hours": snapshot["peak_hours"],
                "peak_slot": snapshot["peak_slot"],
            }
            available = True
        else:
            # 2. 缓存不存在，实时计算
            logger.info(f"缓存未命中，实时计算: person_id={person_id[:8]}...")
            analyzer = RhythmAnalyzer(
                min_active_days=config.threshold.min_active_days,
                min_messages=config.threshold.min_messages,
                sample_limit=config.analysis.sample_limit,
                sample_days=config.analysis.sample_days,
                sample_mode=config.analysis.sample_mode,
                threshold_mode=config.threshold.mode,
            )
            result = await analyzer.analyze(person_id)

            if result["available"]:
                # 计算成功，保存快照
                import time
                now = time.time()
                await store.save_snapshot(person_id, result, now)
                stats = result["stats"]
                available = True
            else:
                # 数据不足
                return True, {
                    "available": False,
                    "reason": result["reason"],
                    "current": result.get("current", {}),
                    "user": nickname,
                }

        # 3. 获取手动记录的习惯
        habits = await store.get_habits(person_id)

        return True, {
            "available": available,
            "user": nickname,
            "stats": stats,
            "habits": habits,
            "note": "数据量充足" if available else "数据量不足",
        }


__all__ = ["QueryUserRhythmTool"]
