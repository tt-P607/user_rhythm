"""user_rhythm 用户作息与习惯分析插件。

通过统计用户历史消息的时间分布，分析作息规律；支持 LLM 主动记录和查询用户习惯；
在私聊场景被动注入作息简报到 Prompt。插件本身不调用任何 LLM，所有分析均为纯代码实现。
"""

from __future__ import annotations

from src.app.plugin_system.base import BasePlugin, register_plugin
from src.app.plugin_system.api.log_api import get_logger

from .components.configs.config import UserRhythmConfig
from .components.tools.query_rhythm import QueryUserRhythmTool
from .components.tools.record_habit import RecordUserHabitTool
from .components.events.prompt_injector import RhythmPromptInjector

logger = get_logger("user_rhythm")


@register_plugin
class UserRhythmPlugin(BasePlugin):
    """用户作息与习惯分析插件。
    
    基于消息时间分布统计用户作息规律，支持 LLM 查询/记录用户习惯，
    私聊场景自动注入作息简报到 Prompt。
    """

    plugin_name = "user_rhythm"
    plugin_description = "用户作息与习惯分析插件"
    plugin_version = "1.0.0"

    configs: list[type] = [UserRhythmConfig]

    def get_components(self) -> list[type]:
        """获取插件包含的所有组件类。"""
        config = self.config
        if isinstance(config, UserRhythmConfig) and not config.plugin.enabled:
            return []
        return [
            QueryUserRhythmTool,
            RecordUserHabitTool,
            RhythmPromptInjector,
        ]

    async def on_plugin_loaded(self) -> None:
        """插件加载钩子：初始化数据库和调度器。"""
        logger.info("user_rhythm 插件加载开始")

        config = self.config
        if not isinstance(config, UserRhythmConfig):
            config = UserRhythmConfig()

        if not config.plugin.enabled:
            logger.warning("插件已禁用，跳过初始化")
            return

        # 初始化插件数据库
        from .core.store import get_rhythm_store
        store = get_rhythm_store()
        await store.initialize()
        logger.info("插件数据库初始化完成")

        # 启动定时重建任务
        from src.app.plugin_system.api import log_api
        from src.kernel.scheduler import get_unified_scheduler, TriggerType

        scheduler = get_unified_scheduler()
        
        # 检查调度器是否已启动，未启动则不创建任务
        try:
            await scheduler.create_schedule(
                callback=self._rebuild_stale_snapshots,
                trigger_type=TriggerType.TIME,
                trigger_config={
                    "interval": config.rebuild.interval_hours * 3600  # 转换为秒
                },
                is_recurring=True,
                task_name="user_rhythm:rebuild_snapshots",
                force_overwrite=True,
            )
            logger.info(f"定时重建任务已启动，间隔 {config.rebuild.interval_hours} 小时")
        except RuntimeError as e:
            logger.warning(f"调度器未启动，跳过定时任务创建: {e}")

        logger.info("user_rhythm 插件加载完成")

    async def on_plugin_unloaded(self) -> None:
        """插件卸载钩子：停止调度器并关闭数据库连接。"""
        logger.info("user_rhythm 插件卸载中")

        # 停止定时任务
        try:
            from src.kernel.scheduler import get_unified_scheduler
            scheduler = get_unified_scheduler()
            await scheduler.remove_schedule_by_name("user_rhythm:rebuild_snapshots")
            logger.info("定时重建任务已停止")
        except Exception as e:
            logger.warning(f"停止定时任务失败: {e}")

        # 关闭数据库
        try:
            from .core.store import get_rhythm_store
            store = get_rhythm_store()
            await store.close()
            logger.info("插件数据库连接已关闭")
        except Exception as e:
            logger.warning(f"关闭数据库失败: {e}")

        logger.info("user_rhythm 插件卸载完成")

    async def _rebuild_stale_snapshots(self) -> None:
        """后台任务：重建过期的快照（仅当用户有新消息时）。"""
        from .core.analyzer import RhythmAnalyzer
        from .core.store import get_rhythm_store
        from src.app.plugin_system.api import database_api
        from src.core.models.sql_alchemy import Messages
        from sqlalchemy import select
        from src.kernel.db.core.session import get_session_factory
        import time

        config = self.config
        if not isinstance(config, UserRhythmConfig):
            return

        store = get_rhythm_store()
        analyzer = RhythmAnalyzer(
            min_active_days=config.threshold.min_active_days,
            min_messages=config.threshold.min_messages,
            sample_limit=config.analysis.sample_limit,
            sample_days=config.analysis.sample_days,
            sample_mode=config.analysis.sample_mode,
            threshold_mode=config.threshold.mode,
        )

        # 获取所有过期快照
        interval_seconds = config.rebuild.interval_hours * 3600
        now = time.time()
        stale_snapshots = await store.get_stale_snapshots(now, interval_seconds)

        logger.info(f"定时重建任务开始，发现 {len(stale_snapshots)} 个过期快照")

        factory = await get_session_factory()
        rebuilt_count = 0
        skipped_count = 0

        for snapshot in stale_snapshots:
            person_id = snapshot["person_id"]
            computed_at = snapshot["computed_at"]

            try:
                # 检查该用户在上次计算后是否有新消息
                async with factory() as s:
                    stmt = (
                        select(Messages.time)
                        .where(
                            Messages.person_id == person_id,
                            Messages.time > computed_at,
                        )
                        .limit(1)
                    )
                    result = await s.execute(stmt)
                    has_new = result.first() is not None

                if not has_new:
                    # 无新消息，只推迟 computed_at
                    await store.update_snapshot_timestamp(person_id, now)
                    skipped_count += 1
                    continue

                # 有新消息，重新计算
                analysis = await analyzer.analyze(person_id)
                if analysis["available"]:
                    await store.save_snapshot(person_id, analysis, now)
                    rebuilt_count += 1
                else:
                    await store.update_snapshot_timestamp(person_id, now)
                    skipped_count += 1

            except Exception as e:
                logger.error(f"重建快照失败 person_id={person_id[:8]}...: {e}")
                skipped_count += 1

        logger.info(f"定时重建任务完成：重建 {rebuilt_count}，跳过 {skipped_count}")
