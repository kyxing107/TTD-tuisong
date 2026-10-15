"""TgtoDrive plugin: push IMDb popular movies to Telegram.

The plugin performs one fetch-and-send operation per run. Configure a schedule
for it from TgtoDrive -> Utilities -> My plugins -> Scheduled execution.
"""

import os
import json
from pathlib import Path
from typing import Any

import requests


PLUGIN_MANIFEST = {
    "schema_version": 1,
    "id": "imdb-popular-movie-telegram",
    "name": "IMDb热门电影推送到Telegram",
    "version": "1.0.2",
    "description": "读取IMDb热门电影榜单，并通过TgtoDrive已配置的Telegram通知机器人发送摘要。",
    "author": "OpenAI",
    "entry": "plugin.py",
    "timeout": 120,
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
            "name": "provider",
            "label": "榜单提供者",
            "type": "text",
            "required": True,
            "default": "tmdb",
            "placeholder": "tmdb",
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
            "name": "test_message",
            "label": "测试消息模式",
            "type": "boolean",
            "required": False,
            "default": False,
            "help": "由界面按钮临时启用；启用后发送固定测试文本，不查询榜单。",
        },
    ],
    "ui": {
        "width": "wide",
        "layout": "stack",
        "components": [
            {"type": "heading", "text": "IMDb热门电影推送"},
            {"type": "field", "name": "count"},
            {"type": "field", "name": "provider"},
            {"type": "field", "name": "region"},
            {"type": "field", "name": "force_refresh"},
            {"type": "field", "name": "send_message"},
            {"type": "field", "name": "test_message"},
            {
                "type": "button",
                "label": "发送测试消息",
                "action": "run",
                "params": {"test_message": True, "send_message": True},
                "style": {"tone": "primary", "variant": "outline"},
            },
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


def _movie_line(movie: dict[str, Any], index: int) -> str:
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
    return f"{index}. {title}" + ("（" + "，".join(suffix) + "）" if suffix else "")


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
        providers = _request(providers_response)
        candidates = _provider_candidates(providers)
        candidates = [item for item in candidates if item.lower() != provider.lower()]
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
            except RuntimeError:
                continue
        raise RuntimeError(
            f"榜单来源 {provider} 不受支持，且 /api/media/providers 未找到可用榜单来源"
        ) from exc


def run(params: dict[str, Any], context: dict[str, str]) -> dict[str, Any]:
    base_url, headers = _client(context)
    test_message = bool(params.get("test_message", False))
    if test_message:
        message = "IMDb热门电影推送插件测试消息：Telegram发送链路正常。"
        movies = []
        provider = "test"
    else:
        provider = str(params.get("provider") or "tmdb").strip()
        if not provider:
            raise ValueError("榜单提供者不能为空")
        count = int(params.get("count", 10))
        if not 1 <= count <= 50:
            raise ValueError("推送数量必须在1到50之间")
        query = {"media_type": "movie", "page": "1"}
        if params.get("region"):
            query["region"] = str(params["region"]).strip()
        if params.get("force_refresh"):
            query["force"] = "1"
        payload, provider = _fetch_ranking(base_url, headers, provider, query)
        movies = _items(payload)[:count]
        if not movies:
            keys = ", ".join(str(key) for key in payload.keys()) if isinstance(payload, dict) else type(payload).__name__
            raise RuntimeError(f"榜单接口未返回可识别的电影列表（响应字段: {keys[:300]}）")
        lines = ["IMDb热门电影", ""] + [_movie_line(movie, i) for i, movie in enumerate(movies, 1)]
        message = "\n".join(lines)

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
                json={"chat_id": str(target), "text": message},
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
        "provider": provider,
        "count": len(movies),
        "test_message": test_message,
        "message": message,
        "sent": sent,
        "delivery": "telegram_bot_api" if sent else "not_sent",
        "ui": [{"type": "code", "text": message}],
    }
    if send_error:
        result["send_error"] = send_error
    return result
