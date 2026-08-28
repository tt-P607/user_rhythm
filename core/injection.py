"""user_rhythm 作息简报注入逻辑。

集中管理注入文本构建与流私有 reminder 同步，供三条路径复用：
- ``on_prompt_build`` 事件中的流侧冷启动兜底；
- 快照定时重建完成后的 person 侧主动刷新；
- 记录习惯成功后的 person 侧主动刷新。

同步采用"内容比对写入"：待写内容与现有 reminder 一致时跳过写入与日志，
保证多次调用间不会产生冗余写操作。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from src.app.plugin_system.api import database_api, log_api
from src.app.plugin_system.api.prompt_api import (
    add_stream_reminder,
    delete_stream_reminder,
    get_stream_reminder,
)
from src.core.prompt import SystemReminderInsertType

if TYPE_CHECKING:
    from ..components.configs.config import UserRhythmConfig
    from .store import RhythmStore

logger = log_api.get_logger("user_rhythm.injection")

# 作息简报写入的流私有 bucket 与 reminder 名称
REMINDER_BUCKET = "actor"
REMINDER_NAME = "user_rhythm_impression"


def build_injection_text(stats: dict[str, Any], habits: list[dict[str, Any]]) -> str:
    """构建注入文本（自然化描述，像是对用户作息的印象）。

    Args:
        stats: 作息统计快照数据
        habits: 手动记录的习惯列表

    Returns:
        str: 组装后的注入文本
    """
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


async def collect_rhythm_stats(
    person_id: str,
    *,
    config: "UserRhythmConfig",
    store: "RhythmStore",
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """获取指定用户的作息统计与习惯数据。

    优先读取快照；快照不存在时实时计算并保存。

    Args:
        person_id: 用户 ID
        config: 插件配置（提供分析器参数）
        store: 插件存储管理器

    Returns:
        tuple[dict | None, list[dict]]: ``(stats, habits)``；
        ``stats`` 为 ``None`` 表示数据未达标。
    """
    from .analyzer import RhythmAnalyzer

    snapshot = await store.get_snapshot(person_id)
    if snapshot:
        stats: dict[str, Any] = {
            "total_messages": snapshot["total_messages"],
            "active_days": snapshot["active_days"],
            "data_span_days": snapshot["data_span_days"],
            "slot_pct": snapshot["slot_pct"],
            "peak_slot": snapshot["peak_slot"],
            "peak_hours": snapshot["peak_hours"],
        }
        return stats, await store.get_habits(person_id)

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
        return None, []

    await store.save_snapshot(person_id, result, time.time())
    return result["stats"], await store.get_habits(person_id)


async def sync_rhythm_reminder(
    *,
    stream_id: str,
    stats: dict[str, Any] | None,
    habits: list[dict[str, Any]],
    debug_log: bool = False,
) -> bool:
    """同步单条聊天流的作息简报 reminder（内容比对写入）。

    Args:
        stream_id: 聊天流 ID
        stats: 作息统计数据，``None`` 表示数据不足，将移除既有 reminder
        habits: 手动记录的习惯列表
        debug_log: 是否在内容变化时输出 INFO 日志

    Returns:
        bool: 是否发生了 reminder 变更
    """
    existing = get_stream_reminder(
        stream_id=stream_id,
        bucket=REMINDER_BUCKET,
        names=[REMINDER_NAME],
    )

    if stats is None:
        if not existing:
            return False
        delete_stream_reminder(stream_id, REMINDER_BUCKET, REMINDER_NAME)
        if debug_log:
            logger.info(f"已移除作息简报: stream={stream_id[:8]}...（数据不再满足条件）")
        return True

    text = build_injection_text(stats, habits)
    if existing == text:
        return False

    add_stream_reminder(
        stream_id=stream_id,
        bucket=REMINDER_BUCKET,
        name=REMINDER_NAME,
        content=text,
        insert_type=SystemReminderInsertType.DYNAMIC,
    )
    if debug_log:
        logger.info(f"已注入作息简报: stream={stream_id[:8]}...")
    return True


async def refresh_person_reminders(
    person_id: str,
    *,
    config: "UserRhythmConfig",
    store: "RhythmStore",
) -> int:
    """内容变化后刷新该用户全部私聊流的作息简报（推刷新）。

    Args:
        person_id: 用户 ID
        config: 插件配置
        store: 插件存储管理器

    Returns:
        int: 发生变更的流数量
    """
    from src.core.models.sql_alchemy import ChatStreams

    stats, habits = await collect_rhythm_stats(person_id, config=config, store=store)
    debug_log = config.plugin.debug_log

    stream_rows = await database_api.filter_query(
        ChatStreams,
        person_id=person_id,
        chat_type="private",
    )
    changed_count = 0
    for row in stream_rows:
        stream_id = str(row.stream_id or "").strip()
        if not stream_id:
            continue
        changed = await sync_rhythm_reminder(
            stream_id=stream_id,
            stats=stats,
            habits=habits,
            debug_log=debug_log,
        )
        if changed:
            changed_count += 1
    return changed_count


__all__ = [
    "REMINDER_BUCKET",
    "REMINDER_NAME",
    "build_injection_text",
    "collect_rhythm_stats",
    "refresh_person_reminders",
    "sync_rhythm_reminder",
]
