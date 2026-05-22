# Video Script Parse Enhancement

## Overview

This document outlines the proposed enhancements to the video script parsing system to better handle different content types and improve viewer engagement through optimized opening scenes.

---

## 1. Content Type Detection

### 1.1 Content Classification Categories

| Category | Description | Key Characteristics |
|----------|-------------|---------------------|
| **Narrative** | News, stories, event reports | Timeline, event executors, chronological flow |
| **Informative** | Articles, tutorials, explainers | Entity attributes, features, facts, data |
| **Discussive** | Debates, opinions, commentaries | Multiple viewpoints, pros/cons arguments |

### 1.2 Detection Approach

A **hybrid approach** combining keyword-based and LLM-based detection is recommended:

```
High-Confidence Keyword Match → Use Keyword Result
Low-Confidence / Ambiguous → Fallback to LLM Analysis
```

#### Keyword-Based Detection (Fast Pre-Filter)
- **Narrative indicators**: 昨天, 今天, 发生, 宣布, 据报道, 消息人士
- **Informative indicators**: 定义, 特点, 功能, 包括, 相比, 差异
- **Discussive indicators**: 有人认为, 专家表示, 优点, 缺点, 一方面

#### LLM-Based Detection (Contextual Analysis)
- Handles nuanced context and implicit meaning
- Supports multi-lingual content
- Provides confidence scores for classifications

---

## 2. Specialized Parsing Strategies

### 2.1 Narrative Content (News/Stories)

**Extraction Focus:**
- **Timeline events**: Extract chronological sequence with time markers
- **Event executors**: Identify key actors and their actions
- **Turning points**: Capture critical moments and cause-effect relationships
- **Key points**: Extract essential information

**Scene Organization:**
- Organize scenes by chronological flow
- Each scene represents a distinct event or time segment

### 2.2 Informative Content (Articles)

**Extraction Focus:**
- **Entities/targets**: Identify main subjects and their attributes
- **Relationships**: Map connections between entities
- **Key features**: Highlight important characteristics
- **Facts & data**: Extract quantifiable information

**Scene Organization:**
- Organize by topic/subtopic hierarchy
- Logical information flow from overview to details

### 2.3 Discussive Content (Debates/Comments)

**Extraction Focus:**
- **Viewpoints**: Identify different perspectives presented
- **Arguments**: Extract pros and cons for each side
- **Evidence**: Capture supporting examples and data
- **Balance**: Ensure fair representation of all sides

**Scene Organization:**
- Present balanced viewpoints
- Structure for clear comparison and contrast

---

## 3. Enhanced Opening Scene Strategy

### 3.1 Attention-Grabbing Hooks by Content Type

| Content Type | Opening Strategy | Example Hooks |
|--------------|------------------|---------------|
| **Narrative** | Start with dramatic event or surprising fact | "Yesterday at 3 PM, something unprecedented happened..." |
| **Informative** | Pose curiosity-inducing question | "What if I told you AI can write code better than most developers?" |
| **Discussive** | Present provocative statement | "70% of experts disagree on this controversial topic" |

### 3.2 Visual Hook Techniques

- **Narrative**: Dynamic split-screen, rapid zoom, text overlays with statistics
- **Informative**: Mysterious close-ups, spotlight effects, animated question marks
- **Discussive**: Split-screen opposing views, contrasting color schemes, impactful text animations

### 3.3 Audio Hook Techniques

- **Narrative**: Urgent, dramatic tone with time-sensitive language
- **Informative**: Curious, engaging tone with thought-provoking questions
- **Discussive**: Provocative, energetic tone highlighting controversy

### 3.4 Opening Scene Evaluation Metrics

| Metric | Weight | Criteria |
|--------|--------|----------|
| Hook presence | 30% | Question, surprising fact, or provocative statement |
| Dynamic visuals | 25% | Zoom, fast cuts, reveal effects |
| Engaging emotion | 25% | Energetic, curious, or dramatic tone |
| Optimal length | 20% | 20-80 characters for 3-5 second hook |

---

## 4. Enhanced Scene Structure

Extended scene schema with content-type specific fields:

```json
{
  "id": "scene_1",
  "title": "Opening Hook",
  "script": "(curious) Have you ever wondered how AI learns?",
  "duration": 5,
  "start_time": 0,
  "end_time": 5,
  "visual_requirement": "Mysterious close-up of neural network visualization...",
  "keywords": "AI, machine learning, curiosity",
  "emotion": "curious, engaging",
  "content_type": "informative",
  
  // Content-type specific fields:
  "timeline_events": [],           // For narrative content
  "entities": [                   // For informative content
    {"name": "AI", "attributes": {"capability": "learning"}}
  ],
  "viewpoints": []                // For discussive content
}
```

---

## 5. Implementation Roadmap

| Phase | Description | Priority |
|-------|-------------|----------|
| **Phase 1** | Content type detection module | High |
| **Phase 2** | Specialized parsing strategies | High |
| **Phase 3** | Enhanced opening scene generation | Medium |
| **Phase 4** | Opening quality evaluation | Medium |
| **Phase 5** | A/B testing framework for openings | Low |

---

## 6. Expected Benefits

1. **Better Content Adaptation**: Scripts tailored to content type
2. **Higher Engagement**: Optimized opening scenes capture attention
3. **Improved Accuracy**: Hybrid detection handles edge cases
4. **Flexibility**: Works with diverse content sources
5. **Scalability**: LLM-based approach adapts to new content patterns

---

## 7. Integration Points

- `app/services/scene_parser.py`: Add content type detection and specialized parsing
- `app/services/llm.py`: Add content-type-specific prompts
- Scene evaluation module: Add opening scene quality metrics