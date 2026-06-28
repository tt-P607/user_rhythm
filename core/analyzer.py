"""user_rhythm 作息分析器。

纯 Python 统计分析，不调用任何 LLM。只输出事实数据，不做主观推断。
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from src.app.plugin_system.api import database_api, log_api
from src.core.models.sql_alchemy import Messages

logger = log_api.get_logger("user_rhythm.analyzer")


class RhythmAnalyzer:
    """用户作息分析器（纯统计计算，无 LLM 调用）。"""

    # 时段划分规则（小时范围）
    TIME_SLOTS = {
        "清晨": (5, 7),
        "上午": (7, 11),
        "中午": (11, 13),
        "下午": (13, 17),
        "傍晚": (17, 19),
        "晚上": (19, 22),
        "深夜": (22, 26),  # 22:00 - 02:00，跨天处理
        "凌晨": (2, 5),
    }

    def __init__(
        self,
        min_active_days: int = 7,
        min_messages: int = 200,
        sample_limit: int = 3000,
        sample_days: int = 90,
        sample_mode: str = "messages",
        threshold_mode: str = "or",
    ) -> None:
        """初始化分析器。
        
        Args:
            min_active_days: 最少活跃天数
            min_messages: 最少消息数
            sample_limit: 取样模式为 'messages' 时，最多取多少条最新消息
            sample_days: 取样模式为 'days' 时，取最近多少天的消息
            sample_mode: 取样模式 'messages' 或 'days'
            threshold_mode: 门槛模式 and/or/days/messages
        """
        self.min_active_days = min_active_days
        self.min_messages = min_messages
        self.sample_limit = sample_limit
        self.sample_days = sample_days
        self.sample_mode = sample_mode
        self.threshold_mode = threshold_mode

    async def analyze(self, person_id: str) -> dict[str, Any]:
        """分析用户的消息时间分布。
        
        Args:
            person_id: 用户 person_id
            
        Returns:
            分析结果字典，包含 available 字段和 stats 字段
        """
        # 查询消息时间戳（只取 time 字段，减少数据传输）
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.kernel.db.core.session import get_session_factory
        import time as _time

        factory = await get_session_factory()
        async with factory() as s:
            s: AsyncSession
            stmt = select(Messages.time).where(Messages.person_id == person_id)

            if self.sample_mode == "days":
                # 取最近 N 天的消息
                cutoff = _time.time() - self.sample_days * 86400
                stmt = stmt.where(Messages.time >= cutoff)
            else:
                # 取最新 N 条消息
                stmt = stmt.order_by(Messages.time.desc()).limit(self.sample_limit)

            result = await s.execute(stmt)
            rows = result.fetchall()

        if not rows:
            return {
                "available": False,
                "reason": "该用户无消息记录",
            }

        # 提取时间戳列表
        timestamps = [row[0] for row in rows]
        total_messages = len(timestamps)

        # 计算活跃天数（去重日期）
        dates = {datetime.fromtimestamp(ts).date() for ts in timestamps}
        active_days = len(dates)

        # 计算数据时间跨度
        if timestamps:
            earliest = min(timestamps)
            latest = max(timestamps)
            data_span_days = max(1, int((latest - earliest) / 86400))
        else:
            data_span_days = 0

        # 检查是否达到门槛（支持 and/or/days/messages 模式）
        threshold_mode = getattr(self, "threshold_mode", "or")
        
        days_ok = active_days >= self.min_active_days
        msgs_ok = total_messages >= self.min_messages
        
        if threshold_mode == "and":
            passed = days_ok and msgs_ok
            reason_template = f"需要同时满足 {self.min_active_days}天 且 {self.min_messages}条消息"
        elif threshold_mode == "days":
            passed = days_ok
            reason_template = f"需要至少 {self.min_active_days}天活跃"
        elif threshold_mode == "messages":
            passed = msgs_ok
            reason_template = f"需要至少 {self.min_messages}条消息"
        else:  # "or" 或其他
            passed = days_ok or msgs_ok
            reason_template = f"需要 {self.min_active_days}天活跃 或 {self.min_messages}条消息（满足其一）"
        
        if not passed:
            return {
                "available": False,
                "reason": f"数据量不足（{reason_template}）",
                "current": {
                    "active_days": active_days,
                    "total_messages": total_messages,
                },
            }

        # 统计 24 小时分布
        hour_counts = [0] * 24
        for ts in timestamps:
            dt = datetime.fromtimestamp(ts)
            hour = dt.hour
            hour_counts[hour] += 1

        # 计算各时段百分比
        slot_counts: dict[str, int] = {}
        for slot_name, (start_hour, end_hour) in self.TIME_SLOTS.items():
            count = 0
            if end_hour > 24:
                # 跨天时段（如深夜 22-02）
                count = sum(hour_counts[start_hour:24]) + sum(hour_counts[0 : end_hour - 24])
            else:
                count = sum(hour_counts[start_hour:end_hour])
            slot_counts[slot_name] = count

        slot_pct = {name: round(count / total_messages * 100, 1) for name, count in slot_counts.items()}

        # 找出 Top-3 活跃小时
        hour_pairs = [(hour, count) for hour, count in enumerate(hour_counts)]
        hour_pairs.sort(key=lambda x: x[1], reverse=True)
        peak_hours = [hour for hour, _ in hour_pairs[:3]]

        # 确定最活跃时段（占比最高）
        peak_slot = max(slot_pct.items(), key=lambda x: x[1])[0]

        return {
            "available": True,
            "stats": {
                "total_messages": total_messages,
                "active_days": active_days,
                "data_span_days": data_span_days,
                "hour_counts": hour_counts,
                "slot_pct": slot_pct,
                "peak_hours": peak_hours,
                "peak_slot": peak_slot,
            },
        }


__all__ = ["RhythmAnalyzer"]
