"""user_rhythm 插件数据模型。

定义插件独立数据库的表结构。
"""

from __future__ import annotations

import time

from sqlalchemy import Float, Index, Integer, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Mapped, mapped_column

# 独立 Base，与核心数据库隔离
Base = declarative_base()


class RhythmSnapshotModel(Base):
    """用户消息时间分布快照表。
    
    存储已计算的作息分布数据，带缓存时效。
    """

    __tablename__ = "rhythm_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    person_id: Mapped[str] = mapped_column(
        Text, nullable=False, unique=True, index=True, comment="用户全局 person_id（哈希值）"
    )

    # 门槛指标
    total_messages: Mapped[int] = mapped_column(Integer, nullable=False, comment="统计的消息总数")
    active_days: Mapped[int] = mapped_column(Integer, nullable=False, comment="活跃天数")
    data_span_days: Mapped[int] = mapped_column(Integer, nullable=False, comment="数据时间跨度（天）")

    # 分布数据（JSON 序列化存储）
    hour_counts_json: Mapped[str] = mapped_column(
        Text, nullable=False, comment="24小时计数数组 JSON, e.g. [0,0,1,2,...,12,10,...]"
    )
    slot_pct_json: Mapped[str] = mapped_column(
        Text, nullable=False, comment="各时段消息占比 JSON, e.g. {上午:48.9, 下午:21.3,...}"
    )
    peak_hours_json: Mapped[str] = mapped_column(
        Text, nullable=False, comment="Top-3活跃小时 JSON, e.g. [9,10,8]"
    )
    peak_slot: Mapped[str] = mapped_column(Text, nullable=False, comment="最活跃时段名称，规则映射")

    # 缓存管理
    computed_at: Mapped[float] = mapped_column(
        Float, nullable=False, comment="快照计算时间戳，用于判断是否需要更新"
    )

    __table_args__ = (Index("idx_rhythm_snapshots_person", "person_id"),)


class UserHabitModel(Base):
    """用户习惯手工记录表。
    
    存储 LLM 在对话中感知到的用户时间规律或习惯。
    """

    __tablename__ = "user_habits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    person_id: Mapped[str] = mapped_column(
        Text, nullable=False, index=True, comment="用户全局 person_id"
    )
    habit_category: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="general",
        comment="习惯类型: schedule(日程)/preference(偏好)/rhythm(作息)/general",
    )
    habit_desc: Mapped[str] = mapped_column(Text, nullable=False, comment="习惯描述")
    cron_like_time: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="关联时间规律，如 '07:30' 或 '周二晚上'"
    )
    created_at: Mapped[float] = mapped_column(
        Float, nullable=False, default=time.time, comment="创建时间戳"
    )
    updated_at: Mapped[float] = mapped_column(
        Float, nullable=False, default=time.time, comment="最后更新时间戳"
    )

    __table_args__ = (
        Index("idx_user_habits_person", "person_id"),
        Index("idx_user_habits_category", "habit_category"),
    )


__all__ = [
    "Base",
    "RhythmSnapshotModel",
    "UserHabitModel",
]
