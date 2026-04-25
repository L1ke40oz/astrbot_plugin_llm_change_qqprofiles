import astrbot.api.message_components as Comp
from astrbot import logger
from astrbot.api import llm_tool
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.event.filter import on_llm_request
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core.star.filter.permission import PermissionType
from astrbot.core.star.star_tools import StarTools

from .status import status_mapping
from .utils import download_image


class QQProfilePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.conf = config
        self.avatar_dir = StarTools.get_data_dir("astrbot_plugin_qqprofile") / "avatar"
        self.avatar_dir.mkdir(parents=True, exist_ok=True)

    async def _apply_nickname(self, event: AstrMessageEvent, nickname: str) -> str:
        nickname = nickname.strip()
        await event.bot.set_qq_profile(nickname=nickname)
        logger.debug(f"已更新QQ昵称：{nickname}")
        return f"已将QQ昵称修改为：{nickname}"

    async def _apply_longnick(self, event: AstrMessageEvent, longnick: str) -> str:
        longnick = longnick.strip()
        await event.bot.set_self_longnick(longNick=longnick)
        logger.debug(f"已更新QQ签名：{longnick}")
        return f"已将QQ签名修改为：{longnick}"

    async def _apply_status(self, event: AstrMessageEvent, status_name: str) -> str:
        status_name = status_name.strip()
        params = status_mapping.get(status_name)
        if not params:
            supported_statuses = "、".join(status_mapping.keys())
            return (
                f"不支持的QQ状态：{status_name}。"
                f"可用状态有：{supported_statuses}"
            )
        await event.bot.set_online_status(
            status=params[0], ext_status=params[1], battery_status=0
        )
        logger.debug(f"已更新QQ状态：{status_name}")
        return f"已将QQ在线状态修改为：{status_name}"

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("设置头像")
    async def set_avatar(self, event: AiocqhttpMessageEvent):
        "将当前消息或引用消息中的图片设置为头像"
        chain = event.get_messages()
        img_url = None
        for seg in chain:
            if isinstance(seg, Comp.Image):
                img_url = seg.url
                break
            if isinstance(seg, Comp.Reply) and seg.chain:
                for reply_seg in seg.chain:
                    if isinstance(reply_seg, Comp.Image):
                        img_url = reply_seg.url
                        break
                if img_url:
                    break
        if not img_url:
            yield event.plain_result("需要引用一张图片")
            return

        await event.bot.set_qq_avatar(file=img_url)
        yield event.plain_result("我换头像啦~")

        save_path = self.avatar_dir / "current.jpg"
        try:
            await download_image(img_url, str(save_path))
            logger.debug(f"头像已保存到：{save_path}")
        except Exception as e:
            logger.error(f"保存头像失败：{e}")

    @llm_tool("qqprofile_set_nickname")
    async def qqprofile_set_nickname(
        self, event: AstrMessageEvent, nickname: str
    ) -> str:
        """修改QQ昵称。

        Args:
            nickname(string): 要设置的新昵称。
        """
        if not nickname or not nickname.strip():
            return "修改QQ昵称失败：nickname 不能为空。"
        return await self._apply_nickname(event, nickname)

    @llm_tool("qqprofile_set_longnick")
    async def qqprofile_set_longnick(
        self, event: AstrMessageEvent, longnick: str
    ) -> str:
        """修改QQ个性签名。

        Args:
            longnick(string): 要设置的新个性签名。
        """
        if not longnick or not longnick.strip():
            return "修改QQ个性签名失败：longnick 不能为空。"
        return await self._apply_longnick(event, longnick)

    @llm_tool("qqprofile_set_status")
    async def qqprofile_set_status(
        self, event: AstrMessageEvent, status_name: str
    ) -> str:
        """修改QQ在线状态。

        Args:
            status_name(string): 要设置的在线状态名称，必须是受支持的状态之一。
        """
        if not status_name or not status_name.strip():
            return "修改QQ在线状态失败：status_name 不能为空。"
        return await self._apply_status(event, status_name)

    @on_llm_request()
    async def on_llm_req(self, event: AstrMessageEvent, request: ProviderRequest):
        if not self.conf.get("inject_profile_prompt", True):
            return

        template = self.conf.get("profile_prompt", "")
        if not template:
            return

        supported_statuses = "、".join(status_mapping.keys())
        request.system_prompt += (
            "\n"
            + template.format(supported_statuses=supported_statuses)
        )
