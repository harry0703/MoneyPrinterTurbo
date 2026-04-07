# 多场景视频处理系统设计规范

## 1. 系统概述

多场景视频处理系统是一个用于处理和生成多场景视频的综合性系统，支持从单个场景视频到完整视频的生成过程。系统通过一系列模块化的函数，实现了视频处理、音频合成、字幕添加等功能，最终生成高质量的视频内容。

## 2. 关键函数职责

### 2.1 场景内部处理函数

| 函数名 | 职责 | 输入参数 | 输出结果 |
|--------|------|----------|----------|
| `process_scene_videos` | 处理单个场景内的视频片段，应用连接模式和过渡效果 | scene_video_paths, video_aspect, video_concat_mode, video_transition_mode, max_clip_duration, local_video_paths | 处理后的视频片段列表 |
| `combine_scene_clips` | 合并单个场景的视频片段，处理时长匹配 | scene_clips, audio_duration | 处理后的视频片段列表 |

### 2.2 多场景处理函数

| 函数名 | 职责 | 输入参数 | 输出结果 |
|--------|------|----------|----------|
| `combine_early_scenes` | 合并多个场景的视频，保持场景顺序 | scene_clips_list, audio_duration | 合并后的视频片段列表 |
| `combine_all_scenes` | 目标视频级别的视频合并，协调整个多场景视频的生成 | task_id, params, scene_results | 最终视频文件路径 |

### 2.3 最终合成函数

| 函数名 | 职责 | 输入参数 | 输出结果 |
|--------|------|----------|----------|
| `finalize_video` | 处理最终合成，添加音频和字幕 | processed_clips, combined_video_path, audio_file, threads | 最终视频文件路径 |
| `generate_video` | 视频生成任务的高级协调函数，协调整个视频生成过程 | video_path, audio_path, subtitle_path, output_file, params, progress_callback | 最终视频文件路径 |

### 2.4 场景级入口函数

| 函数名 | 职责 | 输入参数 | 输出结果 |
|--------|------|----------|----------|
| `build_scene_video` | 场景级别的视频处理入口，协调单个场景的视频生成 | combined_video_path, video_paths, audio_file, video_aspect, video_concat_mode, video_transition_mode, max_clip_duration, threads, scene_info, local_video_paths, intro_video_path | 场景视频文件路径 |

## 3. 函数调用关系

### 3.1 场景级视频生成流程

```
generate_video (场景级任务)
    ↓
build_scene_video
    ↓
process_scene_videos
    ↓
combine_scene_clips
    ↓
finalize_video
    ↓
场景视频文件
```

### 3.2 目标视频级生成流程

```
generate_video (目标视频级任务)
    ↓
combine_all_scenes
    ↓
combine_early_scenes
    ↓
finalize_video
    ↓
完整视频文件
```

### 3.3 详细调用关系

1. **场景内部处理**：
   - `process_scene_videos` 处理单个场景的视频片段，应用连接模式和过渡效果
   - 返回处理后的视频片段列表给 `combine_scene_clips`

2. **场景级别处理**：
   - `combine_scene_clips` 接收 `process_scene_videos` 的输出
   - 处理视频时长与音频时长的匹配
   - 返回处理后的视频片段列表给 `finalize_video`

3. **多场景级别处理**：
   - `combine_early_scenes` 接收多个场景的视频片段列表
   - 按场景顺序合并视频片段
   - 返回合并后的视频片段列表给 `finalize_video`

4. **最终合成**：
   - `finalize_video` 接收 `combine_scene_clips` 或 `combine_early_scenes` 的输出
   - 添加音频和字幕
   - 生成最终视频文件

5. **入口函数**：
   - `build_scene_video` 作为场景级别的入口，调用 `process_scene_videos` → `combine_scene_clips` → `finalize_video`
   - `combine_all_scenes` 作为多场景级别的入口，调用 `combine_early_scenes` → `finalize_video`
   - `generate_video` 作为任务级别的入口，协调整个视频生成过程，根据任务类型调用相应的函数

## 4. 系统流程图

```
┌─────────────────┐     ┌────────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ process_scene_  │     │ combine_scene_     │     │ finalize_       │     │ 场景视频文件     │
│ videos         │────>│ clips             │────>│ video          │────>│                 │
└─────────────────┘     └────────────────────┘     └─────────────────┘     └─────────────────┘
          ↑                      ↑
          │                      │
┌─────────────────┐              │
│ build_scene_    │──────────────┘
│ video          │
└─────────────────┘
          ↑
          │
┌─────────────────┐
│ generate_video  │
│ (场景级任务)    │
└─────────────────┘

┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ 多个场景视频     │     │ combine_early_  │     │ finalize_       │     │ 完整视频文件     │
│ 文件            │────>│ scenes         │────>│ video          │────>│                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘     └─────────────────┘
          ↑                      ↑
          │                      │
┌─────────────────┐              │
│ combine_all_    │──────────────┘
│ scenes         │
└─────────────────┘
          ↑
          │
┌─────────────────┐
│ generate_video  │
│ (目标视频级任务) │
└─────────────────┘
```

## 5. 数据结构

### 5.1 视频参数结构

| 字段名 | 类型 | 描述 |
|--------|------|------|
| `video_subject` | str | 视频主题 |
| `video_aspect` | VideoAspect | 视频 aspect ratio |
| `video_concat_mode` | VideoConcatMode | 视频连接模式 |
| `subtitle_enabled` | bool | 是否启用字幕 |
| `font_name` | str | 字体名称 |
| `font_size` | int | 字体大小 |
| `text_fore_color` | str | 文本前景色 |
| `text_background_color` | str | 文本背景色 |
| `stroke_color` | str | 描边颜色 |
| `stroke_width` | int | 描边宽度 |
| `subtitle_position` | str | 字幕位置 |

### 5.2 场景结果结构

| 字段名 | 类型 | 描述 |
|--------|------|------|
| `scene_id` | str | 场景 ID |
| `scene_index` | int | 场景索引 |
| `audio_file` | str | 音频文件路径 |
| `audio_duration` | float | 音频时长 |
| `subtitle_path` | str | 字幕文件路径 |
| `combined_video_path` | str | 合并后的视频文件路径 |

## 6. 实现细节

### 6.1 视频处理流程

1. **视频片段处理**：
   - 对每个视频片段应用缩放、裁剪等处理
   - 根据需要应用过渡效果
   - 处理视频时长，确保与音频时长匹配

2. **音频处理**：
   - 加载音频文件
   - 调整音频时长以匹配视频时长
   - 将音频添加到视频中

3. **字幕处理**：
   - 解析字幕文件
   - 根据字幕时间戳创建字幕剪辑
   - 将字幕添加到视频中

4. **最终合成**：
   - 合并所有视频片段
   - 添加音频和字幕
   - 生成最终视频文件

### 6.2 错误处理

- 对视频文件加载失败的情况进行处理
- 对音频文件加载失败的情况进行处理
- 对字幕文件解析失败的情况进行处理
- 对视频合成失败的情况进行处理

### 6.3 性能优化

- 使用多线程处理视频合成
- 合理管理内存，及时释放不再使用的资源
- 优化视频编码参数，提高编码效率

## 7. 扩展点

- 支持更多视频过渡效果
- 支持更多字幕样式和位置选项
- 支持视频特效和滤镜
- 支持批量处理多个视频任务

## 8. 总结

多场景视频处理系统通过模块化的设计，实现了从单个场景视频到完整视频的生成过程。系统的函数职责清晰，调用关系合理，代码结构模块化，便于维护和扩展。通过这个系统，可以高效地生成高质量的多场景视频内容。