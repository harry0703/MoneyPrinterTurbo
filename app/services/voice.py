import asyncio
from concurrent.futures import ThreadPoolExecutor
from xml.sax.saxutils import unescape
from edge_tts.submaker import mktimestamp
from loguru import logger
from edge_tts import submaker, SubMaker
import edge_tts
from app.utils import utils


def tts(text: str, voice_name: str, voice_file: str) -> [SubMaker, None]:
    logger.info(f"start, voice name: {voice_name}")
    try:
        async def _do() -> SubMaker:
            communicate = edge_tts.Communicate(text, voice_name)
            sub_maker = edge_tts.SubMaker()
            with open(voice_file, "wb") as file:
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        file.write(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        sub_maker.create_sub((chunk["offset"], chunk["duration"]), chunk["text"])
            return sub_maker

        sub_maker = asyncio.run(_do())
        logger.info(f"completed, output file: {voice_file}")
        return sub_maker
    except Exception as e:
        logger.error(f"failed, error: {e}")
        return None


def create_subtitle(sub_maker: submaker.SubMaker, text: str, subtitle_file: str):
    """
    优化字幕文件
    1. 将字幕文件按照标点符号分割成多行
    2. 逐行匹配字幕文件中的文本
    3. 生成新的字幕文件
    """

    def formatter(idx: int, start_time: float, end_time: float, sub_text: str) -> str:
        """
        1
        00:00:00,000 --> 00:00:02,360
        跑步是一项简单易行的运动
        """
        start_t = mktimestamp(start_time).replace(".", ",")
        end_t = mktimestamp(end_time).replace(".", ",")
        return (
            f"{idx}\n"
            f"{start_t} --> {end_t}\n"
            f"{sub_text}\n"
        )

    start_time = -1.0
    sub_items = []
    sub_index = 0

    script_lines = utils.split_string_by_punctuations(text)

    sub_line = ""
    for _, (offset, sub) in enumerate(zip(sub_maker.offset, sub_maker.subs)):
        _start_time, end_time = offset
        if start_time < 0:
            start_time = _start_time

        sub = unescape(sub)
        sub_line += sub
        if sub_line == script_lines[sub_index]:
            sub_index += 1
            sub_items.append(formatter(
                idx=sub_index,
                start_time=start_time,
                end_time=end_time,
                sub_text=sub_line,
            ))
            start_time = -1.0
            sub_line = ""

    with open(subtitle_file, "w", encoding="utf-8") as file:
        file.write("\n".join(sub_items))


def get_audio_duration(sub_maker: submaker.SubMaker):
    """
    获取音频时长
    """
    if not sub_maker.offset:
        return 0.0
    return sub_maker.offset[-1][1] / 10000000


if __name__ == "__main__":

    async def _do():
        temp_dir = utils.storage_dir("temp")

        voice_names = [
            # 女性
            "zh-CN-XiaoxiaoNeural",
            "zh-CN-XiaoyiNeural",
            # 男性
            "zh-CN-YunyangNeural",
            "zh-CN-YunxiNeural",
        ]
        text = """
        预计未来3天深圳冷空气活动频繁，未来两天持续阴天有小雨，出门带好雨具；
        10-11日持续阴天有小雨，日温差小，气温在13-17℃之间，体感阴凉；
        12日天气短暂好转，早晚清凉；
            """

        for voice_name in voice_names:
            voice_file = f"{temp_dir}/tts-{voice_name}.mp3"
            subtitle_file = f"{temp_dir}/tts.mp3.srt"
            sub_maker = tts(text=text, voice_name=voice_name, voice_file=voice_file)
            create_subtitle(sub_maker=sub_maker, text=text, subtitle_file=subtitle_file)
            audio_duration = get_audio_duration(sub_maker)
            print(f"voice: {voice_name}, audio duration: {audio_duration}s")


    loop = asyncio.get_event_loop_policy().get_event_loop()
    try:
        loop.run_until_complete(_do())
    finally:
        loop.close()
