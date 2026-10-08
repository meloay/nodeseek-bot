# NodeSeek 关键字监控 Telegram 机器人

定时读取 NodeSeek RSS，按每位 Telegram 用户独立配置的关键字匹配新帖标题，并发送带原帖按钮的通知。

## 当前功能

- `/start`、`/help`：注册并查看帮助
- `/add`、`/remove`、`/list`、`/clear`：管理关键字
- `/interval`：设置 1～1440 分钟的用户检查间隔
- `/status`：查看监控状态、运行时长和最近抓取结果
- `/pause`、`/resume`：暂停或恢复推送
- `/dmit_on`、`/dmit_off`：开启或关闭 DMIT 补货通知
- `/dmit_status`：通过地区或网络/硬件系列菜单查看可购买套餐、价格和购买链接
- `/bwh_on`、`/bwh_off`：开启或关闭 BandwagonHost 补货通知
- `/bwh_status`：通过系列或地区菜单查看可购买套餐、价格和购买链接
- 全局 RSS 单次抓取、多用户匹配
- 私聊与群组独立订阅；群组配置仅允许群管理员修改
- 首次启动历史帖子静默建线、用户级幂等去重
- SQLite 持久化、网络重试、日志轮转和历史记录清理
- Docker Compose 部署

一期只启用标题包含匹配。板块过滤、排除词、正则模式和正文匹配已在数据结构中预留，将按开发计划在二期实现。

## 群组订阅

将机器人加入群组后，由群管理员在群内执行 `/start`，再使用 `/add`、`/interval`、
`/dmit_on` 或 `/bwh_on` 配置监控。此后命中的通知会直接发送到该群组。

群组与每位用户的私聊配置相互独立。所有成员都可以查看 `/list`、`/status` 和库存
状态；添加、删除、清空关键字以及启停通知等修改操作仅限群管理员。机器人只需要
发送消息权限；为了可靠识别群管理员，建议同时将机器人设为群管理员。仅使用命令和
通知时，无需关闭 BotFather 的 Privacy Mode。

## 一键安装（推荐）

适用于已安装 Git、Docker 和 Docker Compose v2 的 Linux/macOS 服务器：

```sh
curl -fsSL https://raw.githubusercontent.com/meloay/nodeseek-bot/main/scripts/install.sh | bash
```

安装过程中会提示输入 Telegram Bot Token，输入内容不会回显。默认安装到
`~/nodeseek-bot`，随后自动构建并启动服务。

无人值守安装时，先下载脚本并通过环境变量提供 Token：

```sh
curl -fsSLo install-nodeseek-bot.sh \
  https://raw.githubusercontent.com/meloay/nodeseek-bot/main/scripts/install.sh
TELEGRAM_BOT_TOKEN='你的Token' bash install-nodeseek-bot.sh
```

常用管理命令：

```sh
cd ~/nodeseek-bot
docker compose ps                         # 查看状态
docker compose logs -f --tail=100 bot     # 查看日志
./scripts/update.sh                        # 更新并重启
./scripts/uninstall.sh                     # 停止并移除服务，保留数据
```

如需自定义安装目录，可在运行前设置 `NODESEEK_INSTALL_DIR`。安装器重复执行时会
安全更新已有安装；如果目录中有未提交修改则会停止，避免覆盖本地文件。

## 安全准备

如果 Bot Token 或 SSH 私钥曾以明文保存或分享，请先在对应平台轮换。真实 Token 只放在本机 `.env` 或服务器的密钥管理系统中，不要写入 YAML、Dockerfile、聊天记录或版本库。

## Docker Compose 启动

1. 创建本地环境文件：

   ```sh
   cp .env.example .env
   ```

2. 在 `.env` 中填写新生成的 `TELEGRAM_BOT_TOKEN`。

3. 构建并启动：

   ```sh
   docker compose up -d --build
   ```

4. 查看服务状态和日志：

   ```sh
   docker compose ps
   docker compose logs -f --tail=100 bot
   ```

数据库和日志分别保存在 Docker 命名卷 `bot-data` 与 `bot-logs` 中，容器重建不会删除数据。

## 本地运行

需要 Python 3.10 或更高版本：

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp config.example.yaml config.yaml
export TELEGRAM_BOT_TOKEN='替换为新 Token'
python -m nodeseek_bot
```

配置文件路径可通过 `NODESEEK_CONFIG` 修改；数据库路径和日志级别可分别通过 `DATABASE_PATH`、`LOG_LEVEL` 覆盖。

## 运行测试

```sh
pytest
ruff check .
```

测试使用本地 RSS fixture 和模拟 Telegram Bot，不会访问真实 Telegram 或 NodeSeek。

## 关键行为

- 系统启动后的第一次 RSS 抓取只建立水位线，不推送当前源中的历史帖子。
- 恢复推送后从恢复时刻开始，不补发暂停期间帖子。
- 全局每 60 秒抓取一次 RSS；每位用户的 `/interval` 决定多久参与一次匹配。
- 日志、帖子时间、状态时间和每日清理任务统一使用 UTC+8。
- RSS 临时失败会指数退避重试；单个用户推送失败不会影响其他用户。
- 被用户阻止后，该用户会自动暂停，避免持续无效重试。
- DMIT 中文购物车真实库存页每 60 秒检查一次，首次检查仅建立库存基线；之后只在缺货转为可购买或出现新的可购买套餐时通知。
- DMIT 通知中的购买按钮使用推广 ID `13497`，并打开对应套餐的中文购买页面。
- DMIT 库存使用浏览器 TLS 指纹读取公开购物车库存页，并以官方 `none-stock` 标记为准；不使用账号、Cookie，也不会自动下单。
- BandwagonHost 每 60 秒读取官方公开库存接口，优先使用 `bandwagonhost.com`，失败时自动切换到 `bwh81.net`。
- BandwagonHost 首次检查只建立库存基线；后续仅在缺货套餐恢复购买或出现新可购买套餐时通知。
- BandwagonHost 通知中的购买按钮使用推广 ID `65719`，不会自动下单。
- DMIT 与 BandwagonHost 库存菜单在地区前显示国旗；优惠码仅在确认适用于当前套餐时显示，否则明确提示暂无可用官方优惠码。

## 数据备份与恢复

停止服务后备份数据库可获得最一致的快照：

```sh
docker compose stop bot
docker run --rm -v nodeseek-bot_bot-data:/data -v "$PWD":/backup busybox \
  cp /data/nodeseek_monitor.db /backup/nodeseek_monitor.db.backup
docker compose start bot
```

恢复前先停止服务，再将备份覆盖回命名卷中的数据库文件。执行恢复或删除卷前，请再次确认目标名称并保留额外备份。

## 上线检查

- 确认目标服务器能访问 Telegram API 与 `https://rss.nodeseek.com/`。
- 确认 `.env`、私钥、数据库和日志未进入镜像或版本库。
- 在私聊中完成 `/start → /add → /list → /status` 冒烟测试。
- 首次抓取日志应显示已建立水位线；后续测试新帖只推送一次。
- 连续观察至少 48 小时，检查异常日志、内存和磁盘增长。
