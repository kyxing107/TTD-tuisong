# Project Instructions

## 项目定位

本项目维护可直接导入 TgtoDrive（tgto123）“实用工具 → 我的插件”的 Python 插件。插件必须面向 TgtoDrive Linux 容器运行环境，不依赖开发者 Windows 桌面环境。

## TgtoDrive 插件协议

- 单文件插件必须包含唯一的静态 `PLUGIN_MANIFEST = {...}` 字典和唯一同步入口 `def run(params, context)`。
- `run` 必须是同步函数，签名固定为 `run(params, context)`；异步操作需在入口内部运行。
- 使用 `pathlib.Path` 和 Linux 容器路径。不要使用 Windows 盘符、PowerShell、注册表、COM 或桌面 GUI。
- 运行时只使用 `context["plugin_dir"]` 和 `context["data_dir"]`；持久配置、缓存和输出写入 `data_dir`，不要写入插件代码目录。
- 不创建虚拟环境、不执行 `pip install`、不修改 TgtoDrive 项目依赖，也不要导入 TgtoDrive 内部模块、数据库或 Flask 上下文。
- 所有返回值必须可 JSON 序列化；不得返回 `Path`、`bytes`、文件句柄、`set`、NaN 或 Infinity。
- 网络请求必须设置显式超时、检查 HTTP 状态码和 Content-Type，并限制错误正文长度。
- 清单中的输入必须声明真实类型、默认值和范围；整数 ID 使用 `text`，避免 JavaScript 数字精度丢失。
- 每次修改插件后同步更新 `plugin.json`、入口代码和 `README.md` 中的版本与行为说明。

## TgtoDrive OpenAPI

- 调用 TgtoDrive 时使用环境变量 `TGTO_OPENAPI_BASE_URL` 和 `TGTO_OPENAPI_TOKEN`，请求头固定包含：

  ```http
  Authorization: Bearer <TOKEN>
  ```

- 只调用 `tgto-openapi.json` 中存在的原始 `/api/...` 路径；不得猜测内部路由或直接修改服务数据库。
- 若插件进程没有继承环境变量，优先读取 `context["data_dir"]/openapi_token.txt`；也兼容插件目录中的 `openapi_token.txt` 和 `data_dir/openapi.json`。
- Token 只能放在私有配置文件或环境变量中，不得写入源码、`plugin.json`、README、ZIP、日志或运行结果。
- `openapi_token.txt` 文件只包含 Token；`openapi.json` 可使用如下结构：

  ```json
  {"base_url":"http://127.0.0.1:12366","token":"YOUR_OPENAPI_TOKEN"}
  ```

- 默认服务地址为 `http://127.0.0.1:12366`，但部署端口变化时必须允许配置覆盖。
- 当前榜单接口使用 `GET /api/media/rankings/{provider}`，默认 provider 为 `tmdb`。`imdb` 不是该接口稳定支持的流媒体 provider。
- 遇到 `INVALID_STREAMING_PROVIDER` 时，先调用 `GET /api/media/providers` 发现可用来源，再按优先级重试；不要无限重试。
- 榜单响应字段可能因服务版本变化，解析器应兼容 `items`、`results`、`movies`、`records`、`subjects` 等结构，并支持递归识别电影对象。

## Telegram 推送

- `GET /api/proxy_settings/test_tg` 只能发送 TgtoDrive 固定测试文案，不得用于正式榜单正文推送。
- 正式自定义消息流程为：用 Bearer Token 调用 `GET /api/notify-bots`，读取已配置的 `bot_token` 与管理员目标，再调用 Telegram Bot API：

  ```text
  POST https://api.telegram.org/bot<TOKEN>/sendMessage
  ```

- Telegram 请求使用 `chat_id` 和 `text`，检查 HTTP 状态及响应中的 `ok` 字段；Bot Token 不得写入日志或返回值。
- 插件必须提供“发送测试消息”按钮。按钮通过同一 `run` 入口启用测试模式，只发送固定测试文本，不查询榜单。
- 正式运行应返回榜单摘要、发送状态和必要的错误信息，但不得返回任何凭据。

## 定时执行

- 插件只实现一次运行；定时推送由 TgtoDrive“我的插件 → 定时执行”配置。
- 不在插件中注册常驻线程、守护进程、cron、schedule 或后台循环。
- README 必须说明示例 cron 表达式和运行参数。

## 交付与验证

- 交付至少包含 `plugin.py`、`plugin.json`、`README.md`；同时生成可导入 ZIP 时，根目录直接放置这三个文件。
- 修改后必须执行 Python 编译检查、AST/JSON 清单检查和 ZIP 打包检查。
- README 必须记录功能、输入、依赖、配置文件位置、OpenAPI 路径、输出行为、测试按钮和失败处理。
- 未实际调用外部服务时，明确说明未发送真实 Telegram 消息；不要把真实凭据用于测试。
- 不要把 `__pycache__`、凭据、临时文件或 `tgto-openapi.json` 提交到插件备份仓库，除非用户明确要求。

## GitHub 备份

- Git 提交只包含插件交付文件和用户明确要求的项目文件。
- 推送前检查 `git status`、远程地址、分支和提交内容；不要提交 Token、Cookie、密码或本地运行缓存。
- 当前备份仓库为 `https://github.com/kyxing107/TTD-tuisong`，默认分支为 `main`。更新插件时保持插件 `id` 不变，按行为变化递增版本号。
