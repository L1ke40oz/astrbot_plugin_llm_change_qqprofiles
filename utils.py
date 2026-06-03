
import base64
from urllib.parse import unquote, urlparse

import aiofiles
import aiohttp
from astrbot import logger
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent


async def get_nickname(event: AiocqhttpMessageEvent) -> str | None:
    info = await event.bot.get_stranger_info(user_id=int(event.get_self_id()))
    return info.get("nickname") or info.get("nick")


def to_local_path(source: str) -> str:
    """Resolve a local file source to a plain filesystem path.

    ``file://`` URIs are decoded; bare paths (either slash style) are returned
    unchanged. Non-local sources are returned as-is.
    """
    if not source.lower().startswith("file://"):
        return source
    parsed = urlparse(source)
    path = unquote(parsed.path)
    # Windows paths come through as "/D:/foo"; strip the leading slash.
    if len(path) >= 3 and path[0] == "/" and path[2] == ":":
        path = path[1:]
    return path


async def to_onebot_file(source: str) -> str:
    """Normalize an image source into a value the OneBot端 (NapCat 等) accepts.

    Remote http(s) URLs are passed through unchanged. Local files — including
    ``file://`` URIs and bare paths (with either slash style) — are read and
    encoded as ``base64://`` so the 协议端 never has to resolve the path itself.
    This avoids retcode=1200「文件可能不是图片格式」, which NapCat raises when it
    cannot turn a local path into image bytes (e.g. Windows 盘符路径或跨设备部署)。
    """
    lowered = source.lower()
    if lowered.startswith(("http://", "https://", "base64://")):
        return source

    path = to_local_path(source)
    async with aiofiles.open(path, "rb") as f:
        data = await f.read()
    return "base64://" + base64.b64encode(data).decode("ascii")


async def download_image(url: str, save_path: str) -> None:
    """下载图片并保存到本地"""
    url = url.replace("https://", "http://")
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                async with aiofiles.open(save_path, "wb") as f:
                    await f.write(await resp.read())
            else:
                raise Exception(f"图片下载失败，状态码: {resp.status}")
