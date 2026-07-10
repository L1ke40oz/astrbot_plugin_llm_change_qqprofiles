import os
import shutil
from pathlib import Path

import astrbot.api.message_components as Comp
from astrbot import logger
from astrbot.api import llm_tool
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.event.filter import on_llm_request
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.star.star_tools import StarTools

from .status import diy_face_mapping, status_mapping
from .utils import download_image


class QQProfilePlugin(Star):
    # 工具名 -> 对应的配置开关键
    _TOOL_SWITCH_MAP = {
        "qqprofile_set_avatar": "enable_set_avatar",
        "qqprofile_set_nickname": "enable_set_nickname",
        "qqprofile_set_longnick": "enable_set_longnick",
        "qqprofile_set_status": "enable_set_status",
        "qqprofile_set_diy_status": "enable_set_diy_status",
    }
    # 默认值需与 _conf_schema.json 中保持一致
    _TOOL_SWITCH_DEFAULTS = {
        "enable_set_avatar": False,
        "enable_set_nickname": False,
        "enable_set_longnick": True,
        "enable_set_status": True,
        "enable_set_diy_status": True,
    }

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.conf = config
        self.avatar_dir = (
            StarTools.get_data_dir("astrbot_plugin_llm_change_qqprofiles") / "avatar"
        )
        self.avatar_dir.mkdir(parents=True, exist_ok=True)

    async def initialize(self) -> None:
        """按配置启用/禁用四个工具。工具注册后默认为激活状态，这里只需关闭被禁用的项。"""
        for tool_name, switch_key in self._TOOL_SWITCH_MAP.items():
            enabled = self.conf.get(
                switch_key, self._TOOL_SWITCH_DEFAULTS[switch_key]
            )
            if enabled:
                # 确保之前被关闭过的工具在配置启用后恢复激活
                self.context.activate_llm_tool(tool_name)
                logger.debug(f"已启用QQ资料工具：{tool_name}")
            else:
                self.context.deactivate_llm_tool(tool_name)
                logger.info(f"已按配置禁用QQ资料工具：{tool_name}")

    def _own_plugin_name(self) -> str:
        """Best-effort resolve this plugin's registered name for session checks."""
        try:
            from astrbot.core.star.star import star_map

            meta = star_map.get(self.__class__.__module__)
            if meta and meta.name:
                return meta.name
        except Exception:
            pass
        return "astrbot_plugin_llm_change_qqprofiles"

    async def _session_inactive(self, umo: str) -> bool:
        """Whether this plugin is disabled for the session via AstrBot custom rules.

        AstrBot's per-session plugin management only filters command / message
        handlers, not lifecycle hooks (on_llm_request) or llm_tool calls. So we
        query the session config ourselves and skip when disabled. Fails open
        (returns False) when the API is unavailable.
        """
        try:
            from astrbot.core.star.session_plugin_manager import (
                SessionPluginManager,
            )
        except Exception:
            return False
        try:
            enabled = await SessionPluginManager.is_plugin_enabled_for_session(
                umo, self._own_plugin_name()
            )
            return not enabled
        except Exception:
            return False

    def _get_real_event(self, event_or_ctx) -> AstrMessageEvent:
        """兼容 AstrBot v4.25+ 的 ContextWrapper，提取真正的 AstrMessageEvent"""
        # 如果是新版本传来的套娃 ContextWrapper
        if hasattr(event_or_ctx, "context"):
            ctx = event_or_ctx.context
            if hasattr(ctx, "event"):
                return ctx.event
            elif hasattr(ctx, "message_obj"):
                return ctx.message_obj
        # 如果已经是真正的 event (兼容老版本)
        return event_or_ctx

    def _extract_image_url(self, event: AstrMessageEvent) -> str | None:
        chain = event.get_messages()
        for seg in chain:
            if isinstance(seg, Comp.Image):
                return seg.url
            if isinstance(seg, Comp.Reply) and seg.chain:
                for reply_seg in seg.chain:
                    if isinstance(reply_seg, Comp.Image):
                        return reply_seg.url
        return None

    async def _apply_avatar(
        self, event: AstrMessageEvent, path: str | None = None
    ) -> str:
        # 规范化路径，避免转义字符问题
        if path:
            path = os.path.normpath(path)
        
        img_url = path or self._extract_image_url(event)
        if not img_url:
            return "修改QQ头像失败：当前消息或引用消息中没有图片。"

        # 判断是否为 GIF
        is_gif = False
        if path:
            is_gif = Path(path).suffix.lower() == '.gif'
        elif img_url:
            is_gif = img_url.lower().endswith('.gif')

        # 根据是否为 GIF 选择保存路径
        if is_gif:
            save_path = self.avatar_dir / "current.gif"
        else:
            save_path = self.avatar_dir / "current.jpg"

        # 先下载/复制到本地，再上传
        try:
            if path:
                shutil.copyfile(path, save_path)
            else:
                await download_image(img_url, str(save_path))
            logger.debug(f"头像已保存到：{save_path}")
        except Exception as e:
            logger.error(f"保存头像失败：{e}")
            return f"修改QQ头像失败：保存图片时出错 ({e})"

        # 使用本地文件路径上传
        try:
            await event.bot.set_qq_avatar(file=str(save_path))
        except Exception as e:
            logger.error(f"设置头像失败：{e}")
            return f"修改QQ头像失败：上传时出错 ({e})"

        return "已将QQ头像改成当前消息或引用消息中的图片。"

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

    async def _apply_diy_status(
        self, event: AstrMessageEvent, wording: str, emoji: str | None = None
    ) -> str:
        wording = wording.strip()
        emoji = (emoji or "").strip()
        face_id = diy_face_mapping.get(emoji)
        if emoji and face_id is None:
            supported_emojis = "、".join(diy_face_mapping.keys()) or "（暂无）"
            return (
                f"不支持的状态表情：{emoji}。"
                f"可用表情有：{supported_emojis}"
            )
        await event.bot.set_diy_online_status(
            face_id=face_id if face_id is not None else "",
            face_type=1,
            wording=wording,
        )
        logger.debug(f"已更新QQ自定义状态：emoji={emoji or '无'} wording={wording}")
        if emoji:
            return f"已将QQ自定义状态修改为：{emoji}（{wording}）"
        return f"已将QQ自定义状态文字修改为：{wording}"

    _DISABLED_MSG = "（本会话已停用 QQ 资料修改功能，未执行任何修改。）"

    @llm_tool("qqprofile_set_avatar")
    async def qqprofile_set_avatar(
        self, event: AstrMessageEvent, path: str | None = None, **kwargs
    ) -> str:
        """将QQ头像修改为当前消息或引用消息中的图片。

        Args:
            path(string): 当前消息图片转换出的本地文件路径；未提供时会回退到当前消息或引用消息中的图片。
        """
        real_event = self._get_real_event(event)
        if await self._session_inactive(real_event.unified_msg_origin):
            return self._DISABLED_MSG
        return await self._apply_avatar(real_event, path)

    @llm_tool("qqprofile_set_nickname")
    async def qqprofile_set_nickname(
        self, event: AstrMessageEvent, nickname: str, **kwargs
    ) -> str:
        """修改QQ昵称。

        Args:
            nickname(string): 要设置的新昵称。
        """
        real_event = self._get_real_event(event)
        if await self._session_inactive(real_event.unified_msg_origin):
            return self._DISABLED_MSG
        if not nickname or not nickname.strip():
            return "修改QQ昵称失败：nickname 不能为空。"
        return await self._apply_nickname(real_event, nickname)

    @llm_tool("qqprofile_set_longnick")
    async def qqprofile_set_longnick(
        self, event: AstrMessageEvent, longnick: str, **kwargs
    ) -> str:
        """修改QQ个性签名。

        Args:
            longnick(string): 要设置的新个性签名。
        """
        real_event = self._get_real_event(event)
        if await self._session_inactive(real_event.unified_msg_origin):
            return self._DISABLED_MSG
        if not longnick or not longnick.strip():
            return "修改QQ个性签名失败：longnick 不能为空。"
        return await self._apply_longnick(real_event, longnick)

    @llm_tool("qqprofile_set_status")
    async def qqprofile_set_status(
        self, event: AstrMessageEvent, status_name: str, **kwargs
    ) -> str:
        """修改QQ在线状态。

        Args:
            status_name(string): 要设置的在线状态名称，必须是受支持的状态之一。
        """
        real_event = self._get_real_event(event)
        if await self._session_inactive(real_event.unified_msg_origin):
            return self._DISABLED_MSG
        if not status_name or not status_name.strip():
            return "修改QQ在线状态失败：status_name 不能为空。"
        return await self._apply_status(real_event, status_name)

    @llm_tool("qqprofile_set_diy_status")
    async def qqprofile_set_diy_status(
        self, event: AstrMessageEvent, wording: str, emoji: str | None = None, **kwargs
    ) -> str:
        """修改QQ自定义在线状态，可设置一句自定义状态文字，并可选地搭配一个状态表情。

        Args:
            wording(string): 要展示的自定义状态文字，应简短自然。
            emoji(string): 可选，状态表情名称，必须是受支持的表情之一；不传则只设置文字。
        """
        real_event = self._get_real_event(event)
        if await self._session_inactive(real_event.unified_msg_origin):
            return self._DISABLED_MSG
        if not wording or not wording.strip():
            return "修改QQ自定义状态失败：wording 不能为空。"
        return await self._apply_diy_status(real_event, wording, emoji)

    @on_llm_request()
    async def on_llm_req(self, event: AstrMessageEvent, request: ProviderRequest, *args, **kwargs):
        real_event = self._get_real_event(event)
        if await self._session_inactive(real_event.unified_msg_origin):
            return
        if not self.conf.get("inject_profile_prompt", True):
            return

        template = self.conf.get("profile_prompt", "")
        if not template:
            return

        supported_statuses = "、".join(status_mapping.keys())
        supported_diy_emojis = "、".join(diy_face_mapping.keys()) or "（暂无）"
        request.system_prompt += "\n" + template.format(
            supported_statuses=supported_statuses,
            supported_diy_emojis=supported_diy_emojis,
        )