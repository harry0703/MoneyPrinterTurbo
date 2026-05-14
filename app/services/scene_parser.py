"""
Scene parser module for multi-scene video generation.
Handles intelligent detection, parsing, and quality evaluation of scene scripts.
"""
import re
import json
from typing import List, Dict, Any, Optional, Tuple
from uuid import uuid4
from loguru import logger


# Language code to full name mapping
LANGUAGE_CODE_MAP = {
    "zh": "Chinese",
    "en": "English",
    "de": "German",
    "pt": "Portuguese",
    "ru": "Russian",
    "tr": "Turkish",
    "vi": "Vietnamese",
    "auto": None,  # Auto detect
    None: None,  # No language specified, auto detect
}


def normalize_language(language: str) -> Optional[str]:
    """
    Normalize language code to full language name.
    
    Args:
        language: Language code or full name
        
    Returns:
        Normalized language name (e.g., "Chinese") or None for auto-detect
    """
    if language is None:
        return None
    if language in LANGUAGE_CODE_MAP:
        return LANGUAGE_CODE_MAP[language]
    # If already a full name, return as is
    return language


# Enhanced time marker patterns
def get_time_patterns() -> List[Tuple[str, str]]:
    """
    Get all time marker patterns with their types.
    Returns list of (pattern, type) tuples.
    Only matches patterns that are likely scene headers (with brackets or at line start).
    """
    return [
        # Chinese time patterns - must be in brackets or at line start
        (r"【\s*\d{1,2}\s*-\s*\d{1,2}\s*秒\s*[^】]*】", "chinese_bracket"),  # 【0-5秒 痛点切入】
        (r"【\s*\d{1,2}\s*秒\s*-\s*\d{1,2}\s*秒\s*[^】]*】", "chinese_bracket_full"),  # 【5秒-25秒 方案一】
        (r"^\s*\d{1,2}\s*-\s*\d{1,2}\s*秒", "chinese_range_line"),  # 0-5秒 at line start
        (r"^\s*\d{1,2}\s*秒\s*-\s*\d{1,2}\s*秒", "chinese_range_full_line"),  # 5秒-25秒 at line start
        (r"时长[:：]\s*\d+", "chinese_duration"),  # 时长：5
        
        # English time patterns - must be in brackets or at line start
        (r"\[\s*\d{1,2}\s*-\s*\d{1,2}\s*s\s*[^\]]*\]", "english_bracket"),  # [0-5s Intro]
        (r"\[\s*\d{1,2}\s*s\s*-\s*\d{1,2}\s*s\s*[^\]]*\]", "english_bracket_full"),  # [5s-25s Scene 1]
        (r"^\s*\d{1,2}\s*-\s*\d{1,2}\s*s", "english_range_line"),  # 0-5s at line start
        (r"duration[:\s]+\d+", "english_duration"),  # duration: 5
        
        # Timestamp patterns
        (r"\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}", "timestamp_range"),  # 00:00-00:05
        (r"\[\s*\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}\s*\]", "timestamp_bracket"),  # [00:00-00:05]
    ]


def extract_time_range(text: str) -> Optional[Tuple[int, int]]:
    """
    Extract time range from text.
    Returns (start_seconds, end_seconds) or None.
    """
    # Pattern: 0-5秒 or 0-5s
    match = re.search(r"(\d{1,2})\s*-\s*(\d{1,2})\s*(?:秒|s)", text)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    
    # Pattern: 5秒-25秒 or 5s-25s
    match = re.search(r"(\d{1,2})\s*(?:秒|s)\s*-\s*(\d{1,2})\s*(?:秒|s)", text)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    
    # Pattern: 00:00-00:05 (timestamp)
    match = re.search(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})", text)
    if match:
        start_sec = int(match.group(1)) * 60 + int(match.group(2))
        end_sec = int(match.group(3)) * 60 + int(match.group(4))
        return (start_sec, end_sec)
    
    # Pattern: single number with 秒/s
    match = re.search(r"(\d+)\s*(?:秒|s)", text)
    if match:
        seconds = int(match.group(1))
        return (0, seconds)
    
    return None


def extract_scene_title(text: str) -> str:
    """
    Extract scene title from time marker text.
    """
    # Remove time patterns
    title = re.sub(r"【\s*\d{1,2}\s*-\s*\d{1,2}\s*秒\s*", "", text)
    title = re.sub(r"【\s*\d{1,2}\s*秒\s*-\s*\d{1,2}\s*秒\s*", "", text)
    title = re.sub(r"【", "", title)
    title = re.sub(r"】", "", title)
    title = re.sub(r"\[\s*\d{1,2}\s*-\s*\d{1,2}\s*s\s*", "", title)
    title = re.sub(r"\[", "", title)
    title = re.sub(r"\]", "", title)
    title = re.sub(r"\d{1,2}\s*-\s*\d{1,2}\s*(?:秒|s)", "", title)
    title = re.sub(r"\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}", "", title)
    
    return title.strip() or "Scene"


def extract_visual_requirement(paragraph: str) -> str:
    """
    Extract visual requirements from paragraph.
    Looks for keywords like: 镜头, 画面, 视觉, 特写, 展示, 主播, screen, shot, visual
    """
    visual_keywords = [
        "镜头", "画面", "视觉", "特写", "展示", "主播", "屏幕", "背景",
        "shot", "screen", "visual", "close-up", "display", "background",
        "scene", "view", "camera", "主播坐在", "屏幕上是", "展示一张",
        "特写屏幕", "镜头：", "(镜头：", "【镜头】", "[shot]"
    ]
    
    lines = paragraph.split("\n")
    visual_lines = []
    
    for line in lines:
        line_stripped = line.strip()
        if any(keyword in line_stripped for keyword in visual_keywords):
            visual_lines.append(line_stripped)
    
    # Also look for parenthetical visual cues
    visual_pattern = r"[（(]([^）)]*(?:镜头|画面|特写|展示|主播|shot|screen|visual|close-up)[^）)]*)[）)]"
    matches = re.findall(visual_pattern, paragraph)
    visual_lines.extend(matches)
    
    return " ".join(visual_lines) if visual_lines else ""


def extract_keywords_from_script(script: str) -> str:
    """
    Extract keywords from script content.
    """
    # Look for explicit keyword sections
    keyword_patterns = [
        r"关键词[：:]\s*([^\n]+)",
        r"标签[：:]\s*([^\n]+)",
        r"keywords?[：:]\s*([^\n]+)",
        r"tags?[：:]\s*([^\n]+)",
    ]
    
    for pattern in keyword_patterns:
        match = re.search(pattern, script, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    
    # Extract hashtags as keywords
    hashtags = re.findall(r"#(\w+)", script)
    if hashtags:
        return ", ".join(hashtags)
    
    return ""


def detect_scene_format(script: str) -> Dict[str, Any]:
    """
    Detect if the script is already divided into scenes.
    Enhanced version with time marker detection.
    
    Returns:
        Dict with keys:
        - is_divided: bool - whether script is already divided
        - scene_count: int - number of detected scenes
        - detection_method: str - how scenes were detected
        - confidence: float - confidence level (0-1)
        - time_markers: List[Dict] - detected time markers with positions
    """
    if not script or not script.strip():
        return {
            "is_divided": False,
            "scene_count": 0,
            "detection_method": "empty",
            "confidence": 0.0,
            "time_markers": []
        }
    
    script_lower = script.lower()
    time_markers = []
    
    # Check for enhanced time patterns
    time_patterns = get_time_patterns()
    for pattern, pattern_type in time_patterns:
        matches = re.finditer(pattern, script, re.IGNORECASE)
        for match in matches:
            time_range = extract_time_range(match.group())
            if time_range:
                time_markers.append({
                    "text": match.group(),
                    "type": pattern_type,
                    "start": match.start(),
                    "end": match.end(),
                    "time_range": time_range,
                    "title": extract_scene_title(match.group())
                })
    
    # Remove duplicates and sort by position
    seen_ranges = set()
    unique_markers = []
    for marker in time_markers:
        key = (marker["time_range"][0], marker["time_range"][1])
        if key not in seen_ranges:
            seen_ranges.add(key)
            unique_markers.append(marker)
    
    time_markers = sorted(unique_markers, key=lambda x: x["start"])
    
    # Traditional detection patterns
    scene_markers = [
        r"场景\s*\d+",
        r"scene\s*\d+",
        r"第[一二三四五六七八九十\d]+[幕场]",
        r"\[scene\s*\d+\]",
        r"\[场景\s*\d+\]"
    ]
    
    marker_count = 0
    for pattern in scene_markers:
        matches = re.findall(pattern, script_lower, re.IGNORECASE)
        marker_count += len(matches)
    
    # Check for paragraph separation
    paragraphs = [p.strip() for p in script.split("\n\n") if p.strip()]
    paragraph_count = len(paragraphs)
    
    # Determine if divided
    is_divided = False
    detection_method = "none"
    confidence = 0.0
    scene_count = 1
    
    if time_markers:
        is_divided = True
        detection_method = "time_markers"
        scene_count = len(time_markers)
        confidence = min(0.95 + len(time_markers) * 0.01, 0.99)
    elif marker_count >= 2:
        is_divided = True
        detection_method = "scene_markers"
        scene_count = marker_count
        confidence = min(0.9 + marker_count * 0.02, 0.98)
    elif paragraph_count >= 3 and paragraph_count <= 10:
        is_divided = True
        detection_method = "paragraphs"
        scene_count = paragraph_count
        confidence = min(0.7 + paragraph_count * 0.02, 0.85)
    
    return {
        "is_divided": is_divided,
        "scene_count": scene_count,
        "detection_method": detection_method,
        "confidence": confidence,
        "time_markers": time_markers,
        "paragraphs": paragraphs if is_divided else []
    }


def extract_scenes_from_divided_script(script: str, detection_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract scenes from a script that is already divided.
    Enhanced version with time marker support.
    """
    scenes = []
    time_markers = detection_result.get("time_markers", [])
    
    if time_markers:
        # Use time markers to split script
        for i, marker in enumerate(time_markers):
            start_pos = marker["end"]
            end_pos = time_markers[i + 1]["start"] if i + 1 < len(time_markers) else len(script)
            
            scene_text = script[start_pos:end_pos].strip()
            time_range = marker["time_range"]
            duration = time_range[1] - time_range[0] if time_range else estimate_duration(scene_text)
            
            # Extract visual requirements and clean up script
            visual_req = extract_visual_requirement(scene_text)
            
            # Clean script: remove visual cue lines
            script_lines = []
            for line in scene_text.split("\n"):
                line_stripped = line.strip()
                # Skip lines that are visual cues (start with parenthesis or contain visual keywords at line start)
                if line_stripped.startswith("(") or line_stripped.startswith("（"):
                    continue
                if any(line_stripped.startswith(keyword) for keyword in ["镜头", "画面", "特写", "展示"]):
                    continue
                script_lines.append(line)
            
            clean_script = "\n".join(script_lines).strip()
            
            scene = {
                "id": str(uuid4()),
                "title": marker.get("title", f"Scene {i+1}"),
                "script": clean_script,
                "duration": duration,
                "start_time": time_range[0] if time_range else 0,
                "end_time": time_range[1] if time_range else duration,
                "visual_requirement": visual_req,
                "keywords": extract_keywords_from_script(scene_text)
            }
            scenes.append(scene)
    else:
        # Fall back to paragraph splitting
        paragraphs = detection_result.get("paragraphs", [])
        if not paragraphs:
            paragraphs = [p.strip() for p in script.split("\n\n") if p.strip()]
        
        for i, paragraph in enumerate(paragraphs):
            scene = {
                "id": str(uuid4()),
                "title": f"Scene {i+1}",
                "script": paragraph,
                "duration": estimate_duration(paragraph),
                "start_time": 0,
                "end_time": 0,
                "visual_requirement": extract_visual_requirement(paragraph),
                "keywords": extract_keywords_from_script(paragraph)
            }
            scenes.append(scene)
    
    return scenes


def estimate_duration(script: str) -> int:
    """
    Estimate scene duration based on script length.
    Assumes average speaking rate of 5-6 characters per second for Chinese
    (fast-paced broadcast style), 3 words per second for English.
    """
    char_count = len(script.strip())
    # Average 5.5 characters per second for fast-paced broadcast, minimum 3 seconds, maximum 30 seconds
    duration = max(3, min(30, int(char_count / 5.5)))
    return duration


def check_time_continuity(scenes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Check if scene times are continuous without gaps.
    Returns list of issues.
    """
    issues = []
    
    if not scenes or len(scenes) < 2:
        return issues
    
    # Sort scenes by start time
    sorted_scenes = sorted(scenes, key=lambda x: x.get("start_time", 0))
    
    total_duration = 0
    for i, scene in enumerate(sorted_scenes):
        start_time = scene.get("start_time", 0)
        end_time = scene.get("end_time", 0)
        
        if start_time > 0 or end_time > 0:
            # Check for time gap with previous scene
            if i > 0:
                prev_end = sorted_scenes[i-1].get("end_time", 0)
                if start_time > prev_end:
                    gap = start_time - prev_end
                    if gap > 1:  # Allow 1 second tolerance
                        issues.append({
                            "type": "time_gap",
                            "params": {
                                "scene": i + 1,
                                "gap": gap,
                                "prev_end": prev_end,
                                "curr_start": start_time
                            }
                        })
                elif start_time < prev_end:
                    overlap = prev_end - start_time
                    issues.append({
                        "type": "time_overlap",
                        "params": {
                            "scene": i + 1,
                            "overlap": overlap,
                            "prev_end": prev_end,
                            "curr_start": start_time
                        }
                    })
            
            total_duration = max(total_duration, end_time)
    
    # Check total duration
    if total_duration > 0:
        if total_duration < 30:
            issues.append({
                "type": "total_duration_short",
                "params": {"duration": total_duration, "recommended_min": 30}
            })
        elif total_duration > 300:
            issues.append({
                "type": "total_duration_long",
                "params": {"duration": total_duration, "recommended_max": 300}
            })
    
    return issues


def check_script_duration_match(scene: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Check if script length matches duration.
    Assumes 4 characters per second for Chinese.
    """
    script = scene.get("script", "")
    duration = scene.get("duration", 10)
    
    # Count actual content (exclude visual cues and markers)
    content_lines = []
    for line in script.split("\n"):
        line = line.strip()
        # Skip visual cue lines
        if not any(keyword in line for keyword in ["镜头", "画面", "特写", "展示", "shot", "screen", "visual"]):
            if not line.startswith("(") and not line.startswith("（"):
                content_lines.append(line)
    
    content = " ".join(content_lines)
    char_count = len(content)
    
    # Expected characters: 5.5 chars per second (fast-paced broadcast)
    expected_chars = duration * 5.5
    
    # More lenient thresholds for broadcast scripts
    # Allow 30% shorter to 100% longer (fast-paced broadcast can have more content)
    if char_count < expected_chars * 0.3:
        return {
            "type": "script_too_short",
            "params": {
                "actual": char_count,
                "expected": expected_chars,
                "duration": duration
            }
        }
    elif char_count > expected_chars * 2.0:
        return {
            "type": "script_too_long",
            "params": {
                "actual": char_count,
                "expected": expected_chars,
                "duration": duration
            }
        }
    
    return None


def evaluate_scenes(scenes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Evaluate the quality of parsed scenes across enhanced dimensions.
    
    New dimensions:
    - time_marker_completeness: 20% - Each scene has clear time markers
    - time_continuity: 15% - Scene times are continuous without gaps
    - visual_completeness: 20% - Each scene has visual guidance
    - script_duration_match: 25% - Script length matches duration
    - scene_structure_completeness: 20% - Scene has title, time, script, visual
    
    Returns:
        Dict with keys:
        - total_score: float (0-100)
        - individual_scores: Dict[str, float]
        - auto_accept: bool
        - auto_reject: bool
        - issues: List[Dict]
    """
    if not scenes:
        return {
            "total_score": 0,
            "individual_scores": {},
            "auto_accept": False,
            "auto_reject": True,
            "issues": [{"type": "no_scenes"}]
        }
    
    scores = {
        "time_marker_completeness": 0,
        "time_continuity": 0,
        "visual_completeness": 0,
        "script_duration_match": 0,
        "scene_structure_completeness": 0
    }
    issues = []
    
    # 1. Time marker completeness score (20%)
    scenes_with_time = sum(1 for s in scenes 
                          if s.get("start_time", 0) > 0 or s.get("end_time", 0) > 0)
    scores["time_marker_completeness"] = (scenes_with_time / len(scenes)) * 100
    if scores["time_marker_completeness"] < 80:
        issues.append({
            "type": "time_marker_incomplete",
            "params": {"count": scenes_with_time, "total": len(scenes)}
        })
    
    # 2. Time continuity score (15%)
    time_issues = check_time_continuity(scenes)
    if time_issues:
        scores["time_continuity"] = max(0, 100 - len(time_issues) * 20)
        issues.extend(time_issues)
    else:
        scores["time_continuity"] = 100
    
    # 3. Visual completeness score (20%)
    scenes_with_visual = sum(1 for s in scenes 
                            if s.get("visual_requirement") and len(s["visual_requirement"]) > 5)
    scores["visual_completeness"] = (scenes_with_visual / len(scenes)) * 100
    if scores["visual_completeness"] < 80:
        issues.append({
            "type": "visual_incomplete",
            "params": {"count": scenes_with_visual, "total": len(scenes)}
        })
    
    # 4. Script-duration match score (25%)
    matched_scenes = 0
    for scene in scenes:
        match_issue = check_script_duration_match(scene)
        if match_issue is None:
            matched_scenes += 1
        else:
            issues.append(match_issue)
    
    scores["script_duration_match"] = (matched_scenes / len(scenes)) * 100
    
    # 5. Scene structure completeness score (20%)
    complete_scenes = 0
    for scene in scenes:
        has_title = scene.get("title") and scene["title"] != f"Scene {scenes.index(scene) + 1}"
        has_time = scene.get("start_time", 0) > 0 or scene.get("end_time", 0) > 0
        has_script = len(scene.get("script", "")) >= 20
        has_visual = len(scene.get("visual_requirement", "")) >= 5
        
        if has_title and has_time and has_script and has_visual:
            complete_scenes += 1
    
    scores["scene_structure_completeness"] = (complete_scenes / len(scenes)) * 100
    if scores["scene_structure_completeness"] < 80:
        issues.append({
            "type": "structure_incomplete",
            "params": {"count": complete_scenes, "total": len(scenes)}
        })
    
    # Calculate weighted total score
    weights = {
        "time_marker_completeness": 0.20,
        "time_continuity": 0.15,
        "visual_completeness": 0.20,
        "script_duration_match": 0.25,
        "scene_structure_completeness": 0.20
    }
    
    total_score = sum(scores[key] * weights[key] for key in scores)
    
    return {
        "total_score": total_score,
        "individual_scores": scores,
        "auto_accept": total_score >= 85,
        "auto_reject": total_score < 60,
        "issues": issues
    }


def parse_script_with_llm(script: str, language: str = None) -> List[Dict[str, Any]]:
    """
    Parse script using LLM to divide it into scenes.
    
    Args:
        script: Script text to parse
        language: Language for the generated content
    """
    import app.services.llm as llm_service
    
    # Normalize language code to full name (e.g., "zh" -> "Chinese")
    # This is important for proper language comparisons in scene generation
    language = normalize_language(language)
    
    logger.info(f"Starting to parse script with LLM, script length: {len(script)}, language: {language}")
    
    # Generate multi-scene script using LLM
    # Use script as both subject and script since we want to process the entire script
    multi_scene_script = llm_service.generate_multi_scene_script(video_content=script, language=language)
    logger.info(f"Generated multi-scene script: {multi_scene_script[:500]}...")
    
    # Parse the generated multi-scene script
    scenes_data = llm_service.parse_multi_scene_script(multi_scene_script)
    logger.info(f"Parsed {len(scenes_data)} scenes from multi-scene script")
    
    # Convert to the expected format with additional fields
    scenes = []
    current_time = 0
    
    for i, scene_data in enumerate(scenes_data):
        scene_script = scene_data.get("script", scene_data.get("audio", ""))
        # Extract emotion markers from script (e.g., "(叙述性、略带规划感) 台词内容")
        import re
        emotion_match = re.match(r'^\(([^\)]+)\)\s*(.*)', scene_script)
        emotion = scene_data.get("emotion", "")
        
        if emotion_match:
            extracted_emotion = emotion_match.group(1)
            cleaned_script = emotion_match.group(2)
            # Merge extracted emotion with existing emotion
            if extracted_emotion and not emotion:
                emotion = extracted_emotion
            elif extracted_emotion and emotion:
                emotion = f"{emotion}, {extracted_emotion}"
            scene_script = cleaned_script
        
        duration = estimate_duration(scene_script)
        
        # 获取视觉需求，如果为空则使用LLM生成
        visual_requirement = scene_data.get("visual", scene_data.get("camera", ""))
        
        # 如果视觉需求为空，使用LLM生成
        if not visual_requirement or visual_requirement.strip() == "":
            # Build visual prompt based on selected language
            if language == "Chinese":
                logger.warning(f"[Scene {i+1} Visual Requirements Empty] Attempting to generate visual requirements using LLM...")
                visual_prompt = f"为以下视频台词生成纯文本视觉需求，要求：1. 内容简洁规范；2. 包含画面主体、环境背景、人物动作或物体变化、运镜方式；3. 直接输出纯文本内容，不使用任何特殊标记和格式：{scene_script[:200]}"
            else:
                logger.warning(f"[Scene {i+1} Visual Requirements Empty] Attempting to generate visual requirements using LLM...")
                visual_prompt = f"Generate pure text visual requirements for the following video lines. Requirements: 1. Concise and standard content; 2. Include scene subject, environment background, character actions or object changes, camera movement; 3. Directly output pure text content without any special markers or formats: {scene_script[:200]}"
            
            try:
                visual_response = llm_service._generate_response(visual_prompt)
                if visual_response and "Error: " not in visual_response:
                    # Clean generated content, remove special markers
                    visual_requirement = visual_response.strip()
                    # Remove possible special markers
                    import re
                    visual_requirement = re.sub(r'[#*]+', '', visual_requirement)
                    visual_requirement = visual_requirement.strip()
                    # Ensure content is reasonable
                    if len(visual_requirement) < 20:
                        if language == "Chinese":
                            visual_requirement = f"场景 {i+1} 的视觉需求"
                            logger.warning(f"[场景{i+1}视觉需求过短] 使用默认占位符")
                        else:
                            visual_requirement = f"Visual requirements for Scene {i+1}"
                            logger.warning(f"[Scene {i+1} Visual Requirements Too Short] Using default placeholder")
                    else:
                        if language == "Chinese":
                            logger.info(f"[场景{i+1}视觉需求生成成功] {visual_requirement[:100]}...")
                        else:
                            logger.info(f"[Scene {i+1} Visual Requirements Generated Successfully] {visual_requirement[:100]}...")
                else:
                    if language == "Chinese":
                        visual_requirement = f"场景 {i+1} 的视觉需求"
                        logger.error(f"[场景{i+1}视觉需求生成失败] 使用默认占位符")
                    else:
                        visual_requirement = f"Visual requirements for Scene {i+1}"
                        logger.error(f"[Scene {i+1} Visual Requirements Generation Failed] Using default placeholder")
            except Exception as e:
                if language == "Chinese":
                    visual_requirement = f"场景 {i+1} 的视觉需求"
                    logger.error(f"[场景{i+1}视觉需求生成异常] {str(e)}")
                else:
                    visual_requirement = f"Visual requirements for Scene {i+1}"
                    logger.error(f"[Scene {i+1} Visual Requirements Generation Exception] {str(e)}")
        else:
            logger.info(f"[Scene {i+1} Visual Requirement Exists] {visual_requirement[:100]}...")
        
        # 获取关键词，如果为空则使用LLM生成
        keywords = scene_data.get("keywords", "")
        if not keywords or keywords.strip() == "":
            # Generate keywords using LLM
            logger.info(f"Scene {i+1} - Generating keywords...")
            # Use scene title or first few words as video subject to avoid passing the entire script
            scene_subject = scene_data.get("title", "") or scene_script[:50].strip()
            keywords_list = llm_service.generate_scene_terms(
                video_subject=scene_subject,  # Use scene title or short script snippet as context
                scene_script=scene_script,
                scene_camera=visual_requirement,
                amount=5
            )
            keywords = ", ".join(keywords_list) if isinstance(keywords_list, list) else ""
            logger.info(f"Scene {i+1} - Generated keywords: {keywords}")
        else:
            logger.info(f"[Scene {i+1} Keywords Exists] {keywords}")
        
        scene = {
            "id": str(uuid4()),
            "title": scene_data.get("title", f"Scene {i+1}"),
            "script": scene_script,  # This will be used for audio generation
            "duration": duration,
            "start_time": current_time,
            "end_time": current_time + duration,
            "visual_requirement": visual_requirement,  # LLM-generated visual requirements
            "keywords": keywords,  # LLM-generated keywords
            "emotion": emotion  # Extracted emotion markers
        }
        logger.info(f"Scene {i+1} - Final scene data: visual_requirement='{scene['visual_requirement']}', keywords='{scene['keywords']}', emotion='{scene['emotion']}'")
        scenes.append(scene)
        current_time += duration
    
    # Fallback to paragraph-based parsing if LLM parsing fails
    if not scenes:
        logger.error("=" * 60)
        logger.error("[LLM Parsing Failed] Cannot use LLM to generate scenes, falling back to paragraph splitting mode")
        logger.error("=" * 60)
        
        paragraphs = [p.strip() for p in script.split("\n\n") if p.strip()]
        
        # Limit the number of paragraphs to a reasonable range (5-16)
        max_scenes = 16
        min_scenes = 5
        if len(paragraphs) > max_scenes:
            logger.warning(f"Found {len(paragraphs)} paragraphs, limiting to {max_scenes} scenes")
            paragraphs = paragraphs[:max_scenes]
        elif len(paragraphs) < min_scenes:
            logger.warning(f"Found {len(paragraphs)} paragraphs, which is less than the recommended minimum of {min_scenes} scenes")
        
        for i, paragraph in enumerate(paragraphs):
            duration = estimate_duration(paragraph)
            
            # 检查内容是否适合口播
            unsuitable_patterns = [
                ("Load ", "文件加载指令"),
                ("# When ", "Markdown标题"),
                ("#", "Markdown标记"),
                ("1.", "列表项"),
                ("2.", "列表项"),
                ("3.", "列表项"),
                ("4.", "列表项"),
                ("5.", "列表项"),
                ("```", "代码块"),
                ("references/", "文件路径"),
                ("SKILL.md", "文件名"),
                ("You are an", "指令语句"),
                ("Load '", "文件加载指令"),
                ("Step ", "步骤指令"),
                ("Ask the user", "用户询问指令"),
                ("Fill the template", "模板填充指令"),
            ]
            
            is_unsuitable = False
            unsuitable_reason = ""
            for pattern, reason in unsuitable_patterns:
                if pattern in paragraph:
                    is_unsuitable = True
                    unsuitable_reason = reason
                    break
            
            if is_unsuitable:
                logger.warning(f"[Unsuitable for Voiceover] Skipping content containing '{unsuitable_reason}': {paragraph[:80]}...")
                continue
            
            # Generate more meaningful visual requirements
            import app.services.llm as llm_service
            visual_prompt = f"Generate pure text visual requirements for the following video script. Requirements: 1. Concise and standard content; 2. Include scene subject, environment background, character actions or object changes, camera movement; 3. Directly output pure text content without any special markers or formats: {paragraph}"
            try:
                visual_response = llm_service._generate_response(visual_prompt)
                if visual_response and "Error: " in visual_response:
                    logger.error(f"[Visual Requirement Generation Failed] {visual_response}")
                    visual_requirement = f"Visual requirement for Scene {i+1}"
                else:
                    visual_requirement = visual_response.strip()
            except Exception as e:
                logger.error(f"[Visual Requirement Generation Failed] {str(e)}")
                visual_requirement = f"Visual requirement for Scene {i+1}"
            
            # Generate keywords
            fallback_subject = paragraph[:50].strip()
            keywords_list = llm_service.generate_scene_terms(
                video_subject=fallback_subject,
                scene_script=paragraph,
                scene_camera=visual_requirement,
                amount=5
            )
            
            if isinstance(keywords_list, str) and "Error: " in keywords_list:
                logger.error(f"[Keywords Generation Failed] {keywords_list}")
                keywords = ""
            else:
                keywords = ", ".join(keywords_list) if isinstance(keywords_list, list) else ""
            
            # Check if video lines are suitable for voiceover
            if len(paragraph) < 20:
                logger.warning(f"[Video Lines May Not Be Suitable for Voiceover] Content too short ({len(paragraph)} chars): {paragraph[:80]}...")
            
            # Create scene object
            scene = {
                "id": str(uuid4()),
                "title": f"Scene {i+1}",
                "script": paragraph,  # This will be used for audio generation
                "duration": duration,
                "start_time": current_time,
                "end_time": current_time + duration,
                "visual_requirement": visual_requirement,
                "keywords": keywords
            }
            scenes.append(scene)
            logger.info(f"[Scene {i+1} Created Successfully] Lines length: {len(paragraph)} chars, Estimated duration: {duration} seconds")
            current_time += duration
    
    # Limit the number of scenes to a reasonable range (5-16)
    max_scenes = 16
    min_scenes = 5
    if len(scenes) > max_scenes:
        logger.warning(f"Found {len(scenes)} scenes, limiting to {max_scenes} scenes")
        scenes = scenes[:max_scenes]
    elif len(scenes) < min_scenes:
        logger.warning(f"Found {len(scenes)} scenes, which is less than the recommended minimum of {min_scenes} scenes")
    
    return scenes


def auto_parse_script(script: str, max_retries: int = 3, auto_mode: bool = True, language: str = None) -> Dict[str, Any]:
    """
    Automatically parse script with retry mechanism.
    
    Args:
        script: The script text to parse
        max_retries: Maximum number of retry attempts for LLM parsing
        auto_mode: If True, auto-accept high scores and auto-retry low scores
        language: Language for the generated content
    
    Returns:
        Dict with keys:
        - status: "success", "manual", or "failed"
        - scenes: List of parsed scenes (if success or manual)
        - evaluation: Evaluation result (if manual)
        - message: Error message (if failed)
    """
    if not script or not script.strip():
        return {
            "status": "failed",
            "message": "Script is empty",
            "scenes": []
        }
    
    # Step 1: Always use LLM to parse script for multi-scene construction
    # regardless of whether it's already divided
    logger.info("Using LLM to parse script for multi-scene construction")
    
    scenes = []
    
    # Step 2: Parse with LLM
    for attempt in range(max_retries):
        try:
            scenes = parse_script_with_llm(script, language=language)
            
            if scenes:
                logger.info(f"LLM parsing attempt {attempt + 1} successful, got {len(scenes)} scenes")
                break
            else:
                logger.warning(f"LLM parsing attempt {attempt + 1} returned empty scenes")
                
        except Exception as e:
            logger.error(f"LLM parsing attempt {attempt + 1} failed: {e}")
            
            if attempt == max_retries - 1:
                return {
                    "status": "failed",
                    "message": f"Failed to parse script after {max_retries} attempts: {str(e)}",
                    "scenes": []
                }
    
    if not scenes:
        return {
            "status": "failed",
            "message": "No scenes could be extracted from the script",
            "scenes": []
        }
    
    # Step 3: Evaluate scene quality
    evaluation = evaluate_scenes(scenes)
    logger.info(f"Scene evaluation: total_score={evaluation['total_score']:.1f}, "
                f"auto_accept={evaluation['auto_accept']}, auto_reject={evaluation['auto_reject']}")
    
    # Step 4: Decision making
    if auto_mode:
        if evaluation["auto_accept"]:
            # High quality, auto-accept
            logger.success(f"Auto-accepting {len(scenes)} scenes with score {evaluation['total_score']:.1f}")
            return {
                "status": "success",
                "scenes": scenes,
                "evaluation": evaluation
            }
        elif evaluation["auto_reject"]:
            # Low quality, return with manual status
            logger.warning(f"Auto-rejecting scenes with score {evaluation['total_score']:.1f}")
            return {
                "status": "manual",
                "scenes": scenes,
                "evaluation": evaluation
            }
        else:
            # Medium quality, need user confirmation
            logger.info(f"Medium quality scenes (score {evaluation['total_score']:.1f}), requiring user confirmation")
            return {
                "status": "manual",
                "scenes": scenes,
                "evaluation": evaluation
            }
    else:
        # Manual mode, always return manual status
        return {
            "status": "manual",
            "scenes": scenes,
            "evaluation": evaluation
        }


def get_evaluation_status(total_score: float) -> Dict[str, str]:
    """
    Get evaluation status based on score.
    """
    if total_score >= 85:
        return {"status": "excellent", "icon": "✅"}
    elif total_score >= 70:
        return {"status": "good", "icon": "✅"}
    elif total_score >= 60:
        return {"status": "fair", "icon": "⚠️"}
    else:
        return {"status": "poor", "icon": "❌"}


def format_evaluation_result(evaluation: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format evaluation result for display.
    Returns structured data instead of formatted string for i18n support.
    """
    total_score = evaluation["total_score"]
    scores = evaluation["individual_scores"]
    issues = evaluation["issues"]
    
    # Get status
    status_info = get_evaluation_status(total_score)
    
    return {
        "total_score": total_score,
        "status": status_info["status"],
        "icon": status_info["icon"],
        "individual_scores": {
            "time_marker_completeness": scores.get("time_marker_completeness", 0),
            "time_continuity": scores.get("time_continuity", 0),
            "visual_completeness": scores.get("visual_completeness", 0),
            "script_duration_match": scores.get("script_duration_match", 0),
            "scene_structure_completeness": scores.get("scene_structure_completeness", 0)
        },
        "issues": issues
    }
