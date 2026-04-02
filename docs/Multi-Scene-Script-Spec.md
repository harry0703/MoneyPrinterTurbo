# Multi-Scene Script Generation Implementation

## 1. Current Implementation

### 1.1 Core Features

The current multi-scene script generation implementation focuses on creating structured, visually-rich storyboard scripts from user input. Key features include:

- **LLM-powered scene division** based on semantic structure
- **Audio-first approach** with natural spoken dialogue
- **Visual transformation** using metaphors and dynamic elements
- **Technical content handling** for code and specialized terms
- **Multi-language support** based on user selection

### 1.2 Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        User Input                               │
│ (Video subject or full script)                                   │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│              LLM Processing (Single Call)                        │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 1. Content Analysis                                    │    │
│  │ 2. Scene Division based on semantic structure          │    │
│  │ 3. Visual Element Generation                           │    │
│  │ 4. Dialogue Optimization                              │    │
│  │ 5. Keyword Extraction                                 │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Multi-Scene Script Output                       │
└─────────────────────────────────────────────────────────────────┘
```

## 2. Detailed Implementation

### 2.1 Core Functions

#### 2.1.1 `generate_multi_scene_script`

```python
def generate_multi_scene_script(
    video_content: str,
    language: str = "",
    max_scenes: int = 12
) -> str:
    """
    Generate multi-scene script for video.
    
    Args:
        video_content: The content of the video (can be a subject or full script)
        language: Language for the script
        max_scenes: Maximum number of scenes to generate
    
    Returns:
        Multi-scene script text with visual descriptions, camera movements, and emotion annotations
    """
```

#### 2.1.2 `parse_multi_scene_script`

```python
def parse_multi_scene_script(script_text: str) -> List[Dict]:
    """
    Parse multi-scene script text into structured data.
    
    Input format:
        ###  Scene [Number]: [Scene Core Theme]
        - **Core Keywords**: Keyword 1, Keyword 2, Keyword 3
        - **Visual (Visual Elements)**: 
            - **Visual Element 1**: Detailed description
            - **Visual Element 2**: Detailed description
        - **Audio (Dialogue Script)**: 
            - ([Emotion Marker]) Dialogue content
    
    Returns:
        List of scene dictionaries with structure:
        [
            {
                "id": "scene_1",
                "title": "Scene core theme",
                "visual": "Visual description",
                "audio": "Dialogue content",
                "emotion": "Emotion marker",
                "script": "Complete script",
                "keywords": "Keywords"
            },
            ...
        ]
    """
```

### 2.2 LLM Prompt Structure

The system uses a comprehensive prompt to guide the LLM in generating high-quality multi-scene scripts:

#### 2.2.1 Role and Goal
- **Role**: Senior video director and storyboard designer with 10 years of experience
- **Goal**: Transform text content into visually impactful, logically coherent storyboard scripts

#### 2.2.2 Key Constraints
1. **Audio-First Principle**: Dialogue is core, visuals enhance the dialogue
2. **Semantic Scene Division**: 5-15 scenes with logical boundaries
3. **Visual Transformation**: Use visual metaphors, dynamic graphics, or scene reenactment
4. **Dialogue Optimization**: Natural spoken language with emotion markers
5. **Technical Content Handling**: Plain language explanations for technical terms
6. **Keyword Extraction**: 3-5 core keywords per scene

#### 2.2.3 Output Format
```
###  Scene [Number]: [Scene Core Theme]
- **Core Keywords**: Keyword 1, Keyword 2, Keyword 3
- **Visual (Visual Elements)**:
    - **Visual Element 1**: Detailed description
    - **Visual Element 2**: Detailed description
- **Audio (Dialogue Script)**:
    - ([Emotion Marker]) Dialogue content
```

## 3. Workflow

### 3.1 Input Processing
1. User provides video subject or full script
2. System detects input type and language
3. Input is passed to LLM for scene generation

### 3.2 Script Generation
1. LLM analyzes content and divides into semantic scenes
2. For each scene, generates:
   - Scene title and core theme
   - Visual elements and camera movements
   - Natural spoken dialogue with emotion markers
   - Core keywords

### 3.3 Output Processing
1. Generated script is parsed into structured scene data
2. Each scene is processed for audio generation
3. Visual requirements are extracted for video material search

## 4. Technical Content Handling

The system includes specialized handling for technical content:

- **Terminology**: Replaces technical terms with plain language explanations
- **Code/Symbols**: Avoids direct reading of code or symbols
- **Complex Concepts**: Uses analogies and examples to explain
- **Readability**: Keeps sentences short and conversational

## 5. Language Support

The system supports multi-language script generation:
- **Input Language**: Detects or uses user-specified language
- **Output Language**: Generates all content in the selected language
- **Localization**: Adapts visual and dialogue elements to cultural context

## 6. Fallback Mechanism

If LLM generation fails, the system provides a fallback mechanism:
- Generates a basic 3-scene structure
- Includes opening, main content, and conclusion scenes
- Uses generic but effective visual descriptions

## 7. Integration Points

### 7.1 Scene Parser Integration
- `scene_parser.py` calls `generate_multi_scene_script` for script processing
- Parses generated script into structured scene data

### 7.2 Task Processing Integration
- `task.py` uses multi-scene scripts for video generation
- Processes each scene sequentially for audio and video creation

## 8. Configuration

### 8.1 Current Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_scenes` | int | 12 | Maximum number of scenes to generate |
| `language` | string | "" | Language for script generation |

### 8.2 Future Configuration Options

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `scene_count` | int | 8 | Target number of scenes |
| `visual_style` | string | "mixed" | Visual style preference |
| `dialogue_style` | string | "natural" | Dialogue style preference |

## 9. Performance Metrics

| Metric | Current | Notes |
|--------|---------|-------|
| Generation time | 3-10s | Depends on content length |
| Success rate | >95% | Fallback for failures |
| Scene quality | High | Semantic coherence and visual richness |

## 10. Usage Examples

### 10.1 Basic Usage
```python
from app.services import llm

# Generate multi-scene script from subject
script = llm.generate_multi_scene_script(
    video_content="The benefits of regular exercise",
    language="Chinese"
)

# Parse script into scenes
scenes = llm.parse_multi_scene_script(script)
```

### 10.2 Full Script Input
```python
from app.services import llm

# Generate multi-scene script from full script
full_script = """Regular exercise has numerous benefits..."""
script = llm.generate_multi_scene_script(
    video_content=full_script,
    language="English"
)
```

## 11. Limitations

- **Scene Count**: Limited to maximum 15 scenes
- **Content Length**: Works best with 500-3000 characters
- **Technical Content**: May require additional processing for highly specialized topics
- **Visual Complexity**: Visual descriptions are text-based only

## 12. Future Roadmap

1. **Semantic Clustering**: Implement advanced scene boundary detection
2. **Content Type Adaptation**: Optimize for different content types
3. **Visual Preview**: Generate thumbnail previews for scenes
4. **Interactive Editing**: Allow users to adjust scene boundaries
5. **Multi-Modal Input**: Support image and audio inputs

## 13. Appendix

### 13.1 Glossary

- **Scene**: A distinct segment of the video with specific visual and audio elements
- **Visual Element**: A component of the scene's visual composition
- **Emotion Marker**: Indication of the tone or emotion for the dialogue
- **Core Keywords**: Key concepts associated with each scene

### 13.2 References

- LLM Prompt Engineering Best Practices
- Video Storyboarding Techniques
- Audio-Visual Content Creation Guidelines

---

## 14. Appendix: Multi-Scene Script Prompt Template

# Role
你是一位拥有10年经验的资深视频编导和分镜脚本设计师。你擅长将各种类型的文本内容（无论是干货文章、故事还是营销文案）转化为视觉冲击力强、逻辑严密的分镜脚本。

# Goal
请阅读用户提供的【原始文案】，将其改编为一份标准化的**场景化分镜脚本**。

# Constraints & Workflow
1. **逻辑拆解**：分析文案的起承转合，将其拆解为若干个独立的场景。
2. **视觉转化**：
    - 拒绝枯燥的画面（如“一个人说话”）。
    - 必须运用**视觉隐喻**（用具体物体表达抽象概念）、**动态图形**或**场景重现**。
    - 画面描述需包含：主体、环境、动作、运镜方式（如特写、推拉）。
3. **口播优化**：将原文改写为自然的口语，并标注语气/情绪。
4. **格式强制**：**必须**严格遵守下方的【输出模板】格式，不得随意增减字段。

---

# Output Template (请严格按此格式输出)

###  场景 [序号]：[场景核心主题]
- **Visual (画面视觉)**：
    - [详细描述画面内容，包括主体、动作、环境、光影、运镜建议]
    - [如果是抽象概念，请描述具体的视觉隐喻]
- **Audio (口播文案)**：
    - ([情绪/语气标注]) [具体的口播台词]

---

# Few-Shot Example (参考示例)
*如果输入是“拖延症是因为大脑在逃避痛苦”，输出应包含：*
###  场景 1：逃避痛苦的本能
- **Visual (画面视觉)**：
    - 画面左侧是一个快乐的小猴子玩偶在抢方向盘，右侧是一个理性的掌舵人（人类）被绑在柱子上。背景是混乱的游乐场。
    - 运镜：快速推拉，表现混乱感。
- **Audio (口播文案)**：
    - ([生动、比喻]) 拖延症其实不是时间管理问题，而是情绪管理问题。就像你大脑里住了一只抢方向盘的猴子...