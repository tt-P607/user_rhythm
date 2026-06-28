"""user_rhythm 习惯记录工具。

允许 LLM 主动记录用户明确陈述的时间习惯或生活规律。
"""

from __future__ import annotations

from typing import Annotated

from src.app.plugin_system.base import BaseTool
from src.app.plugin_system.api import log_api

logger = log_api.get_logger("user_rhythm.record_tool")

_TOOL_DESCRIPTION = """记录用户明确陈述的时间习惯或生活规律。

当用户在对话中告知某些时间相关的习惯（如"我每天早上7点半去跑步"或"我周二晚上都有吉他课"）时，
你可以调用此工具主动记录下来。这些记录与统计分析是分开的，具有更高的可靠性。
"""


class RecordUserHabitTool(BaseTool):
    """记录用户习惯的工具类。"""

    tool_name = "record_user_habit"
    tool_description = _TOOL_DESCRIPTION

    async def execute(
        self,
        target_user: Annotated[str, "目标用户的昵称、备注名或 user_id"],
        habit_desc: Annotated[str, "习惯的精炼描述（例如：'每天中午12点到1点会午睡半小时'）"],
        habit_category: Annotated[str, "习惯类型：schedule(日程)/preference(偏好)/rhythm(作息)/general"] = "general",
        cron_like_time: Annotated[str | None, "关联的时间规律（例如：'12:00-13:00' 或 '周二晚上'）"] = None,
    ) -> tuple[bool, str]:
        """执行记录。
        
        Args:
            target_user: 目标用户标识
            habit_desc: 习惯描述
            habit_category: 习惯类别
            cron_like_time: 时间规律（可选）
            
        Returns:
            (True, 成功信息) 或 (False, 错误信息)
        """
        from ...core.store import get_rhythm_store
        from ...core.user_resolver import resolve_person_id

        # 解析用户 person_id（跨平台模糊匹配）
        person_id = await resolve_person_id(target_user)

        if not person_id:
            return False, f"未找到匹配的用户: {target_user}"

        # 参数清理
        habit_desc = habit_desc[:100].strip()
        if not habit_desc:
            return False, "习惯描述不能为空"

        if habit_category not in ["schedule", "preference", "rhythm", "general"]:
            habit_category = "general"

        if cron_like_time:
            cron_like_time = cron_like_time[:50].strip()

        # 保存到数据库
        store = get_rhythm_store()
        try:
            await store.add_habit(person_id, habit_desc, habit_category, cron_like_time)
            logger.info(f"成功记录习惯: person_id={person_id[:8]}..., desc={habit_desc}")
            return True, f"已成功记录该习惯：{habit_desc}"
        except Exception as e:
            logger.error(f"记录习惯失败: {e}")
            return False, f"记录习惯失败: {e}"


__all__ = ["RecordUserHabitTool"]
