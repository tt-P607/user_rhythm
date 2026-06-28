"""user_rhythm 内部用户解析工具。

提供跨平台的用户关键词模糊搜索能力（不限定 platform）。
"""

from __future__ import annotations

from src.app.plugin_system.api import database_api, log_api
from src.core.models.sql_alchemy import PersonInfo

logger = log_api.get_logger("user_rhythm.user_resolver")


async def resolve_person_id(keyword: str) -> str | None:
    """根据关键词解析用户 person_id（跨平台模糊匹配）。

    解析规则：
    1. 尝试将 keyword 视为 user_id（通过数字判断），在 person_info 中精确匹配
    2. 按昵称/群名片精确匹配（全平台）
    3. 若精确匹配失败，尝试模糊包含匹配；仅在唯一命中时返回
    4. 多命中时返回 None（调用方应提示用户澄清）

    Args:
        keyword: 待解析关键词（user_id、昵称或群名片）

    Returns:
        person_id（哈希值）；无法定位或命中不唯一时返回 None
    """
    normalized = str(keyword or "").strip().lstrip("@").strip()
    if not normalized:
        return None

    normalized_lower = normalized.lower()

    # 获取全部 person_info 记录（可根据实际规模考虑优化）
    persons = await database_api.filter_query(PersonInfo)

    exact_hits: list[str] = []
    partial_hits: list[str] = []

    for person in persons:
        person_id_val = str(getattr(person, "person_id", "") or "").strip()
        if not person_id_val:
            continue

        user_id_val = str(getattr(person, "user_id", "") or "").strip()
        nickname = str(getattr(person, "nickname", "") or "").strip()
        cardname = str(getattr(person, "cardname", "") or "").strip()

        # 纯数字关键词：精确匹配 user_id
        if normalized.isdigit():
            if user_id_val == normalized:
                exact_hits.append(person_id_val)
            continue

        # 昵称/群名片精确匹配
        if (nickname and nickname.lower() == normalized_lower) or (
            cardname and cardname.lower() == normalized_lower
        ):
            exact_hits.append(person_id_val)
            continue

        # 模糊匹配
        if (nickname and normalized_lower in nickname.lower()) or (
            cardname and normalized_lower in cardname.lower()
        ):
            partial_hits.append(person_id_val)

    unique_exact = list(dict.fromkeys(exact_hits))
    if len(unique_exact) == 1:
        return unique_exact[0]
    if len(unique_exact) > 1:
        logger.debug(f"关键词 '{keyword}' 精确匹配到 {len(unique_exact)} 个用户，无法确定")
        return None

    unique_partial = list(dict.fromkeys(partial_hits))
    if len(unique_partial) == 1:
        return unique_partial[0]
    if len(unique_partial) > 1:
        logger.debug(f"关键词 '{keyword}' 模糊匹配到 {len(unique_partial)} 个用户，无法确定")

    return None


__all__ = ["resolve_person_id"]
