# 热门影视榜单推送到 Telegram

插件采用静态勾选界面：榜单提供者当前为 TMDB；榜单内容包括 TMDB热门电影、TMDB热门电视剧和TMDB趋势。点击“查询/推送”会读取当前勾选的榜单，查询 Emby 入库状态，并发送到 TgtoDrive 已配置的 Telegram 通知机器人。

榜单提供者和榜单内容均为静态选项，不显示动态分类。

当前 OpenAPI 只明确声明 `/api/media/rankings/{provider}` 的 `force`、`media_type`、`page`、`region` 参数，没有声明 TMDB 趋势的真实路由值。因此 TMDB 电影/电视剧使用对应的 `media_type`；TMDB 趋势需要填写已核实的映射，不会偷偷改用其他来源。映射示例：

```json
{
  "trending": {"provider": "已核实的来源ID", "query": {"media_type": "movie"}}
}
```

映射可粘贴到表单“分类接口映射（可选JSON）”，或保存为持久数据目录的 `ranking_routes.json`。`query` 只能使用 OpenAPI 声明的四个参数。没有映射时会明确提示缺少接口映射。

配置：优先使用 `TGTO_OPENAPI_BASE_URL` 与 `TGTO_OPENAPI_TOKEN`；也可在 `data_dir/openapi_token.txt` 或 `data_dir/openapi.json` 中保存。Token 只用于 Bearer 调用 TgtoDrive，不会发送给 Telegram。

主要路径：`GET /api/media/rankings/{provider}`、`POST /api/media/emby/cards`、`GET /api/notify-bots`，以及 Telegram Bot API `sendMessage`。Emby 返回 `found` 显示“已入库”，其他状态和查询失败统一显示“未入库”。

Telegram 正文使用方案一的清爽分组格式：顶部显示上海时区当天日期，分组标题和片名加粗，状态/年份/评分使用斜体，并在多个榜单之间加入分隔线；插件结果面板仍返回纯文本。

表单提供四种 Telegram 消息样式，可随时切换：方案一清爽分组型、方案二紧凑榜单型、方案三信息卡片型、方案四兼容纯文本型。默认使用方案一。

界面采用分区布局：榜单选择、查询参数、推送设置。数量和页码在查询参数区并排显示，便于快速配置。

定时推送由 TgtoDrive“实用工具 → 我的插件 → 定时执行”配置，例如每天 `0 9 * * *`。插件本身不创建后台线程或计划任务。

导入 `imdb-popular-movie-telegram.zip`，或直接导入 `plugin.py`。`send_message=false` 可先预览消息。
