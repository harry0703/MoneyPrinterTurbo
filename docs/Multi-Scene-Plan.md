# 多场景模式实现计划

## 1. 现有模块分析

### 1.1 核心服务模块

#### app/services/task.py
**当前功能**：
- `generate_script()` - 生成视频脚本
- `generate_terms()` - 生成视频关键词
- `generate_audio()` - 生成音频
- `generate_subtitle()` - 生成字幕
- `get_video_materials()` - 获取视频素材
- `generate_final_videos()` - 生成最终视频
- `start()` - 主流程控制

**可重用部分**：
- `generate_audio()` - 完全可重用，用于为每个场景生成音频
- `generate_subtitle()` - 完全可重用，用于为每个场景生成字幕
- `get_video_materials()` - 完全可重用，用于为每个场景获取视频素材
- `generate_final_videos()` - 部分可重用，最终合成步骤可重用

**需要修改部分**：
- `start()` - 需要重构以支持多场景流程
- `generate_script()` - 需要扩展以支持多场景脚本生成
- `generate_terms()` - 需要扩展以支持多场景关键词生成

#### app/services/llm.py
**当前功能**：
- `_generate_response()` - 通用的LLM响应生成
- `generate_script()` - 生成视频脚本
- `generate_terms()` - 生成视频关键词

**可重用部分**：
- `_generate_response()` - 完全可重用，底层LLM调用逻辑

**需要修改部分**：
- `generate_script()` - 需要扩展以支持多场景脚本生成
- `generate_terms()` - 需要扩展以支持多场景关键词生成

**需要新增部分**：
- `generate_multi_scene_script()` - 新增：生成多场景脚本
- `convert_to_multi_scene()` - 新增：将单场景脚本转换为多场景格式
- `parse_multi_scene_script()` - 新增：解析多场景脚本结构

#### app/services/video.py
**当前功能**：
- `combine_videos()` - 合并视频片段
- `generate_video()` - 生成最终视频（添加字幕、背景音乐等）

**可重用部分**：
- `combine_videos()` - 完全可重用，用于合并每个场景的视频片段
- `generate_video()` - 完全可重用，用于最终视频合成

**需要新增部分**：
- `combine_scene_clips()` - 新增：合并所有场景片段

### 1.2 数据模型模块

#### app/models/schema.py
**需要新增**：
- `Scene` - 场景数据模型
- `MultiSceneParams` - 多场景参数模型

### 1.3 UI模块

#### webui/Main.py
**需要修改**：
- 添加多场景模式开关
- 修改文案显示逻辑以支持多场景格式
- 修改关键词显示逻辑以支持多场景格式

## 2. 详细修改计划

### 2.1 LLM服务扩展 (app/services/llm.py)

#### 新增函数：generate_multi_scene_script()
```python
def generate_multi_scene_script(
    video_subject: str, 
    language: str = "", 
    max_scenes: int = 5
) -> List[Dict]:
    """
    Generate multi-scene script for video.
    
    Returns:
        List of scene dictionaries with structure:
        [
            {
                "id": "scene_1",
                "camera": "镜头描述",
                "start_time": 0,
                "end_time": 5,
                "title": "场景标题",
                "script": "主播文案"
            },
            ...
        ]
    """
```

#### 新增函数：convert_to_multi_scene()
```python
def convert_to_multi_scene(
    video_script: str,
    video_subject: str = ""
) -> List[Dict]:
    """
    Convert single-scene script to multi-scene format.
    
    Returns:
        List of scene dictionaries
    """
```

#### 新增函数：parse_multi_scene_script()
```python
def parse_multi_scene_script(script_text: str) -> List[Dict]:
    """
    Parse multi-scene script text into structured data.
    
    Input format:
        (镜头: 镜头描述)
        【0-5秒 场景标题】
        主播文案内容...
    
    Returns:
        List of scene dictionaries
    """
```

#### 修改函数：generate_terms()
```python
def generate_terms(
    video_subject: str, 
    video_script: str, 
    amount: int = 5,
    scene_index: int = None  # 新增参数：场景索引
) -> List[str]:
    """
    Generate search terms for stock videos.
    If scene_index is provided, generate terms for specific scene.
    """
```

### 2.2 任务服务扩展 (app/services/task.py)

#### 新增函数：generate_scene_script()
```python
def generate_scene_script(task_id, params):
    """
    Generate multi-scene script.
    If multi-scene mode is enabled, generate multi-scene script.
    Otherwise, use existing generate_script() logic.
    """
```

#### 新增函数：generate_scene_terms()
```python
def generate_scene_terms(task_id, params, scenes):
    """
    Generate terms for each scene.
    Returns list of terms for each scene.
    """
```

#### 新增函数：process_scene()
```python
def process_scene(task_id, params, scene, scene_index, total_scenes):
    """
    Process a single scene:
    1. Generate audio for scene
    2. Generate subtitle for scene
    3. Get video materials for scene
    4. Combine scene video clip (without BGM)
    
    Returns:
        Scene result with video clip path, audio path, subtitle path
    """
```

#### 新增函数：combine_all_scenes()
```python
def combine_all_scenes(task_id, params, scene_results):
    """
    Combine all scene clips into final video.
    1. Concatenate all scene video clips
    2. Add background music
    3. Generate final video
    
    Returns:
        Final video path
    """
```

#### 修改函数：start()
```python
def start(task_id, params: VideoParams, stop_at: str = "video"):
    """
    Main task entry point.
    Modified to support multi-scene mode.
    
    Flow:
    1. Check if multi-scene mode is enabled
    2. If enabled:
       a. Generate multi-scene script
       b. Generate terms for each scene
       c. Process each scene (audio, subtitle, materials, clip)
       d. Combine all scenes with BGM
    3. If disabled:
       a. Use existing single-scene flow
    """
```

### 2.3 视频服务扩展 (app/services/video.py)

#### 新增函数：combine_scene_clips()
```python
def combine_scene_clips(
    scene_clips: List[str],
    output_file: str,
    params: VideoParams
) -> str:
    """
    Combine all scene video clips into one video.
    
    Args:
        scene_clips: List of scene video clip paths
        output_file: Output file path
        params: Video parameters
    
    Returns:
        Path to combined video
    """
```

#### 可重用函数：generate_video()
```python
# 现有函数完全可重用
# 用于最终视频合成（添加字幕、背景音乐等）
def generate_video(
    video_path: str,
    audio_path: str,
    subtitle_path: str,
    output_file: str,
    params: VideoParams,
):
    """
    Generate final video with subtitle and BGM.
    This function can be reused for final video generation.
    """
```

### 2.4 数据模型扩展 (app/models/schema.py)

#### 新增模型：Scene
```python
class Scene(BaseModel):
    id: str = ""
    camera: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    title: str = ""
    script: str = ""
    keywords: List[str] = []
    video_clips: List[str] = []
    audio_file: str = ""
    subtitle_file: str = ""
```

#### 新增模型：MultiSceneParams
```python
class MultiSceneParams(BaseModel):
    enabled: bool = False
    max_scenes: int = 10
    scene_duration_min: int = 5
    scene_duration_max: int = 30
```

#### 扩展模型：VideoParams
```python
class VideoParams(BaseModel):
    # ... existing fields ...
    multi_scene_enabled: bool = False  # 新增
    multi_scene_params: MultiSceneParams = None  # 新增
```

### 2.5 UI扩展 (webui/Main.py)

#### 新增UI组件：多场景模式开关
```python
# 在文案设置区域添加
multi_scene_enabled = st.checkbox(
    "启用多场景模式",
    value=False,
    help="启用后将视频划分为多个场景，每个场景有独立的视觉需求"
)
```

#### 修改UI逻辑：文案显示
```python
# 根据多场景模式显示不同格式的文案
if multi_scene_enabled:
    # 显示多场景格式文案
    # 场景之间用分隔线区分
else:
    # 显示普通文案
```

#### 修改UI逻辑：关键词显示
```python
# 根据多场景模式显示不同格式的关键词
if multi_scene_enabled:
    # 显示多场景关键词
    # 不同场景用分号分隔，同一场景用逗号分隔
else:
    # 显示普通关键词
```

## 3. 处理流程对比

### 3.1 现有流程（单场景）

```
1. 生成脚本 (generate_script)
   ↓
2. 生成关键词 (generate_terms)
   ↓
3. 生成音频 (generate_audio)
   ↓
4. 生成字幕 (generate_subtitle)
   ↓
5. 获取视频素材 (get_video_materials)
   ↓
6. 合成最终视频 (generate_final_videos)
   ├── 合并视频片段 (combine_videos)
   └── 添加字幕和BGM (generate_video)
```

### 3.2 多场景流程

```
1. 生成多场景脚本 (generate_multi_scene_script)
   ├── 如果提供主题：直接生成多场景脚本
   └── 如果提供文案：转换为多场景格式
   ↓
2. 为每个场景生成关键词 (generate_scene_terms)
   ↓
3. 遍历每个场景 (process_scene)
   ├── 生成场景音频 (generate_audio) [重用]
   ├── 生成场景字幕 (generate_subtitle) [重用]
   ├── 获取场景视频素材 (get_video_materials) [重用]
   └── 合成场景片段 (combine_videos) [重用，不含BGM]
   ↓
4. 合并所有场景片段 (combine_scene_clips) [新增]
   ↓
5. 生成最终视频 (generate_video) [重用，添加BGM]
```

## 4. 关键算法分析

### 4.1 多场景脚本解析算法

**输入**：多场景格式文本
```
(镜头: 主播坐在电脑前)
【0-5秒 痛点切入】
各位朋友们，2026年了...

(镜头: 特写屏幕)
【5-25秒 方案一】
第一招，也是最核心的...
```

**解析步骤**：
1. 识别场景分隔符：`(镜头:` 标记
2. 提取镜头描述：`镜头:` 后的内容
3. 识别时间标记：`【数字-数字秒` 格式
4. 提取场景标题：时间标记后的文字
5. 提取场景文案：直到下一个场景标记或文本结束

**输出**：场景列表
```python
[
    {
        "camera": "主播坐在电脑前",
        "start_time": 0,
        "end_time": 5,
        "title": "痛点切入",
        "script": "各位朋友们，2026年了..."
    },
    {
        "camera": "特写屏幕",
        "start_time": 5,
        "end_time": 25,
        "title": "方案一",
        "script": "第一招，也是最核心的..."
    }
]
```

### 4.2 场景关键词生成算法

**输入**：场景对象（包含镜头描述、标题、文案）

**生成策略**：
1. 分析镜头描述中的视觉元素
2. 分析文案中的关键概念
3. 结合视频主题生成搜索关键词
4. 限制每个场景的关键词数量（3-5个）

**输出**：关键词列表
```python
["computer screen", "coding", "programming", "developer"]
```

### 4.3 场景片段合成算法

**输入**：场景视频素材列表、场景音频、场景字幕

**合成步骤**：
1. 调用现有 `combine_videos()` 合并视频片段
2. 不添加背景音乐
3. 保存为临时场景视频文件

**输出**：场景视频文件路径

### 4.4 最终视频合成算法

**输入**：所有场景视频文件列表

**合成步骤**：
1. 按顺序连接所有场景视频
2. 添加统一的背景音乐
3. 生成最终视频文件

**输出**：最终视频文件路径

## 5. 实现优先级

### 5.1 第一阶段：核心功能
1. **LLM服务扩展**
   - 实现 `generate_multi_scene_script()`
   - 实现 `parse_multi_scene_script()`
   - 实现 `convert_to_multi_scene()`

2. **数据模型扩展**
   - 定义 `Scene` 模型
   - 定义 `MultiSceneParams` 模型
   - 扩展 `VideoParams` 模型

### 5.2 第二阶段：任务处理
1. **任务服务扩展**
   - 实现 `generate_scene_script()`
   - 实现 `generate_scene_terms()`
   - 实现 `process_scene()`
   - 实现 `combine_all_scenes()`
   - 修改 `start()` 函数

### 5.3 第三阶段：视频处理
1. **视频服务扩展**
   - 实现 `combine_scene_clips()`
   - 验证现有函数可重用性

### 5.4 第四阶段：UI集成
1. **UI扩展**
   - 添加多场景模式开关
   - 实现多场景文案显示
   - 实现多场景关键词显示

### 5.5 第五阶段：测试优化
1. **功能测试**
   - 测试多场景脚本生成
   - 测试场景处理流程
   - 测试最终视频合成

2. **性能优化**
   - 优化场景处理并发性
   - 优化内存使用
   - 优化视频合成效率

## 6. 风险评估与缓解策略

### 6.1 技术风险

**风险1**：LLM生成的多场景脚本格式不稳定
- **缓解策略**：
  - 提供明确的格式模板和示例
  - 实现容错解析逻辑
  - 支持手动编辑和调整

**风险2**：场景视频素材不匹配
- **缓解策略**：
  - 优化关键词生成算法
  - 提供素材预览功能
  - 支持手动选择素材

**风险3**：处理时间过长
- **缓解策略**：
  - 实现场景级并发处理
  - 提供进度实时反馈
  - 支持断点续传

### 6.2 兼容性风险

**风险**：影响现有单场景模式
- **缓解策略**：
  - 使用配置开关控制模式
  - 保持现有API向后兼容
  - 充分测试单场景模式

## 7. 测试计划

### 7.1 单元测试
- 测试多场景脚本解析
- 测试场景关键词生成
- 测试场景片段合成

### 7.2 集成测试
- 测试完整多场景流程
- 测试单场景与多场景切换
- 测试边界情况

### 7.3 用户验收测试
- 测试UI交互
- 测试生成视频质量
- 测试性能表现

## 8. 总结

### 8.1 可完全重用的模块
- `app/services/voice.py` - TTS服务
- `app/services/material.py` - 素材下载服务
- `app/services/subtitle.py` - 字幕生成服务
- `app/services/video.py::combine_videos()` - 视频片段合并
- `app/services/video.py::generate_video()` - 最终视频生成

### 8.2 需要扩展的模块
- `app/services/llm.py` - 添加多场景脚本生成和解析
- `app/services/task.py` - 添加多场景任务处理逻辑
- `app/models/schema.py` - 添加多场景数据模型
- `webui/Main.py` - 添加多场景UI支持

### 8.3 需要新增的模块
- 多场景脚本解析器
- 场景片段合成器
- 多场景配置管理

通过合理的模块划分和功能复用，可以在不影响现有功能的基础上，高效地实现多场景模式功能。
