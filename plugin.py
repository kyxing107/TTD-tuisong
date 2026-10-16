"""TgtoDrive plugin: push selected popular media rankings to Telegram.

The plugin performs one fetch-and-send operation per run. Configure a schedule
for it from TgtoDrive -> Utilities -> My plugins -> Scheduled execution.
"""

import os
import json
import html
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import quote
from pathlib import Path
from typing import Any

import requests


PLUGIN_MANIFEST = {
    "schema_version": 1,
    "id": "imdb-popular-movie-telegram",
    "name": "热门影视榜单推送到Telegram",
    "version": "1.3.3",
    "description": "使用勾选的榜单提供者和分类读取热门影视，查询Emby状态后推送Telegram。",
    "author": "OpenAI",
    "entry": "plugin.py",
    "timeout": 600,
    "inputs": [
        {
            "name": "count",
            "label": "推送数量",
            "type": "number",
            "required": True,
            "default": 10,
            "min": 1,
            "max": 50,
            "step": 1,
        },
        {
            "name": "providers",
            "label": "榜单提供者",
            "type": "multiselect",
            "required": False,
            "default": [],
            "options": [
                {"label": "TMDB", "value": "tmdb"},
            ],
        },
        {
            "name": "contents",
            "label": "榜单内容（可多选）",
            "type": "multiselect",
            "required": False,
            "default": [],
            "options": [
                {"label": "TMDB热门电影", "value": "movie"},
                {"label": "TMDB热门电视剧", "value": "tv"},
                {"label": "TMDB趋势", "value": "trending"},
            ],
        },
        {
            "name": "page",
            "label": "榜单页码",
            "type": "number",
            "required": True,
            "default": 1,
            "min": 1,
            "max": 9999,
            "step": 1,
            "help": "读取所选榜单的页码。",
        },
        {
            "name": "region",
            "label": "地区参数",
            "type": "text",
            "required": False,
            "default": "",
            "placeholder": "留空使用服务默认值",
        },
        {
            "name": "force_refresh",
            "label": "强制刷新榜单",
            "type": "boolean",
            "required": False,
            "default": False,
        },
        {
            "name": "send_message",
            "label": "发送Telegram",
            "type": "boolean",
            "required": False,
            "default": True,
        },
        {
            "name": "message_style",
            "label": "Telegram消息样式",
            "type": "select",
            "required": True,
            "default": "clean",
            "options": [
                {"label": "方案一：清爽分组型", "value": "clean"},
                {"label": "方案二：紧凑榜单型", "value": "compact"},
                {"label": "方案三：信息卡片型", "value": "card"},
                {"label": "方案四：兼容纯文本型", "value": "plain"},
            ],
        },
    ],
    "ui": {
        "width": "wide",
        "layout": "stack",
        "components": [
            {"type": "heading", "text": "热门影视榜单推送"},
            {"type": "heading", "text": "榜单选择"},
            {"type": "field", "name": "providers"},
            {"type": "field", "name": "contents"},
            {"type": "heading", "text": "查询参数"},
            {
                "type": "grid",
                "columns": 2,
                "children": [
                    {"type": "field", "name": "count"},
                    {"type": "field", "name": "page"},
                ],
            },
            {"type": "field", "name": "region"},
            {"type": "field", "name": "force_refresh"},
            {"type": "heading", "text": "推送设置"},
            {"type": "field", "name": "send_message"},
            {"type": "field", "name": "message_style"},
            {"type": "button", "label": "查询/推送", "action": "run", "params": {}},
            {
                "type": "alert",
                "text": "Telegram目标使用TgtoDrive当前已配置的通知机器人和管理员目标。",
                "style": {"tone": "muted"},
            },
        ],
    },
}


def _client(context: dict[str, Any]) -> tuple[str, dict[str, str]]:
    base_url = os.environ.get("TGTO_OPENAPI_BASE_URL", "").rstrip("/")
    token = os.environ.get("TGTO_OPENAPI_TOKEN", "")
    # Some TgtoDrive deployments do not pass custom environment variables to
    # plugin subprocesses. Keep the fallback in the persistent private data
    # directory instead of exposing credentials in the form or source code.
    data_dir = Path(context["data_dir"])
    plugin_dir = Path(context["plugin_dir"])
    if not token:
        for token_path in (data_dir / "openapi_token.txt", plugin_dir / "openapi_token.txt"):
            try:
                token = token_path.read_text(encoding="utf-8").strip()
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise ValueError(f"无法读取Token文件 {token_path.name}: {exc}") from exc
            if token:
                break
    if not base_url or not token:
        config_path = data_dir / "openapi.json"
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            config = {}
        except (OSError, ValueError) as exc:
            raise ValueError(f"无法读取OpenAPI配置文件 {config_path.name}: {exc}") from exc
        base_url = str(config.get("base_url") or base_url).rstrip("/")
        token = str(config.get("token") or config.get("openapi_token") or token)
    if not base_url:
        base_url = "http://127.0.0.1:12366"
    if not base_url or not token:
        raise ValueError(
            "未找到TgtoDrive OpenAPI配置。请配置TGTO_OPENAPI_BASE_URL和"
            "TGTO_OPENAPI_TOKEN，或在插件持久目录创建openapi.json："
            '{"base_url":"http://127.0.0.1:12366","token":"YOUR_OPENAPI_TOKEN"}'
        )
    # TgtoDrive OpenAPI authentication: every /api request uses Bearer auth.
    return base_url, {"Authorization": "Bearer " + token, "Accept": "application/json"}


def _request(response: requests.Response) -> Any:
    content_type = response.headers.get("content-type", "")
    if not 200 <= response.status_code < 300:
        detail = response.text[:500].strip()
        raise RuntimeError(f"TgtoDrive接口失败，HTTP {response.status_code}: {detail}")
    if "json" not in content_type.lower():
        raise RuntimeError(f"TgtoDrive接口返回非JSON内容: {content_type}")
    payload = response.json()
    if isinstance(payload, dict) and payload.get("success") is False:
        raise RuntimeError(str(payload.get("message") or payload.get("error") or "接口返回失败"))
    return payload


def _items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("items", "results", "movies", "data", "rankings", "list", "records", "rows", "subjects", "entries"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
        if isinstance(value, dict):
            nested = _items(value)
            if nested:
                return nested
    # The endpoint is inferred in the OpenAPI export and some versions wrap
    # the list under a provider-specific key. Scan all nested values and keep
    # objects that look like movie records.
    discovered: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if any(value.get(key) for key in ("title", "name", "original_title", "display_name")):
                discovered.append(value)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    if discovered:
        return discovered
    return []


def _movie_line(movie: dict[str, Any], index: int, emby_status: str = "") -> str:
    title = movie.get("title") or movie.get("name") or movie.get("original_title") or "未命名"
    year = movie.get("year") or movie.get("release_year") or movie.get("release_date") or ""
    rating = movie.get("rating") or movie.get("vote_average") or movie.get("score") or ""
    imdb_id = movie.get("imdb_id") or movie.get("imdbId") or ""
    suffix = []
    if year:
        suffix.append(str(year)[:10])
    if rating not in ("", None):
        suffix.append(f"评分 {rating}")
    if imdb_id:
        suffix.append(str(imdb_id))
    if emby_status:
        suffix.insert(0, emby_status)
    return f"{index}. {title}" + ("（" + "，".join(suffix) + "）" if suffix else "")


def _telegram_block(label: str, lines: list[str]) -> str:
    """Format one ranking block for Telegram's HTML renderer."""
    rendered: list[str] = []
    for line in lines:
        number, title, suffix = _telegram_parts(line)
        if suffix:
            rendered.append(
                f"{html.escape(number)}. <b>{html.escape(title)}</b>\n"
                f"   <i>{html.escape(suffix)}</i>"
            )
        else:
            rendered.append(f"{html.escape(number)}. <b>{html.escape(title)}</b>")
    return "<b>" + html.escape(label) + "</b>\n\n" + "\n\n".join(rendered)


def _telegram_parts(line: str) -> tuple[str, str, str]:
    number, detail = line.split(". ", 1)
    if "（" not in detail or not detail.endswith("）"):
        return number, detail, ""
    title, suffix = detail.split("（", 1)
    suffix = suffix[:-1].replace("已入库", "✅ 已入库").replace("未入库", "⬜ 未入库").replace("评分 ", "⭐ ")
    return number, title, suffix


def _plain_icon_line(line: str) -> str:
    number, title, suffix = _telegram_parts(line)
    return f"{number}. {title}" + (f"（{suffix}）" if suffix else "")


def _telegram_message(blocks: list[tuple[str, list[str]]], style: str) -> tuple[str, str]:
    date_text = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y年%m月%d日")
    style = style if style in {"clean", "compact", "card", "plain"} else "clean"
    if style == "clean":
        content = "\n\n━━━━━━━━━━━━\n\n".join(_telegram_block(label, lines) for label, lines in blocks)
        return f"<b>🎬 热门影视榜单</b>\n<i>📅 {date_text}</i>\n\n{content}", "HTML"
    if style == "compact":
        rendered: list[str] = [f"<b>🔥 热门影视榜单</b> · <i>{date_text}</i>"]
        for label, lines in blocks:
            rendered.append("\n<b>" + html.escape(label) + "</b>")
            for line in lines:
                number, title, suffix = _telegram_parts(line)
                if suffix:
                    suffix_parts = suffix.split("，")
                    marker = suffix_parts[0] if suffix_parts and suffix_parts[0].startswith(("✅", "⬜")) else ""
                    rest = " · ".join(suffix_parts[1:] if marker else suffix_parts)
                    prefix = f"{marker} " if marker else ""
                    tail = f" · <i>{html.escape(rest)}</i>" if rest else ""
                    rendered.append(f"{html.escape(number)}. {prefix}<b>{html.escape(title)}</b>{tail}")
                else:
                    rendered.append(f"{html.escape(number)}. <b>{html.escape(title)}</b>")
        return "\n".join(rendered), "HTML"
    if style == "card":
        rendered = [f"<b>🔥 热门影视榜单</b>\n<i>📅 {date_text}</i>"]
        for label, lines in blocks:
            rendered.append("<b>" + html.escape(label) + "</b>\n━━━━━━━━━━━━")
            for line in lines:
                number, title, suffix = _telegram_parts(line)
                if suffix:
                    rendered.append(f"<b>{html.escape(number.zfill(2) if number.isdigit() else number)} · {html.escape(title)}</b>\n<i>{html.escape(suffix)}</i>")
                else:
                    rendered.append(f"<b>{html.escape(number)} · {html.escape(title)}</b>")
        return "\n\n".join(rendered), "HTML"
    plain = ["热门影视榜单", f"日期：{date_text}", ""]
    for label, lines in blocks:
        plain.extend([label, "", *(_plain_icon_line(line) for line in lines), ""])
    return "\n".join(plain).rstrip(), ""


def _status_from_value(value: Any) -> str | None:
    if isinstance(value, bool):
        return "已入库" if value else "未入库"
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1", "found", "exists", "available", "入库", "已入库", "在库"}:
            return "已入库"
        if normalized in {"false", "no", "0", "not_found", "missing", "未入库", "不在库"}:
            return "未入库"
    if isinstance(value, dict):
        for key in ("in_emby", "is_in_emby", "emby_exists", "exists", "found", "in_library", "has_emby", "library_exists", "available", "is_available", "isAdded"):
            if key in value:
                status = _status_from_value(value[key])
                if status:
                    return status
        for key in ("emby", "emby_status", "library", "library_status", "status", "state", "data", "result", "card"):
            if key in value:
                status = _status_from_value(value[key])
                if status:
                    return status
    return None


def _emby_statuses(base_url: str, headers: dict[str, str], movies: list[dict[str, Any]], provider: str, media_type: str) -> list[str]:
    items = []
    for movie in movies:
        item = dict(movie)
        item.update({
            "source": movie.get("source") or provider,
            "provider": movie.get("provider") or provider,
            "entity_type": movie.get("entity_type") or media_type,
            "type": movie.get("type") or media_type,
            "media_type": movie.get("media_type") or media_type,
            "title": movie.get("title") or movie.get("name") or movie.get("original_title"),
        })
        external_id = movie.get("id") or movie.get("external_id") or movie.get("tmdb_id") or movie.get("imdb_id")
        if external_id is not None:
            item["external_id"] = str(external_id)
            item["id"] = str(external_id)
        items.append(item)
    response = requests.post(
        f"{base_url}/api/media/emby/cards",
        headers={**headers, "Content-Type": "application/json"},
        json={"items": items},
        timeout=(5, 30),
        allow_redirects=False,
    )
    payload = _request(response)
    records = payload if isinstance(payload, list) else []
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            records = data["items"]
        for key in ("items", "cards", "results", "data", "entries", "matches"):
            if isinstance(payload.get(key), list):
                records = payload[key]
                break
    def flatten(value: Any) -> list[Any]:
        if isinstance(value, list):
            result: list[Any] = []
            for child in value:
                result.extend(flatten(child))
            return result
        if isinstance(value, dict):
            nested: list[Any] = []
            for key in ("items", "cards", "results", "data", "entries", "matches", "card", "emby"):
                if key in value:
                    nested.extend(flatten(value[key]))
            return [value] + nested
        return [value]

    records = flatten(records)

    def record_matches(record: Any, movie: dict[str, Any]) -> bool:
        if not isinstance(record, dict):
            return False
        title = str(movie.get("title") or movie.get("name") or movie.get("original_title") or "").casefold()
        values = " ".join(str(record.get(key, "")) for key in ("title", "name", "original_title", "id", "external_id", "tmdb_id", "imdb_id")).casefold()
        return bool(title and title in values)

    statuses: list[str] = []
    for index, movie in enumerate(movies):
        record = records[index] if index < len(records) else None
        status = _status_from_value(record)
        # The current TgtoDrive response is data.items[index].result.state.
        if isinstance(record, dict):
            result = record.get("result")
            if isinstance(result, dict):
                status = _status_from_value(result.get("state")) or status
        for candidate in records:
            if record_matches(candidate, movie):
                status = _status_from_value(candidate) or status
                if status:
                    break
        statuses.append(status or "未入库")
    return statuses


def _extract_bot_target(payload: Any) -> tuple[Any, Any]:
    """Best-effort extraction from generic notify-bots responses."""
    candidates = payload if isinstance(payload, list) else []
    if isinstance(payload, dict):
        for key in ("bots", "items", "data", "configs"):
            if isinstance(payload.get(key), list):
                candidates = payload[key]
                break
    for item in candidates:
        if not isinstance(item, dict):
            continue
        token = item.get("bot_token") or item.get("token")
        target = item.get("admin_user_id") or item.get("chat_id") or item.get("target_id")
        if token and target:
            return token, target
    return None, None


def _provider_candidates(payload: Any) -> list[str]:
    """Extract provider ids from the generic /api/media/providers response."""
    found: list[str] = []
    preferred = ("tmdb", "douban", "豆瓣", "imdb")

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                key_text = str(key).lower()
                if key_text in {"id", "key", "value", "provider", "source", "code", "slug"} and isinstance(item, str):
                    candidate = item.strip()
                    if candidate and candidate not in found and len(candidate) <= 100:
                        found.append(candidate)
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)
    return sorted(found, key=lambda item: (0 if item.lower() in preferred else 1, item.lower()))


def _fetch_ranking(base_url: str, headers: dict[str, str], provider: str, query: dict[str, str]) -> tuple[Any, str]:
    response = requests.get(
        f"{base_url}/api/media/rankings/{provider}",
        headers=headers,
        params=query,
        timeout=(5, 30),
        allow_redirects=False,
    )
    try:
        return _request(response), provider
    except RuntimeError as exc:
        if "INVALID_STREAMING_PROVIDER" not in str(exc):
            raise
        providers_response = requests.get(
            f"{base_url}/api/media/providers",
            headers=headers,
            timeout=(5, 20),
            allow_redirects=False,
        )
        candidates = _provider_candidates(_request(providers_response))
        candidates = [item for item in candidates if item.lower() != provider.lower()]
        errors: list[str] = []
        for candidate in candidates:
            retry = requests.get(
                f"{base_url}/api/media/rankings/{candidate}",
                headers=headers,
                params=query,
                timeout=(5, 30),
                allow_redirects=False,
            )
            try:
                return _request(retry), candidate
            except RuntimeError as retry_error:
                errors.append(str(retry_error)[:120])
        raise RuntimeError(f"榜单来源 {provider} 不受支持，已发现来源也未返回可用榜单") from exc


_CONTENT_LABELS = {item["value"]: item["label"] for item in PLUGIN_MANIFEST["inputs"][2]["options"]}
_TMDB_CONTENTS = {"movie", "tv", "trending"}
_DOUBAN_CONTENTS: set[str] = set()


def _queue_path(context: dict[str, str]) -> Path:
    return Path(context["data_dir"]) / "push_selections.json"


def _load_queue(context: dict[str, str]) -> list[dict[str, str]]:
    try:
        value = json.loads(_queue_path(context).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        raise ValueError(f"已添加内容配置损坏: {exc}") from exc
    return [x for x in value if isinstance(x, dict) and x.get("provider") == "tmdb" and x.get("content") in _TMDB_CONTENTS] if isinstance(value, list) else []


def _save_queue(context: dict[str, str], queue: list[dict[str, str]]) -> None:
    path = _queue_path(context)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _parse_routes(params: dict[str, Any], context: dict[str, str]) -> dict[str, Any]:
    raw = params.get("ranking_routes")
    if not raw:
        route_path = Path(context["data_dir"]) / "ranking_routes.json"
        try:
            raw = route_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
    if isinstance(raw, dict):
        routes = raw
    else:
        try:
            routes = json.loads(str(raw))
        except ValueError as exc:
            raise ValueError("分类接口映射必须是合法JSON") from exc
    if not isinstance(routes, dict):
        raise ValueError("分类接口映射必须是JSON对象")
    for key, route in routes.items():
        if not isinstance(key, str) or not isinstance(route, dict):
            raise ValueError("分类接口映射格式错误")
        mapped_provider = str(route.get("provider") or "").strip()
        if not mapped_provider or "/" in mapped_provider or "\\" in mapped_provider:
            raise ValueError(f"分类 {key} 的provider映射无效")
        query = route.get("query", {})
        if not isinstance(query, dict) or any(str(k) not in {"force", "media_type", "page", "region"} for k in query):
            raise ValueError(f"分类 {key} 的query只能使用force、media_type、page、region")
    return routes


def _selection_pairs(params: dict[str, Any], context: dict[str, str]) -> list[dict[str, str]]:
    providers = params.get("providers") or []
    if isinstance(providers, str):
        providers = [providers]
    providers = [str(x).strip().lower() for x in providers if str(x).strip()]
    contents = params.get("contents") or []
    if isinstance(contents, str):
        contents = [contents]
    label_to_value = {str(label): value for value, label in _CONTENT_LABELS.items()}
    contents = [label_to_value.get(str(x), str(x)) for x in contents if str(x)]
    invalid_providers = [x for x in providers if x not in {"tmdb", "douban"}]
    if invalid_providers:
        raise ValueError("榜单提供者只能选择TMDB")
    if providers:
        selections: list[dict[str, str]] = []
        for provider in providers:
            allowed = _TMDB_CONTENTS if provider == "tmdb" else _DOUBAN_CONTENTS
            selected = [x for x in contents if x in allowed]
            if not selected:
                name = "TMDB"
                raise ValueError(f"已选择{name}，请至少勾选一个对应的榜单内容")
            selections.extend({"provider": provider, "content": x} for x in selected)
        return selections
    if contents:
        raise ValueError("榜单提供者为空时不能勾选榜单内容")
    return _load_queue(context)


def _query_for_selection(selection: dict[str, str], page: int, region: str, force: bool, routes: dict[str, Any]) -> tuple[str, dict[str, str], str]:
    provider, content = selection["provider"], selection["content"]
    route = routes.get(content)
    if provider == "douban" or content == "trending":
        if not route:
            raise RuntimeError(f"分类“{_CONTENT_LABELS.get(content, content)}”没有已核实的接口映射，请在表单或data_dir/ranking_routes.json中配置")
    query = {"page": str(page)}
    if region:
        query["region"] = region
    if force:
        query["force"] = "1"
    if route:
        actual_provider = str(route["provider"])
        query.update({str(k): str(v) for k, v in route.get("query", {}).items()})
    else:
        actual_provider = provider
        query["media_type"] = "tv" if content == "tv" else "movie"
    return actual_provider, query, content


def run(params: dict[str, Any], context: dict[str, str]) -> dict[str, Any]:
    action = str(params.get("action") or "run").strip().lower()
    selections = _selection_pairs(params, context)
    if action == "add":
        queue = _load_queue(context)
        for item in selections:
            if item not in queue:
                queue.append(item)
        _save_queue(context, queue)
        return {"action": "add", "count": len(queue), "selections": queue, "ui": [{"type": "code", "text": "已添加：\n" + "\n".join(f"{x['provider']} / {_CONTENT_LABELS.get(x['content'], x['content'])}" for x in queue)}]}
    if action == "list":
        return {"action": "list", "count": len(selections), "selections": selections, "ui": [{"type": "code", "text": "\n".join(f"{x['provider']} / {_CONTENT_LABELS.get(x['content'], x['content'])}" for x in selections) or "暂无已添加内容"}]}
    if action == "clear":
        _save_queue(context, [])
        return {"action": "clear", "count": 0, "selections": [], "ui": [{"type": "code", "text": "已清空推送队列"}]}
    if not selections:
        raise ValueError("请先选择提供者和榜单内容，或添加推送内容")
    base_url, headers = _client(context)
    count = int(params.get("count", 10))
    if not 1 <= count <= 50:
        raise ValueError("推送数量必须在1到50之间")
    page = int(params.get("page", 1))
    if not 1 <= page <= 9999:
        raise ValueError("榜单页码必须在1到9999之间")
    routes = _parse_routes(params, context)
    blocks: list[str] = []
    telegram_blocks: list[tuple[str, list[str]]] = []
    total = 0
    for selection in selections:
        actual_provider, query, content = _query_for_selection(selection, page, str(params.get("region") or "").strip(), bool(params.get("force_refresh")), routes)
        payload, resolved_provider = _fetch_ranking(base_url, headers, actual_provider, query)
        movies = _items(payload)[:count]
        if not movies:
            raise RuntimeError(f"榜单“{_CONTENT_LABELS.get(content, content)}”接口未返回可识别的内容列表")
        media_type = "tv" if content in {"tv", "douban_tv", "douban_tv_hot", "douban_cn_tv", "douban_kr_tv", "douban_jp_tv", "douban_us_tv"} else "movie"
        try:
            emby_statuses = _emby_statuses(base_url, headers, movies, resolved_provider, media_type)
        except Exception:
            emby_statuses = ["未入库"] * len(movies)
        plain_lines = [_movie_line(movie, i, emby_statuses[i - 1]) for i, movie in enumerate(movies, 1)]
        label = _CONTENT_LABELS.get(content, content)
        blocks.append(label + "\n\n" + "\n".join(plain_lines))
        telegram_blocks.append((label, plain_lines))
        total += len(movies)
    message = "\n\n".join(blocks)
    telegram_message, parse_mode = _telegram_message(telegram_blocks, str(params.get("message_style") or "clean"))

    sent = False
    send_error = None
    if params.get("send_message", True):
        try:
            bots_response = requests.get(
                f"{base_url}/api/notify-bots",
                headers=headers,
                timeout=(5, 20),
                allow_redirects=False,
            )
            bots = _request(bots_response)
            bot_token, target = _extract_bot_target(bots)
            body = {"message": message}
            if bot_token:
                body["bot_token"] = bot_token
            if target:
                body["admin_user_id"] = target
            if not bot_token or not target:
                raise RuntimeError("/api/notify-bots未返回可用的bot_token和管理员目标")
            send_response = requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": str(target), "text": telegram_message, **({"parse_mode": parse_mode} if parse_mode else {})},
                timeout=(5, 30),
                allow_redirects=False,
            )
            if not 200 <= send_response.status_code < 300:
                raise RuntimeError(
                    f"Telegram Bot API发送失败，HTTP {send_response.status_code}: "
                    f"{send_response.text[:500].strip()}"
                )
            telegram_result = send_response.json()
            if not telegram_result.get("ok"):
                raise RuntimeError(str(telegram_result.get("description") or "Telegram发送失败"))
            sent = True
        except Exception as exc:
            send_error = str(exc)

    result = {
        "providers": sorted({x["provider"] for x in selections}),
        "count": total,
        "selections": selections,
        "page": page,
        "message": message,
        "sent": sent,
        "delivery": "telegram_bot_api" if sent else "not_sent",
        "ui": [{"type": "code", "text": message}],
    }
    if send_error:
        result["send_error"] = send_error
    return result
