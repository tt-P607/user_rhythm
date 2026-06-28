"""user_rhythm 私聊 Prompt 注入器。

在私聊场景，当用户作息数据达标时，自动注入作息简报到 User Prompt 末尾。
"""

from __future__ import annotations

from typing import Any

from src.app.plugin_system.base import BaseEventHandler
from src.app.plugin_system.api import event_api, log_api

logger = log_api.get_logger("user_rhythm.injector")


class RhythmPromptInjector(BaseEventHandler):
    """作息简报注入器。
    
    订阅 on_prompt_build 事件，在私聊场景自动注入用户作息与习惯简报。
    """

    handler_name = "rhythm_prompt_injector"
    handler_description = "在私聊场景自动注入用户作息简报到 User Prompt"
    weight = 12
    intercept_message = False
    init_subscribe = ["on_prompt_build"]

    async def execute(
        self,
        event_name: str,
        params: dict[str, Any],
    ) -> tuple[event_api.EventDecision, dict[str, Any]]:
        """处理 on_prompt_build 事件。"""
        from ..configs.config import UserRhythmConfig
        from ...core.analyzer import RhythmAnalyzer
        from ...core.store import get_rhythm_store

        config = self.plugin.config
        if not isinstance(config, UserRhythmConfig):
            return event_api.EventDecision.SUCCESS, params

        if not config.plugin.enabled or not config.injection.enabled:
            return event_api.EventDecision.SUCCESS, params

        # 检查是否是目标 prompt
        prompt_name: str = params.get("name", "")
        if prompt_name not in config.injection.target_prompts:
            return event_api.EventDecision.SUCCESS, params

        values = params.get("values", {})
        
        # 获取 stream_id（KFC 直接放在 values 中）
        stream_id = str(values.get("stream_id", "")).strip()
        if not stream_id:
            return event_api.EventDecision.SUCCESS, params

        # 通过 stream_id 查询 ChatStreams，拿到 chat_type 和 person_id
        from src.app.plugin_system.api import database_api
        from src.core.models.sql_alchemy import ChatStreams

        try:
            chat_stream_row = await database_api.get_by(ChatStreams, stream_id=stream_id)
            if not chat_stream_row:
                return event_api.EventDecision.SUCCESS, params
            chat_type = str(getattr(chat_stream_row, "chat_type", "")).strip()
            person_id = str(getattr(chat_stream_row, "person_id", "")).strip()
            if not person_id:
                return event_api.EventDecision.SUCCESS, params
        except Exception as e:
            logger.debug(f"查询 chat_streams 失败: {e}")
            return event_api.EventDecision.SUCCESS, params

        # 只在私聊场景注入
        if chat_type != "private":
            return event_api.EventDecision.SUCCESS, params

        # 获取或计算快照
        store = get_rhythm_store()
        snapshot = await store.get_snapshot(person_id)

        if not snapshot:
            # 缓存不存在，实时计算
            analyzer = RhythmAnalyzer(
                min_active_days=config.threshold.min_active_days,
                min_messages=config.threshold.min_messages,
                sample_limit=config.analysis.sample_limit,
                sample_days=config.analysis.sample_days,
                sample_mode=config.analysis.sample_mode,
                threshold_mode=config.threshold.mode,
            )
            result = await analyzer.analyze(person_id)

            if not result["available"]:
                # 数据不足，不注入
                return event_api.EventDecision.SUCCESS, params

            # 保存快照
            import time
            now = time.time()
            await store.save_snapshot(person_id, result, now)
            stats = result["stats"]
        else:
            stats = {
                "total_messages": snapshot["total_messages"],
                "active_days": snapshot["active_days"],
                "data_span_days": snapshot["data_span_days"],
                "slot_pct": snapshot["slot_pct"],
                "peak_slot": snapshot["peak_slot"],
                "peak_hours": snapshot["peak_hours"],
            }

        # 获取手动记录的习惯
        habits = await store.get_habits(person_id)

        # 构建注入内容
        injected_text = self._build_injection_text(stats, habits)

        # 追加到 values["extra"]
        existing_extra = str(values.get("extra", ""))
        values["extra"] = (existing_extra + injected_text) if existing_extra else injected_text

        if config.plugin.debug_log:
            logger.info(f"已注入作息简报: person_id={person_id[:8]}...")

        return event_api.EventDecision.SUCCESS, params

    def _build_injection_text(self, stats: dict[str, Any], habits: list[dict[str, Any]]) -> str:
        """构建注入文本（自然化描述，像是对用户作息的印象）。"""
        # 格式化完整时段占比
        slot_items = sorted(stats["slot_pct"].items(), key=lambda x: x[1], reverse=True)
        slot_strs = [f"{name}{pct:.1f}%" for name, pct in slot_items]
        slot_line = "、".join(slot_strs)

        # 最活跃时段（带具体小时）
        peak_hours_str = "-".join([f"{h}点" for h in sorted(stats["peak_hours"][:2])])
        peak_line = f"{stats['peak_slot']}（集中在{peak_hours_str}）"

        # 数据来源说明
        source_line = f"基于过去{stats['data_span_days']}天的互动观察，共{stats['total_messages']}条消息"

        # 组装成自然的"印象"描述
        return f"""

<关于对方作息的印象>
你对这个人的作息印象：
· 消息时间分布：{slot_line}
· 最常活跃时段：{peak_line}
· {source_line}

你可以结合当前时间和这些作息规律，自然地理解对方现在可能处于什么状态。
</关于对方作息的印象>
"""


__all__ = ["RhythmPromptInjector"]
