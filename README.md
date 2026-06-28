# user_rhythm - 用户作息与习惯分析插件

通过统计用户历史消息的时间分布，分析其作息规律；支持 LLM 主动记录和查询用户习惯；
在私聊场景被动注入作息简报到 Prompt。**插件本身不调用任何 LLM**，所有分析均为纯代码实现。

## 功能特性

- **作息统计分析**：基于用户消息时间戳的纯 Python 统计分析，计算 24 小时分布、时段占比、最活跃时段等
- **门槛机制**：需同时满足 7天活跃 + 200条消息才生成分布模型，避免数据稀疏时产生误导
- **懒加载 + 定时重建**：首次查询时按需计算，后续由定时任务（默认 24 小时）在后台重建
- **模糊搜索**：支持通过昵称或 user_id 模糊查询用户
- **私聊被动注入**：在私聊场景自动将作息简报注入到 User Prompt，让 Bot 自然了解用户习惯
- **群聊主动查询**：群聊不自动注入，LLM 可通过 Tool 主动查询
- **习惯记录**：LLM 可主动记录用户明确陈述的时间习惯（与统计分析分开，可靠度更高）

## 安装与部署

本插件作为 Neo-MoFox 的一部分，可通过克隆至 `plugins/` 目录完成安装：

```bash
git clone https://github.com/tt-P607/user_rhythm.git plugins/user_rhythm
```

## 配置

默认配置文件将自动生成在：`config/plugins/user_rhythm/config.toml`

```toml
[plugin]
enabled = true
debug_log = false

[threshold]
mode = "or"              # 门槛模式：'and'=同时满足天数和条数，'or'=满足其一即可，'days'=仅看天数，'messages'=仅看条数
min_active_days = 7      # 最少活跃天数
min_messages = 200       # 最少消息数

[analysis]
sample_mode = "messages" # 取样模式：'messages'=取最新 N 条消息，'days'=取最近 N 天的消息
sample_limit = 3000      # sample_mode='messages' 时：最多取多少条最新消息
sample_days = 90         # sample_mode='days' 时：取最近多少天的消息

[rebuild]
interval_hours = 24      # 定时重建间隔（小时）

[injection]
enabled = true
target_prompts = ["default_chatter_user_prompt"]
```

## 使用方式

### 1. LLM 主动查询（Tool）

```
query_user_rhythm(target_user="张三")
```

返回：
- `available`: 数据是否充足
- `stats`: 统计数据（消息分布、活跃时段等）
- `habits`: 手动记录的习惯列表

### 2. LLM 主动记录习惯（Tool）

```
record_user_habit(
    target_user="张三",
    habit_desc="每天早上7点半去跑步",
    habit_category="rhythm",
    cron_like_time="07:30"
)
```

### 3. 私聊自动注入

在私聊场景，插件会自动检查用户的作息数据，如果达标则注入类似以下内容到 User Prompt 末尾：

```
[用户作息特征参考]
消息时间分布：上午47.2%、下午22.8%、晚上19.3%、深夜8.1%
最活跃时段：上午（9-10点）
手动记录习惯：每天早上07:30跑步
数据来源：过去45天内，12天活跃，共计247条消息
```

## 设计原则

1. **纯事实数据，无主观推断**：`RhythmAnalyzer` 只输出原始统计数字和时段名称，不贴"夜猫子"/"晨型人"等标签
2. **LLM 自行解读**：如何基于数据判断作息类型，完全由 LLM 根据完整数据自己决定
3. **门槛保护**：数据不足时不生成分布模型，避免误导
4. **零 LLM 调用**：整个插件不调用任何 LLM，所有计算都是纯代码实现
5. **性能控制**：sample_limit 限制单次查询最多取 3000 条最新消息，保证速度

## 技术架构

```
plugins/user_rhythm/
├── plugin.py              # 插件入口，注册组件，管理生命周期
├── manifest.json          # 插件元数据
├── components/
│   ├── configs/
│   │   └── config.py      # 配置模型
│   ├── tools/
│   │   ├── query_rhythm.py     # 查询工具
│   │   └── record_habit.py     # 记录工具
│   └── events/
│       └── prompt_injector.py  # 私聊注入器
└── core/
    ├── models.py          # 数据模型（RhythmSnapshotModel, UserHabitModel）
    ├── store.py           # 存储层（PluginDatabase）
    └── analyzer.py        # 统计分析器（纯代码，无LLM）
```

## 数据存储

- **快照缓存**：`data/user_rhythm/rhythm.db` - `rhythm_snapshots` 表
- **习惯记录**：同上 - `user_habits` 表
- **消息时间戳**：只读访问核心数据库的 `messages` 表，不修改

## License

AGPL-v3.0
