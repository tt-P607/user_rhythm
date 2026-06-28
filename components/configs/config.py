"""user_rhythm 插件配置。

配置文件默认路径：config/plugins/user_rhythm/config.toml
"""

from __future__ import annotations

from typing import ClassVar

from src.app.plugin_system.base import BaseConfig, Field, SectionBase, config_section


class UserRhythmConfig(BaseConfig):
    """user_rhythm 用户作息分析插件配置模型。"""

    config_name: ClassVar[str] = "config"
    config_description: ClassVar[str] = "用户作息分析插件配置"

    @config_section("plugin")
    class PluginSection(SectionBase):
        """插件基础配置。"""

        enabled: bool = Field(
            default=True,
            description="是否启用插件",
        )
        debug_log: bool = Field(
            default=False,
            description="是否在日志中输出详细调试信息",
        )

    @config_section("threshold")
    class ThresholdSection(SectionBase):
        """生成分布模型的门槛配置。"""

        mode: str = Field(
            default="or",
            description="门槛模式：'and'=同时满足天数和条数，'or'=满足其一即可，'days'=仅看天数，'messages'=仅看条数",
        )
        min_active_days: int = Field(
            default=7,
            description="最少活跃天数（根据 mode 与消息数门槛配合判断）",
        )
        min_messages: int = Field(
            default=200,
            description="最少消息数（根据 mode 与活跃天数门槛配合判断）",
        )

    @config_section("analysis")
    class AnalysisSection(SectionBase):
        """统计分析配置。"""

        sample_mode: str = Field(
            default="messages",
            description="取样模式：'messages'=取最新 N 条消息，'days'=取最近 N 天的消息",
        )
        sample_limit: int = Field(
            default=3000,
            description="sample_mode='messages' 时：最多取多少条最新消息",
        )
        sample_days: int = Field(
            default=90,
            description="sample_mode='days' 时：取最近多少天的消息",
        )

    @config_section("rebuild")
    class RebuildSection(SectionBase):
        """定时重建配置。"""

        interval_hours: int = Field(
            default=24,
            description="定时重建任务的间隔时间（小时），默认 24 小时",
        )

    @config_section("injection")
    class InjectionSection(SectionBase):
        """私聊被动注入配置。"""

        enabled: bool = Field(
            default=True,
            description="是否在私聊场景自动注入作息简报到 Prompt",
        )
        target_prompts: list[str] = Field(
            default_factory=lambda: ["default_chatter_user_prompt"],
            description="要注入的提示词模板名称列表（对应 on_prompt_build 事件的 name 字段）",
        )

    plugin: PluginSection = Field(default_factory=PluginSection)
    threshold: ThresholdSection = Field(default_factory=ThresholdSection)
    analysis: AnalysisSection = Field(default_factory=AnalysisSection)
    rebuild: RebuildSection = Field(default_factory=RebuildSection)
    injection: InjectionSection = Field(default_factory=InjectionSection)
