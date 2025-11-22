import asyncio
import uuid

from wechatpy import WeChatClient
from wechatpy.replies import ImageReply, TextReply, VoiceReply, VideoReply

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.message_components import Image, Plain, Record, Video
from astrbot.api.platform import AstrBotMessage, PlatformMetadata

try:
    import pydub
except Exception:
    logger.warning(
        "检测到 pydub 库未安装，微信公众平台将无法语音收发。如需使用语音，请前往管理面板 -> 控制台 -> 安装 Pip 库安装 pydub。",
    )


class WeixinOfficialAccountPlatformEvent(AstrMessageEvent):
    def __init__(
        self,
        message_str: str,
        message_obj: AstrBotMessage,
        platform_meta: PlatformMetadata,
        session_id: str,
        client: WeChatClient,
    ):
        super().__init__(message_str, message_obj, platform_meta, session_id)
        self.client = client

    @staticmethod
    async def send_with_client(
        client: WeChatClient,
        message: MessageChain,
        user_name: str,
    ):
        pass

    async def split_plain(self, plain: str) -> list[str]:
        """将长文本分割成多个小文本, 每个小文本长度不超过 2048 字符

        Args:
            plain (str): 要分割的长文本
        Returns:
            list[str]: 分割后的文本列表

        """
        if len(plain) <= 2048:
            return [plain]
        result = []
        start = 0
        while start < len(plain):
            # 剩下的字符串长度<2048时结束
            if start + 2048 >= len(plain):
                result.append(plain[start:])
                break

            # 向前搜索分割标点符号
            end = min(start + 2048, len(plain))
            cut_position = end
            for i in range(end, start, -1):
                if i < len(plain) and plain[i - 1] in [
                    "。",
                    "！",
                    "？",
                    ".",
                    "!",
                    "?",
                    "\n",
                    ";",
                    "；",
                ]:
                    cut_position = i
                    break

            # 没找到合适的位置分割, 直接切分
            if cut_position == end and end < len(plain):
                cut_position = end

            result.append(plain[start:cut_position])
            start = cut_position

        return result

    async def send(self, message: MessageChain):
        message_obj = self.message_obj
        active_send_mode = message_obj.raw_message.get("active_send_mode", False)
        for comp in message.chain:
            if isinstance(comp, Plain):
                # Split long text messages if needed
                plain_chunks = await self.split_plain(comp.text)
                for chunk in plain_chunks:
                    if active_send_mode:
                        self.client.message.send_text(message_obj.sender.user_id, chunk)
                    else:
                        reply = TextReply(
                            content=chunk,
                            message=self.message_obj.raw_message["message"],
                        )
                        xml = reply.render()
                        future = self.message_obj.raw_message["future"]
                        assert isinstance(future, asyncio.Future)
                        future.set_result(xml)
                    await asyncio.sleep(0.5)  # Avoid sending too fast
            elif isinstance(comp, Image):
                img_path = await comp.convert_to_file_path()

                with open(img_path, "rb") as f:
                    try:
                        response = self.client.media.upload("image", f)
                    except Exception as e:
                        logger.error(f"微信公众平台上传图片失败: {e}")
                        await self.send(
                            MessageChain().message(f"微信公众平台上传图片失败: {e}"),
                        )
                        return
                    logger.debug(f"微信公众平台上传图片返回: {response}")

                    if active_send_mode:
                        self.client.message.send_image(
                            message_obj.sender.user_id,
                            response["media_id"],
                        )
                    else:
                        reply = ImageReply(
                            media_id=response["media_id"],
                            message=self.message_obj.raw_message["message"],
                        )
                        xml = reply.render()
                        future = self.message_obj.raw_message["future"]
                        assert isinstance(future, asyncio.Future)
                        future.set_result(xml)

            elif isinstance(comp, Record):
                record_path = await comp.convert_to_file_path()
                # 转成amr
                record_path_amr = f"data/temp/{uuid.uuid4()}.amr"
                pydub.AudioSegment.from_wav(record_path).export(
                    record_path_amr,
                    format="amr",
                )

                with open(record_path_amr, "rb") as f:
                    try:
                        response = self.client.media.upload("voice", f)
                    except Exception as e:
                        logger.error(f"微信公众平台上传语音失败: {e}")
                        await self.send(
                            MessageChain().message(f"微信公众平台上传语音失败: {e}"),
                        )
                        return
                    logger.info(f"微信公众平台上传语音返回: {response}")

                    if active_send_mode:
                        self.client.message.send_voice(
                            message_obj.sender.user_id,
                            response["media_id"],
                        )
                    else:
                        reply = VoiceReply(
                            media_id=response["media_id"],
                            message=self.message_obj.raw_message["message"],
                        )
                        xml = reply.render()
                    future = self.message_obj.raw_message["future"]
                    assert isinstance(future, asyncio.Future)
                    future.set_result(xml)

            elif isinstance(comp, Video):
                video_path = await comp.convert_to_file_path()

                with open(video_path, "rb") as f:
                    try:
                        response = self.client.media.upload("video", f)
                    except Exception as e:
                        logger.error(f"微信公众平台上传视频失败: {e}")
                        await self.send(
                            MessageChain().message(f"微信公众平台上传视频失败: {e}"),
                        )
                        return
                    logger.debug(f"微信公众平台上传视频返回: {response}")

                    if active_send_mode:
                        # 微信公众号主动发送视频消息
                        try:
                            self.client.message.send_video(
                                message_obj.sender.user_id,
                                response["media_id"],
                            )
                        except AttributeError:
                            # 如果 send_video 方法不存在，尝试使用 media_id 发送
                            logger.warning("微信公众平台可能不支持主动发送视频消息")
                            await self.send(
                                MessageChain().message("微信公众平台不支持主动发送视频消息"),
                            )
                    else:
                        # 被动回复视频消息
                        # 微信公众号视频消息必须包含 title 和 description，否则会显示为 "Share Message"
                        reply = VideoReply(
                            media_id=response["media_id"],
                            message=self.message_obj.raw_message["message"],
                        )
                        # 通过属性设置 title 和 description
                        reply.title = "视频"
                        reply.description = "视频消息"
                        xml = reply.render()
                        logger.debug(f"视频消息 XML: {xml}")
                        future = self.message_obj.raw_message["future"]
                        assert isinstance(future, asyncio.Future)
                        future.set_result(xml)

            else:
                logger.warning(f"还没实现这个消息类型的发送逻辑: {comp.type}。")

        await super().send(message)

    async def send_streaming(self, generator, use_fallback: bool = False):
        buffer = None
        async for chain in generator:
            if not buffer:
                buffer = chain
            else:
                buffer.chain.extend(chain.chain)
        if not buffer:
            return None
        buffer.squash_plain()
        await self.send(buffer)
        return await super().send_streaming(generator, use_fallback)
