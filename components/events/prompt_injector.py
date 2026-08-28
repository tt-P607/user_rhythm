"""user_rhythm 私聊 Prompt 注入器。

在私聊场景，当用户作息数据达标时，自动注入作息简报到 User Prompt 末尾。
"""

from __future__ import annotations

import time
from typing import Any

from src.app.plugin_system.api import event_api, log_api
from src.app.plugin_system.base import BaseEventHandler

logger = log_api.get_logger("user_rhythm.injector")


class RhythmPromptInjector(BaseEventHandler):
    """作息简报注入器。

    冷启动兜底：对目标模板命中的聊天流，在 reminder 缺失时补齐注入；
    reminder 已存在或处于冷却期时立即返回，不产生查库开销。
    """

    name = "rhythm_prompt_injector"
    description = "在私聊场景自动注入用户作息简报到 User Prompt"
    weight = 12
    intercept_message = False
    init_subscribe = ["on_prompt_build"]

    def __init__(self, plugin: Any) -> None:
        """初始化注入器。

        Args:
            plugin: 所属插件实例
        """
        super().__init__(plugin)
        # 冷却表：stream_id -> 冷却结束时刻（monotonic 秒），仅含冷却中的流
        self._cooldown_until: dict[str, float] = {}

    async def execute(
        self,
        event_name: str,
        params: dict[str, Any],
    ) -> tuple[event_api.EventDecision, dict[str, Any]]:
        """处理 on_prompt_build 事件，执行冷启动兜底同步。"""
        from src.app.plugin_system.api.prompt_api import get_stream_reminder

        from ...core.injection import REMINDER_BUCKET, REMINDER_NAME
        from ..configs.config import UserRhythmConfig

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

        # 热路径：reminder 存在即视为内容最新（变化源会推刷新），直接返回
        if get_stream_reminder(stream_id, REMINDER_BUCKET, [REMINDER_NAME]):
            return event_api.EventDecision.SUCCESS, params

        # 冷路径：reminder 缺失；冷却期内不重复尝试。
        # 失败冷却复用快照重建间隔，不额外引入可调项
        now = time.monotonic()
        wake_at = self._cooldown_until.get(stream_id)
        if wake_at is not None and now < wake_at:
            return event_api.EventDecision.SUCCESS, params
        self._cooldown_until[stream_id] = now + config.rebuild.interval_hours * 3600

        # 冷却已登记，执行一次冷启动同步（查流身份 + reminder 写入/移除）
        await self._sync_stream(stream_id, config)
        return event_api.EventDecision.SUCCESS, params

    async def _sync_stream(self, stream_id: str, config: Any) -> None:
        """查流身份并执行一次 reminder 同步（仅私聊）。

        Args:
            stream_id: 聊天流 ID
            config: 插件配置
        """
        from src.app.plugin_system.api import database_api
        from src.core.models.sql_alchemy import ChatStreams

        from ...core.injection import collect_rhythm_stats, sync_rhythm_reminder
        from ...core.store import get_rhythm_store

        try:
            chat_stream_row = await database_api.get_by(
                ChatStreams, stream_id=stream_id
            )
            if not chat_stream_row:
                return
            chat_type = str(chat_stream_row.chat_type or "").strip()
            person_id = str(chat_stream_row.person_id or "").strip()
            if not person_id:
                return
        except Exception as e:
            logger.debug(f"查询 chat_streams 失败: {e}")
            return

        # 只在私聊场景同步
        if chat_type != "private":
            return

        store = get_rhythm_store()
        stats, habits = await collect_rhythm_stats(
            person_id, config=config, store=store
        )
        await sync_rhythm_reminder(
            stream_id=stream_id,
            stats=stats,
            habits=habits,
            debug_log=bool(config.plugin.debug_log),
        )


__all__ = ["RhythmPromptInjector"]
