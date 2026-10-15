# IMDb热门电影推送到 Telegram

## 功能

每次运行使用 OpenAPI Bearer Token 调用 TgtoDrive 原始 `/api/...` 路径：`GET /api/media/rankings/{provider}` 查询榜单，读取 `GET /api/notify-bots` 的现有机器人配置；随后使用返回的机器人 Token 和管理员目标调用 Telegram Bot API `sendMessage` 发送榜单正文。Bearer Token 只用于 TgtoDrive API，不会转发给 Telegram。

TgtoDrive 的榜单接口要求使用受支持的流媒体 provider；默认值为 `tmdb`。如果手工填写的 provider 返回 `INVALID_STREAMING_PROVIDER`，插件会调用 `/api/media/providers` 自动发现来源并重试。榜单响应会递归识别常见的 `items`、`results`、`movies`、`records`、`subjects` 等结构。

插件只执行一次任务；需要定时推送时，在 TgtoDrive 的“实用工具 → 我的插件 → 定时执行”中为本插件创建 cron 计划，例如 `0 9 * * *`。

## 配置

优先使用容器环境变量：

- `TGTO_OPENAPI_BASE_URL`：例如 `http://127.0.0.1:12366`
- `TGTO_OPENAPI_TOKEN`：在 TgtoDrive OpenAPI 页面创建的 Bearer Token

如果插件进程没有继承环境变量，推荐在插件的持久数据目录（运行上下文中的 `data_dir`）创建 `openapi_token.txt`，文件内容只放 Token（前后空白会自动去除）。例如：

```text
YOUR_OPENAPI_TOKEN
```

服务地址默认使用 `TGTO_OPENAPI_BASE_URL`；未设置时插件使用 `http://127.0.0.1:12366`。如果端口不同，再创建 `openapi.json`：

```json
{"base_url":"http://127.0.0.1:12366","token":"YOUR_OPENAPI_TOKEN"}
```

`openapi_token.txt` 和 `openapi.json` 只由插件读取，不会写入插件代码、日志或运行结果。不要把真实 Token 放进 `plugin.py`、`plugin.json` 或 ZIP 包。

Token 文件可放在 `data_dir/openapi_token.txt`（推荐，更新后保留），也可放在插件目录的 `openapi_token.txt`。

表单参数：`count`（1-50，默认 10）、`provider`（默认 `tmdb`）、`region`（可选）、`force_refresh`、`send_message`。

界面中的“发送测试消息”按钮会调用同一入口，通过 Telegram Bot API 发送固定测试文本，不查询榜单。

Telegram 目标使用 TgtoDrive 已保存的通知机器人配置，不在插件中保存 Token。

## 导入

直接导入 `plugin.py`，或导入同目录生成的 `imdb-popular-movie-telegram.zip`。

## 验证

先将 `send_message=false` 运行，检查返回的榜单文本；再启用发送。无效 Token、接口非 2xx、空榜单和通知发送异常都会在结果中明确显示。
