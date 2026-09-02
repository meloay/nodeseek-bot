# NodeSeek 论坛关键字监控 Telegram 机器人 - 项目需求文档

## 一、项目概述

### 1.1 项目背景

NodeSeek（[www.nodeseek.com](https://www.nodeseek.com/)）是一个主机 / VPS / 服务器爱好者交流论坛，涵盖日常、技术、情报、测评、交易、拼车等多个板块。用户需要实时监控论坛新发帖中包含特定关键字的内容，并通过 Telegram 机器人接收推送通知，以便第一时间获取感兴趣的信息。

### 1.2 项目目标

开发一个基于 Telegram Bot 的 NodeSeek 论坛监控工具，用户可通过 Telegram 机器人配置监控关键字，系统定时抓取论坛最新帖子，匹配关键字后自动推送到用户 Telegram 账号。

### 1.3 核心价值

- **实时性**：第一时间获取关注的论坛动态
- **精准性**：自定义关键字过滤，只接收感兴趣的内容
- **便捷性**：通过 Telegram 一站式配置与接收
- **轻量化**：低资源消耗，可长期稳定运行

---

## 二、功能需求

### 2.1 数据源接入

- **RSS 源抓取**：基于 NodeSeek 官方 RSS 源 `https://rss.nodeseek.com/` 获取最新帖子列表
- **分类支持**：支持按论坛分类筛选（日常、技术、情报、测评、交易、拼车、推广、Dev、贴图、曝光等）
- **增量更新**：记录已推送帖子 ID，避免重复推送
- **抓取频率**：可配置抓取间隔（默认 60 秒，建议不低于 30 秒）
- **异常重试**：网络异常时自动重试机制

### 2.2 Telegram 机器人交互功能

#### 用户配置命令

命令	功能说明
/start	欢迎信息，展示使用帮助
/add <关键字>	添加监控关键字（支持多个）
/remove <关键字>	删除指定监控关键字
/list	查看当前所有监控关键字列表
/clear	清空所有监控关键字
/interval <分钟数>	设置推送检查间隔（如 /interval 5）
/status	查看当前监控状态、关键字数量、运行时长
/pause	暂停推送通知
/resume	恢复推送通知
/help	显示帮助文档

#### 高级配置

- **板块过滤**：可指定只监控特定板块（如只监控交易 / 情报板块）
- **匹配模式**：支持精确匹配 / 模糊匹配 / 正则表达式三种模式
- **排除词设置**：可添加排除关键字，命中时不推送
- **推送格式**：可选择简洁模式 / 完整模式

### 2.3 关键字匹配引擎

- **多关键字匹配**：同时匹配多个关键字，任一命中即推送
- **匹配范围**：支持标题匹配、标题 + 正文匹配两种模式
- **大小写不敏感**：中英文均不区分大小写
- **去重机制**：同一帖子只推送一次，基于帖子唯一 ID 去重
- **命中高亮**：推送消息中高亮显示命中的关键字

### 2.4 推送消息格式

推送消息包含以下信息：

- 帖子标题（命中关键字高亮）
- 帖子所属板块
- 发帖作者
- 发布时间
- 内容摘要（前 200 字）
- 命中的关键字
- 帖子原文链接
- 直达链接按钮（Inline Keyboard）

### 2.5 多用户支持

- **用户隔离**：每个 Telegram 用户独立配置，互不干扰
- **数据持久化**：用户配置与已推送记录持久化存储
- **用户上限**：单实例支持至少 100 个用户同时使用

---

## 三、技术架构

### 3.1 技术栈选型

层级	技术选型	说明
开发语言	Python 3.10+	生态丰富，Telegram Bot 库成熟
Telegram Bot	python-telegram-bot v20+	官方推荐异步框架
RSS 解析	feedparser	成熟稳定的 RSS 解析库
数据存储	SQLite	轻量级，无需额外部署数据库
任务调度	APScheduler	定时任务调度
部署方式	Docker + Docker Compose	一键部署，环境隔离

### 3.2 系统架构图

┌─────────────────┐     HTTP/RSS     ┌─────────────────┐
│  NodeSeek 论坛   │ ◄─────────────── │   RSS 抓取模块   │
│  rss.nodeseek.com│                  │  (定时轮询)      │
└─────────────────┘                  └────────┬────────┘
                                              │
                                              ▼
┌─────────────────┐                  ┌─────────────────┐
│  Telegram 用户  │ ───────────────► │  匹配引擎模块   │
│  (配置/接收)     │ ◄─────────────── │  (关键字匹配)    │
└─────────────────┘                  └────────┬────────┘
                                              │
                                              ▼
                                       ┌─────────────────┐
                                       │   数据存储层     │
                                       │  (SQLite)       │
                                       └─────────────────┘

### 3.3 核心模块划分

1. **rss_fetcher**：RSS 源抓取与解析模块
2. **matcher**：关键字匹配引擎
3. **bot_handler**：Telegram 机器人命令处理与消息推送
4. **storage**：数据持久化层（用户配置、推送记录）
5. **scheduler**：定时任务调度器
6. **config**：全局配置管理

---

## 四、数据模型设计

### 4.1 用户表 (users)

字段	类型	说明
user_id	INTEGER PRIMARY KEY	Telegram 用户 ID
username	TEXT	Telegram 用户名
is_active	BOOLEAN	是否启用推送（默认 True）
check_interval	INTEGER	检查间隔（分钟，默认 5）
match_scope	TEXT	匹配范围：title /full（默认 title）
created_at	DATETIME	创建时间
updated_at	DATETIME	更新时间

### 4.2 关键字表 (keywords)

字段	类型	说明
id	INTEGER PRIMARY KEY	自增 ID
user_id	INTEGER	关联用户 ID
keyword	TEXT	关键字内容
match_mode	TEXT	匹配模式：exact /fuzzy/regex（默认 fuzzy）
is_exclude	BOOLEAN	是否为排除词（默认 False）
created_at	DATETIME	创建时间

### 4.3 板块过滤表 (category_filters)

字段	类型	说明
id	INTEGER PRIMARY KEY	自增 ID
user_id	INTEGER	关联用户 ID
category	TEXT	板块名称

### 4.4 推送记录表 (sent_posts)

字段	类型	说明
id	INTEGER PRIMARY KEY	自增 ID
user_id	INTEGER	接收用户 ID
post_id	TEXT	帖子唯一标识（从 RSS 提取）
post_title	TEXT	帖子标题
matched_keywords	TEXT	命中的关键字列表
sent_at	DATETIME	推送时间

## 五、非功能需求

### 5.1 性能要求

- 单次 RSS 抓取 + 解析耗时 < 3 秒
- 单用户关键字匹配耗时 < 100ms
- 支持 100 用户并发配置操作无延迟
- 内存占用 < 200MB，CPU 占用 < 5%（空闲时）

### 5.2 稳定性要求

- 7×24 小时不间断运行
- 网络异常自动重试，重试间隔指数退避
- RSS 源格式变化时优雅降级，不崩溃
- 异常自动记录日志，便于排查

### 5.3 可维护性

- 配置文件与代码分离
- 结构化日志输出（INFO/WARNING/ERROR 分级）
- 代码模块化，便于后续扩展其他论坛源
- Docker 一键部署

### 5.4 合规性

- 遵守 NodeSeek 网站 robots.txt 规则
- 抓取频率控制合理，不对站点造成压力
- 仅抓取公开内容，不涉及登录态与隐私数据
- 用户数据本地存储，不上传第三方

---

## 六、部署方案

### 6.1 环境要求

- Linux /macOS/ Windows 均可
- Docker & Docker Compose（推荐）
- 或 Python 3.10+ 环境直接运行
- 网络可访问 NodeSeek 与 Telegram API

### 6.2 配置项
# config.yaml
telegram:
  bot_token: "你的Bot Token"
  admin_id: 123456789  # 管理员用户ID

rss:
  url: "https://rss.nodeseek.com/"
  default_interval_minutes: 5
  min_interval_minutes: 1
  timeout_seconds: 10
  retry_times: 3

database:
  path: "./data/nodeseek_monitor.db"

logging:
  level: "INFO"
  file: "./logs/app.log"

### 6.3 部署步骤

1. 从 @BotFather 获取 Telegram Bot Token
2. 克隆项目代码
3. 复制配置模板并填入 Token
4. 执行 `docker-compose up -d` 启动
5. 在 Telegram 中与机器人对话，发送 `/start` 开始使用

---

## 七、扩展规划（可选）

### 7.1 一期功能（MVP）

- 基础关键字添加 / 删除 / 列表
- RSS 定时抓取与推送
- SQLite 数据持久化
- 基础去重机制

### 7.2 二期功能

- 板块过滤
- 排除词设置
- 匹配模式切换
- 推送统计面板

### 7.3 三期功能

- 支持多个论坛源扩展
- 关键词分组管理
- 推送静默时段设置
- Web 管理后台

---

## 八、交付物清单

1. 完整 Python 源代码
2. Dockerfile 与 docker-compose.yml
3. 配置文件模板
4. 部署说明文档（README.md）
5. 使用说明文档