"""user_rhythm 插件存储层。

管理插件独立数据库的初始化和读写操作。
"""

from __future__ import annotations

import json
import time
from typing import Any, ClassVar

from src.app.plugin_system.api import storage_api, log_api

logger = log_api.get_logger("user_rhythm.store")


class RhythmStore:
    """作息分布快照与习惯记录的存储管理器（单例）。"""

    _instance: ClassVar[RhythmStore | None] = None

    def __init__(self) -> None:
        """初始化存储管理器。"""
        from .models import Base, RhythmSnapshotModel, UserHabitModel

        self._db_path = "data/user_rhythm/rhythm.db"
        self._db = storage_api.PluginDatabase(self._db_path, [RhythmSnapshotModel, UserHabitModel])
        self._initialized = False

    @classmethod
    def get_instance(cls) -> RhythmStore:
        """获取单例实例。"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def initialize(self) -> None:
        """初始化数据库（建表）。"""
        if self._initialized:
            return
        await self._db.initialize()
        self._initialized = True
        logger.info(f"插件数据库已初始化: {self._db_path}")

    async def close(self) -> None:
        """关闭数据库连接。"""
        await self._db.close()
        self._initialized = False

    # ========== 快照管理 ==========

    async def get_snapshot(self, person_id: str) -> dict[str, Any] | None:
        """获取指定用户的快照。
        
        Returns:
            快照字典，不存在时返回 None
        """
        from .models import RhythmSnapshotModel

        async with self._db.session() as s:
            from sqlalchemy import select
            stmt = select(RhythmSnapshotModel).where(RhythmSnapshotModel.person_id == person_id)
            result = await s.execute(stmt)
            row = result.scalar_one_or_none()

        if row is None:
            return None

        return {
            "person_id": row.person_id,
            "total_messages": row.total_messages,
            "active_days": row.active_days,
            "data_span_days": row.data_span_days,
            "hour_counts": json.loads(row.hour_counts_json),
            "slot_pct": json.loads(row.slot_pct_json),
            "peak_hours": json.loads(row.peak_hours_json),
            "peak_slot": row.peak_slot,
            "computed_at": row.computed_at,
        }

    async def save_snapshot(self, person_id: str, data: dict[str, Any], computed_at: float) -> None:
        """保存或更新快照。
        
        Args:
            person_id: 用户 ID
            data: analyzer.analyze() 返回的数据
            computed_at: 计算时间戳
        """
        from .models import RhythmSnapshotModel
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        stmt = sqlite_insert(RhythmSnapshotModel).values(
            person_id=person_id,
            total_messages=data["stats"]["total_messages"],
            active_days=data["stats"]["active_days"],
            data_span_days=data["stats"]["data_span_days"],
            hour_counts_json=json.dumps(data["stats"]["hour_counts"]),
            slot_pct_json=json.dumps(data["stats"]["slot_pct"]),
            peak_hours_json=json.dumps(data["stats"]["peak_hours"]),
            peak_slot=data["stats"]["peak_slot"],
            computed_at=computed_at,
        ).on_conflict_do_update(
            index_elements=["person_id"],
            set_=dict(
                total_messages=data["stats"]["total_messages"],
                active_days=data["stats"]["active_days"],
                data_span_days=data["stats"]["data_span_days"],
                hour_counts_json=json.dumps(data["stats"]["hour_counts"]),
                slot_pct_json=json.dumps(data["stats"]["slot_pct"]),
                peak_hours_json=json.dumps(data["stats"]["peak_hours"]),
                peak_slot=data["stats"]["peak_slot"],
                computed_at=computed_at,
            ),
        )

        async with self._db.session() as s:
            await s.execute(stmt)

    async def get_stale_snapshots(self, now: float, interval_seconds: float) -> list[dict[str, Any]]:
        """获取所有过期快照。
        
        Args:
            now: 当前时间戳
            interval_seconds: 过期间隔（秒）
            
        Returns:
            过期快照列表
        """
        from .models import RhythmSnapshotModel

        cutoff = now - interval_seconds
        from sqlalchemy import select

        async with self._db.session() as s:
            stmt = select(RhythmSnapshotModel).where(RhythmSnapshotModel.computed_at < cutoff)
            result = await s.execute(stmt)
            rows = result.scalars().all()

        return [{"person_id": row.person_id, "computed_at": row.computed_at} for row in rows]

    async def update_snapshot_timestamp(self, person_id: str, computed_at: float) -> None:
        """仅更新快照的 computed_at 字段（推迟下次检查）。"""
        from .models import RhythmSnapshotModel
        from sqlalchemy import update

        async with self._db.session() as s:
            stmt = update(RhythmSnapshotModel).where(
                RhythmSnapshotModel.person_id == person_id
            ).values(computed_at=computed_at)
            await s.execute(stmt)

    # ========== 习惯管理 ==========

    async def get_habits(self, person_id: str) -> list[dict[str, Any]]:
        """获取指定用户的所有习惯记录。"""
        from .models import UserHabitModel

        from sqlalchemy import select

        async with self._db.session() as s:
            stmt = (
                select(UserHabitModel)
                .where(UserHabitModel.person_id == person_id)
                .order_by(UserHabitModel.created_at.desc())
            )
            result = await s.execute(stmt)
            rows = result.scalars().all()

        return [
            {
                "id": row.id,
                "habit_category": row.habit_category,
                "habit_desc": row.habit_desc,
                "cron_like_time": row.cron_like_time,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
            for row in rows
        ]

    async def add_habit(
        self,
        person_id: str,
        habit_desc: str,
        habit_category: str = "general",
        cron_like_time: str | None = None,
    ) -> None:
        """添加新的习惯记录。"""
        from .models import UserHabitModel

        now = time.time()
        habit = UserHabitModel(
            person_id=person_id,
            habit_category=habit_category,
            habit_desc=habit_desc,
            cron_like_time=cron_like_time,
            created_at=now,
            updated_at=now,
        )

        async with self._db.session() as s:
            s.add(habit)
            await s.flush()


def get_rhythm_store() -> RhythmStore:
    """获取存储管理器单例（便捷函数）。"""
    return RhythmStore.get_instance()


__all__ = ["RhythmStore", "get_rhythm_store"]
