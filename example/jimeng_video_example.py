import os
import time
import asyncio
from dataclasses import dataclass
from typing import Literal, List, Optional
# 通过 pip install 'volcengine-python-sdk[ark]' 安装方舟SDK
from volcenginesdkarkruntime import Ark
from volcenginesdkarkruntime.types.content_generation.content_generation_task import ContentGenerationTask
from volcenginesdkarkruntime.types.content_generation.content_generation_task_id import ContentGenerationTaskID

# 请确保您已将 API Key 存储在环境变量 ARK_API_KEY 中
# 初始化Ark客户端，从环境变量中读取您的API Key
client: Ark = Ark(
    # 此为默认路径，您可根据业务所在地域进行配置
    base_url="https://ark.cn-beijing.volces.com/api/v3",
    # 从环境变量中获取您的 API Key。此为默认方式，您可根据需要进行修改
    api_key=os.environ.get("ARK_API_KEY", "3b27c504-3ea7-4b09-9852-159d547a24d5"),
)

@dataclass
class TaskMsg:
    status: Literal["succeeded", "failed"]
    video_url: Optional[str] = None

async def generate_video(
    prompt: str,
    duration: int,
    camera_fixed: bool = False,
    watermark: bool = True
) -> TaskMsg:
    content_text: str = \
        prompt +    \
        " --duration " + str(duration) + \
        " --camerafixed " + "true" if camera_fixed else "false" + \
        " --watermark" + "true" if watermark else "false"
    
    # 创建内容
    create_result: ContentGenerationTaskID = client.content_generation.tasks.create(
        model="doubao-seedance-1-5-pro-251215", # 模型 Model ID 已为您填入
        content=[
            {
                "type": "text",
                "text": content_text
            },
        ]
    )
    
    # 保存一份任务ID
    task_id: str = create_result.id

    # 然后轮询内容
    while True: 
        get_result: ContentGenerationTask = client.content_generation.tasks.get(task_id=task_id)
        status = get_result.status
        if status == "succeeded":
            print("----- task succeeded -----")
            print(get_result)
            return TaskMsg(
                status=status
            )

        elif status == "failed":
            print("----- task failed -----")
            print(f"Error: {get_result.error}")
            return TaskMsg(
                status=status,
                video_url=get_result.content.video_url
            )


if __name__ == "__main__":
    print("----- create request -----")
    create_result = client.content_generation.tasks.create(
        model="doubao-seedance-1-5-pro-251215", # 模型 Model ID 已为您填入
        content=[
            {
                # 文本提示词与参数组合
                "type": "text",
                "text": "人工智能的普及正在重塑就业市场，它替代了许多重复性和程序化的工作岗位，导致部分行业出现失业现象  --duration 5 --camerafixed false --watermark false"
            },
        ]
    )
    print(create_result)

    # 轮询查询部分
    print("----- polling task status -----")
    task_id = create_result.id
    while True: 
        get_result: ContentGenerationTask = client.content_generation.tasks.get(task_id=task_id)
        status = get_result.status
        if status == "succeeded":
            print("----- task succeeded -----")
            print(get_result)
            break
        elif status == "failed":
            print("----- task failed -----")
            print(f"Error: {get_result.error}")
            break
        else:
            print(f"Current status: {status}, Retrying after 3 seconds...")
            time.sleep(3)

# 更多操作请参考下述网址
# 查询视频生成任务列表：https://www.volcengine.com/docs/82379/1521675
# 取消或删除视频生成任务：https://www.volcengine.com/docs/82379/1521720