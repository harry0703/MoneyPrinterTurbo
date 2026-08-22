from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image


SUPPORTED_CONTENT_IDS = {f"HC20260810-{number:03d}" for number in range(1, 11)}
VERSION = "v01"
EXPECTED_SHOTS = [f"S{number:02d}" for number in range(1, 11)]
DETERMINISTIC_SHOTS = {"S03", "S08", "S10"}
DUAL_SOURCE_SHOTS = {
    ("HC20260810-004", "S03"),
    ("HC20260810-006", "S01"),
    ("HC20260810-009", "S01"),
    ("HC20260810-010", "S05"),
}
REPARSE_POINT_FLAG = 0x400


class ManualPackError(RuntimeError):
    """Raised when a manual pack cannot be built or verified safely."""


PROMPT_ACTIONS: dict[str, tuple[str, str]] = {
    "S01": (
        "餐后坐在藤编餐椅上的45岁中国女性只完成一次轻靠椅背并缓慢自然眨眼的连贯小动作，手部保持原位，镜头只做极轻微推近",
        "The seated 45-year-old Chinese woman makes one connected, low-amplitude action: a light settle back into the chair with one slow natural blink; keep her hands in place, with an extremely subtle camera push-in",
    ),
    "S02": (
        "餐桌旁的同一位女性只将视线缓慢抬向左侧窗光，手保持在已经离开餐盘的位置，餐盘、椅子与侧后方构图均不动",
        "The same woman beside the dining table slowly raises only her gaze toward the window light on the left; keep her hand in its already-away-from-the-plate position, and keep the plate, chair, and rear-side framing still",
    ),
    "S03": (
        "后期将左侧夜间暗光和右侧早晨窗光做一次缓慢交叉淡化，中央深青分隔、灯、窗帘和家具保持原位",
        "In post-production, make one slow crossfade between the dark night side and the morning window-light side; keep the central teal divider, lamps, curtains, and furniture fixed",
    ),
    "S04": (
        "餐桌前的同一位女性从当前首帧手部位置继续完成放勺的最后阶段：指尖轻触勺柄，勺子只做极小幅落稳，随即手轻轻收回，不重新拿起餐具；剩余菜品和餐盘不动，俯侧45度近景固定",
        "From the current first-frame hand position, the same woman completes only the final phase of setting down and releasing the spoon: fingertips lightly contact the handle, the spoon makes a tiny settling motion, then the hand gently withdraws without picking the utensil up again; keep the remaining greens and plate still, with a fixed 45-degree high oblique close view",
    ),
    "S05": (
        "同一位女性人物已经站起，只沿当前方向从餐区朝客厅迈一小步，镜头轻微横移跟随；米色开衫、蓝色上衣、深蓝长裤与家具位置不变",
        "The same woman is already standing and takes only one small step in the current direction from the dining area toward the living room, with a slight lateral camera follow; preserve her beige cardigan, blue top, navy trousers, and all furniture positions",
    ),
    "S06": (
        "越肩视角中的同一位女性只用拇指依次轻点黑屏上三个空白位置，手机四角、纯黑屏幕、另一只手和木桌不动",
        "From the over-shoulder view, the same woman makes one restrained sequence of three light thumb taps on blank positions of the black screen; keep all four phone corners, the pure black screen, other hand, and wooden table fixed",
    ),
    "S07": (
        "手机已放在桌面，同一位女性只完成一次自然呼吸，闭眼、双手和坐姿保持稳定，镜头只做轻微后拉",
        "With the phone already resting on the table, the same woman makes one natural breath only; keep her eyes closed, hands and seated posture stable, with a very slight camera pull-back",
    ),
    "S08": (
        "后期让深青、浅桃和青绿三块日光场景依次各做一次轻微亮度提示，三个坐姿剪影、拱形板和植物保持不动",
        "In post-production, give the deep-teal, peach, and green daylight panels one gentle sequential brightness cue; keep the three seated silhouettes, arch panels, and plants motionless",
    ),
    "S09": (
        "在当前已把车钥匙放入盘中的状态下，钥匙保持在置物盘中，同一位女性朝沙发方向只迈一小步，镜头先固定，后轻微跟随；青绿柜体、沙发和行走方向不变",
        "With the car key already placed in the tray, keep the key in the tray while the same woman takes only one small step toward the sofa; keep the camera fixed first, then follow slightly, preserving the teal cabinet, sofa, and travel direction",
    ),
    "S10": (
        "后期让暖米白结束板上的三枚青绿圆点按从下到上的顺序各淡入一次，浅桃拱形、植物影子和背景完全不动",
        "In post-production, fade in each of the three teal dots once from bottom to top on the warm off-white end board; keep the peach arches, plant shadow, and background completely still",
    ),
}


SHOT_SEMANTIC_CONTRACTS: dict[str, dict[str, Any]] = {
    "S01": {
        "storyboard": {
            "人物动作": ("短暂眨眼",),
            "相机": ("85mm中近景固定", "缓慢推近"),
            "ai_source_layer": ("自然眨眼", "轻靠椅背"),
        },
        "prompt_zh": ("轻靠椅背", "缓慢自然眨眼", "极轻微推近"),
    },
    "S02": {
        "storyboard": {
            "人物动作": ("抬眼看向窗光", "手离开餐盘"),
            "相机": ("侧后方中景",),
            "ai_source_layer": ("只做抬眼动作",),
        },
        "prompt_zh": ("视线缓慢抬向左侧窗光", "手保持在已经离开餐盘的位置"),
    },
    "S03": {
        "storyboard": {
            "人物动作": ("夜晚关灯", "早晨拉帘"),
            "相机": ("无相机运动",),
            "ai_source_layer": ("无AI动态源",),
        },
        "prompt_zh": ("夜间暗光", "早晨窗光", "交叉淡化"),
    },
    "S04": {
        "storyboard": {
            "人物动作": ("放慢一口后停下餐具",),
            "相机": ("俯侧45度近景", "餐具与手同框"),
            "ai_source_layer": ("放下餐具一个动作",),
        },
        "prompt_zh": ("放勺的最后阶段", "勺子只做极小幅落稳", "手轻轻收回", "俯侧45度近景固定"),
    },
    "S05": {
        "storyboard": {
            "人物动作": ("从餐椅起身", "朝客厅方向迈一步"),
            "相机": ("全身中景", "小幅横移跟随"),
            "ai_source_layer": ("起身并迈一步", "方向固定"),
        },
        "prompt_zh": ("人物已经站起", "朝客厅迈一小步", "镜头轻微横移跟随"),
    },
    "S06": {
        "storyboard": {
            "人物动作": ("拇指点按三个空白位置",),
            "相机": ("越肩近景固定",),
            "ai_source_layer": ("黑屏手机", "单手点按", "不生成界面"),
        },
        "prompt_zh": ("拇指依次轻点", "黑屏上三个空白位置", "手机四角"),
    },
    "S07": {
        "storyboard": {
            "人物动作": ("放下手机", "闭眼感受片刻"),
            "相机": ("正面中近景", "轻微后拉"),
            "ai_source_layer": ("放下手机", "一次自然呼吸"),
        },
        "prompt_zh": ("手机已放在桌面", "一次自然呼吸", "轻微后拉"),
    },
    "S08": {
        "storyboard": {
            "人物动作": ("三次不同日光色块并列", "人物剪影保持一致"),
            "相机": ("无相机运动",),
            "ai_source_layer": ("无AI动态源", "纯色日光", "人物剪影"),
        },
        "prompt_zh": ("三块日光场景", "依次各做一次轻微亮度提示"),
    },
    "S09": {
        "storyboard": {
            "人物动作": ("把车钥匙放回置物盘", "走向沙发"),
            "相机": ("腰部中景", "先定后短跟"),
            "ai_source_layer": ("放下钥匙后离开一步",),
        },
        "prompt_zh": ("钥匙保持在置物盘中", "朝沙发方向只迈一小步", "镜头先固定，后轻微跟随"),
    },
    "S10": {
        "storyboard": {
            "人物动作": ("三枚青绿圆点依次出现",),
            "相机": ("无相机运动",),
            "ai_source_layer": ("无AI动态源", "纯确定性结束板"),
        },
        "prompt_zh": ("三枚青绿圆点", "从下到上的顺序各淡入一次"),
    },
}


VISUAL_REVIEW_NOTES = {
    "S01": "暖光餐桌旁坐姿人物，闭眼、手与餐盘关系清楚",
    "S02": "同一人物侧后坐姿，手已离盘，视线面向窗光",
    "S03": "夜间暗光与早晨窗光双板，中央分隔稳定",
    "S04": "餐具已在桌面，手在勺子附近，支持放勺最后落稳阶段",
    "S05": "人物已站立行走，从餐区朝客厅的方向清楚",
    "S06": "越肩黑屏手机，四角完整，拇指点按位置清楚",
    "S07": "手机已平放桌面，人物闭眼静坐",
    "S08": "三块色板与三个一致坐姿剪影，适合确定性亮度提示",
    "S09": "车钥匙在置物盘中，人物朝沙发方向处于离开姿态",
    "S10": "暖米白结束板与三枚青绿圆点，无文字",
}


PROMPT_ACTIONS_002: dict[str, tuple[str, str]] = {
    "S01": (
        "垂直分屏内保持同一人物与同一餐盒：左侧从食物已到唇边的状态继续完成一次较快入口并短距离收回筷子；右侧从筷子停在餐盒上方的状态缓慢夹起一小块食物送到唇边，只完成一次从容进餐动作；两侧不同步，分屏和景别固定",
        "Keep the same woman and matching lunch box in the vertical split screen: on the left, continue from food already at her lips to complete one quicker bite and withdraw the chopsticks a short distance; on the right, slowly lift one small piece from the box to her lips for one unhurried eating action; keep the two sides unsynchronized and the split framing fixed",
    ),
    "S02": (
        "后期把左右两格相同剩余份量的餐盒验收帧完全静止并列，中央青绿分隔线、米白桌面、饭菜种类与份量都不移动，只在后期叠加观察变量文字",
        "In post-production, hold the two accepted lunch-box frames with matching remaining portions completely still side by side; keep the central teal divider, warm table, food types, and portions motionless, adding observation-variable copy only in post",
    ),
    "S03": (
        "同一位女性从勺中食物已经到唇边的状态完成这一口：轻合嘴唇后把勺子缓慢下移一小段，另一只手继续扶住唯一餐盒；餐桌侧面中景固定，餐盒内饭菜位置和份量完全不变，窗边日光只低幅移动",
        "From the food already at her lips, the same woman completes this single bite by gently closing her lips and lowering the spoon a short distance while the other hand continues to steady the lunch box; keep the side medium shot fixed with no jump in window light or food quantity",
    ),
    "S04": (
        "从当前手指靠近已平放勺子的状态完成放下餐具的最后阶段：指尖轻触勺柄，勺子仅极小幅落稳，随后手收回；先保持餐具近景固定，不由模型切镜，人物中景只在后期确定性衔接",
        "From the current hand position beside the spoon already lying flat, complete only the final phase of setting the utensil down: fingertips lightly contact the handle, the spoon settles by a tiny amount, then the hand withdraws; keep the utensil close-up fixed and leave the later person-medium-shot cut to deterministic editing",
    ),
    "S05": (
        "人物已经在普通办公位坐下，从落座后的最后阶段只做一次很小的身体落稳并停顿，双手始终放在腿上且已经离开唯一一把键盘；办公位侧面中景固定，唯一一台黑色显示器保持纯空白无界面",
        "The woman is already seated at the ordinary workstation; complete only the final settling phase with one tiny body settle and pause, keeping both hands on her lap and already away from the keyboard; hold the side medium shot fixed and keep the black monitor and keyboard free of any interface",
    ),
    "S06": (
        "同一位女性从看向餐盘的视线缓慢抬到正前方的中性位置，只完成一次视线移动，头部、交叠在腿上的双手和坐姿保持稳定；眼平中近景只做极轻微推近",
        "The same woman slowly lifts her gaze from the lunch box to a neutral point ahead, completing one gaze movement only; keep her head, folded hands on her lap, and seated posture stable, with an extremely slight eye-level medium-close push-in",
    ),
    "S07": (
        "俯拍画面中唯一一把叉子已经平放在餐盒旁且不在餐盒内，从当前指尖靠近叉柄的位置完成放平动作的最后阶段：叉子只极小幅落稳，随后手完全离开；餐盒剩余米饭和菜量、桌面与俯拍构图不变",
        "In the overhead view, the fork is already lying flat beside the lunch box; from fingertips near the handle, complete only the final phase of laying it down as the fork settles minimally and the hand moves away; keep the remaining rice and vegetables, tabletop, and overhead framing unchanged",
    ),
    "S08": (
        "人物从当前朝办公椅迈步的位置沿原方向完成余下两小步并一次自然落座，不回头、不反转路线；走廊中远景轻微跟随，接近椅子后固定，显示器保持黑色空白",
        "From the current stride toward the office chair, the woman completes the remaining two small steps and one natural sit-down without turning back or reversing direction; follow slightly in the corridor medium-long view, then lock off near the chair, keeping the monitor black and blank",
    ),
    "S09": (
        "后期把恰好一只餐盘与一把空青绿色餐椅的静物验收帧全程静止，盘中剩余食物、木桌边缘、椅子和墙面光影完全不动；保持无人物、无餐具、无第二套餐位，只由后期加入边界文字",
        "In post-production, hold the accepted still life of the plate and empty teal dining chair completely static; keep the remaining food, wooden table edge, chair, and wall light motionless, adding boundary copy only in post",
    ),
    "S10": (
        "后期保持暖米白结束板和中央两条青绿色暂停符号完全静止，两个圆角竖条的数量、间距、尺寸与颜色不变，只在后期叠加结尾文字",
        "In post-production, keep the warm off-white end board and the two central teal pause bars completely still; preserve the count, spacing, size, and color of both rounded vertical bars, adding closing copy only in post",
    ),
}


SHOT_SEMANTIC_CONTRACTS_002: dict[str, dict[str, Any]] = {
    "S01": {"storyboard": {"人物动作": ("左侧匆匆动作", "右侧从容动作"), "相机": ("垂直分屏固定", "两侧同景别"), "ai_source_layer": ("两段独立人物源", "一次进餐动作")}, "prompt_zh": ("左侧", "一次较快入口", "右侧", "一次从容进餐动作", "分屏和景别固定")},
    "S02": {"storyboard": {"人物动作": ("相同剩余份量",), "相机": ("分屏静止", "后期对齐构图"), "ai_source_layer": ("无AI动态源", "确定性并列")}, "prompt_zh": ("相同剩余份量", "完全静止并列", "后期叠加")},
    "S03": {"storyboard": {"人物动作": ("从第一口开始", "日光缓慢移动"), "相机": ("餐桌侧面中景固定",), "ai_source_layer": ("一口自然进餐",)}, "prompt_zh": ("食物已经到唇边", "完成这一口", "餐桌侧面中景固定")},
    "S04": {"storyboard": {"人物动作": ("主动放下餐具",), "相机": ("餐具近景", "后切人物中景"), "ai_source_layer": ("只做放下餐具动作",)}, "prompt_zh": ("放下餐具的最后阶段", "勺子仅极小幅落稳", "手收回", "不由模型切镜")},
    "S05": {"storyboard": {"人物动作": ("回到普通办公位坐下", "双手离开键盘"), "相机": ("办公位侧面中景", "落座后保持固定"), "ai_source_layer": ("落座并停顿一次",)}, "prompt_zh": ("已经在普通办公位坐下", "落座后的最后阶段", "唯一一把键盘", "唯一一台黑色显示器", "侧面中景固定")},
    "S06": {"storyboard": {"人物动作": ("视线在餐盘与自己之间",), "相机": ("眼平中近景", "轻微推近"), "ai_source_layer": ("一次视线移动",)}, "prompt_zh": ("从看向餐盘的视线缓慢抬到正前方", "一次视线移动", "极轻微推近")},
    "S07": {"storyboard": {"人物动作": ("把餐具平放在盘边",), "相机": ("餐盘俯拍近景固定",), "ai_source_layer": ("一次放平餐具动作",)}, "prompt_zh": ("唯一一把叉子", "不在餐盒内", "放平动作的最后阶段", "手完全离开", "俯拍构图不变")},
    "S08": {"storyboard": {"人物动作": ("停一步", "自然落座"), "相机": ("走廊中远景", "办公位侧景"), "ai_source_layer": ("走两步并坐下",)}, "prompt_zh": ("完成余下两小步", "一次自然落座", "不反转路线", "轻微跟随")},
    "S09": {"storyboard": {"人物动作": ("餐盘与空椅静态画面",), "相机": ("无相机运动",), "ai_source_layer": ("无AI动态源", "餐桌静物板")}, "prompt_zh": ("恰好一只餐盘", "一把空青绿色餐椅", "无人物、无餐具、无第二套餐位", "全程静止")},
    "S10": {"storyboard": {"人物动作": ("暂停符号",), "相机": ("无相机运动",), "ai_source_layer": ("无AI动态源", "确定性结束板")}, "prompt_zh": ("暖米白结束板", "两条青绿色暂停符号", "完全静止")},
}


VISUAL_REVIEW_NOTES_002 = {
    "S01": "左右分屏为同一人物和同类餐盒，左侧食物已到唇边、右侧筷子位于餐盒上方",
    "S02": "左右餐盒静物板份量与构图对齐，中央青绿分隔明确",
    "S03": "侧面坐姿人物用勺进餐，食物已到唇边，另一手扶餐盒",
    "S04": "勺子已平放桌面，手靠近勺柄，适合只做最终落稳与撤手",
    "S05": "人物已坐在办公椅上，双手在腿上，黑色显示器无界面",
    "S06": "人物低头看餐盒，双手交叠在腿上，适合一次抬眼",
    "S07": "俯拍中叉子已平放餐盒旁，手指靠近叉柄",
    "S08": "人物从走廊迈向办公椅，方向和落座目标清楚",
    "S09": "剩余餐盘与空青绿椅构成静态边界板，无人物",
    "S10": "暖米白结束板中央只有两条青绿暂停符号，无文字",
}


PROMPT_ACTIONS_003: dict[str, tuple[str, str]] = {
    "S01": (
        "同一位女性保持坐姿和双手在桌面的位置，视线停在自己面前已经添加过食物的小餐盘上，只完成一次安静停顿；高位斜俯中景缓慢下降少量，前景公用菜盘、盛菜勺和餐盘份量不变",
        "Keep the same woman seated with both hands in place on the table and her gaze resting on the small plate in front of her that has already received an extra serving; complete one quiet pause only while the high oblique medium view descends slightly, preserving the foreground serving dish, serving spoon, and all portions",
    ),
    "S02": (
        "从右手已经握住盛菜勺且勺面贴近桌面的状态完成放勺：把勺子短距离移回公用盘边、轻触桌面后松手，随后手离开；手部与餐桌近景固定，小餐盘和公用菜盘都不移动",
        "From the right hand already holding the serving spoon close to the tabletop, complete setting it down by moving it a short distance back beside the shared dish, letting it touch the table, releasing it, and withdrawing the hand; keep the hand-table close-up fixed and both dishes motionless",
    ),
    "S03": (
        "后期在俯拍固定构图中确定性切换左侧空碗与右侧添加后餐盘，两件米白餐具、木桌纹理、墙面叶影和中间白色分隔保持静止，不生成倒菜或份量变化动画",
        "In post-production, deterministically switch between the empty bowl on the left and the filled plate after an added serving on the right; hold both warm-white dishes, wood grain, wall leaf shadows, and central white divider still, without generating any serving or portion-change animation",
    ),
    "S04": (
        "同一位女性从唯一一把叉子已悬在餐盘上方且未接触食物的位置向菜品靠近一小段后停住，不夹起也不入口，另一只手保持静止；侧面手臂中近景固定并把焦点留在停住的叉子上",
        "From the fork already raised above the plate, the same woman moves it a short distance toward the food and then stops, without picking anything up or taking a bite; keep wrist and forearm stable in a fixed side medium-close view focused on the halted fork",
    ),
    "S05": (
        "客厅中的同一位女性只把双手已经扶住的一只米白靠垫向沙发角落轻移并摆正一次，随即松手；全身与沙发广角固定，只保留这一只靠垫，不新增收纳物或高要求事项道具",
        "In the living room, the same woman makes one adjustment to the single warm-white cushion already held by both hands, shifting it slightly into the sofa corner and straightening it before releasing; keep the full-body wide view fixed and add no storage items or task props",
    ),
    "S06": (
        "从唯一一把盛菜勺里已有一小份豆腐和豆角的状态完成一次少盛动作：公用盘保持在左侧，把这一勺移到开场为空的小餐盘上方并放下食物，再把勺子短距离放回公用盘边；俯侧餐桌构图稳定，不再添加第二勺",
        "From one small serving of tofu and green beans already in the serving spoon, complete a single smaller-serving sequence: move it over the empty small plate, deposit the food, then set the spoon back beside the shared dish over a short distance; keep the high-side table framing stable and do not add a second spoonful",
    ),
    "S07": (
        "后期保持暖米白底上的一个青绿色C形开放餐盘轮廓、右侧一双短筷和一把浅桃色勺完全静止，各一件餐具的数量、C形开口方向、间距与颜色不变，不新增刻度、仪表或图表，只叠加后期文字",
        "In post-production, keep the teal open plate outline, two utensil lines, and single peach spoon bowl on the warm off-white background completely still; preserve line count, opening direction, spacing, and colors, adding only the later non-uniform-portion copy",
    ),
    "S08": (
        "人物从当前朝餐椅行走的位置沿原方向迈完一小步，扶住椅背并一次自然坐下，不绕桌、不反转路线；门口中远景轻微跟随，人物落座后固定，桌上现有一大一小两只餐盘不变",
        "From the current walk toward the dining chair, the woman completes one small step in the same direction, steadies the chair back, and sits once naturally without circling the table or reversing path; follow slightly in the doorway medium-long view and lock off after she sits, preserving the existing large and small dishes",
    ),
    "S09": (
        "唯一一把叉子已经平放且人物处于半起身相位，只让上身轻微抬起后再次停住，结束时仍保持半起身，不站直、不迈步、不碰叉；空餐盘和叉子留在原位，侧面全身中景只做极短跟随",
        "With the single fork already flat and the woman in a half-risen phase, let her torso lift only slightly and stop again while still half-risen; do not stand upright, step away, or touch the fork; keep the empty plate and fork in place with only an extremely short follow in the side full-body medium view",
    ),
    "S10": (
        "后期保持深青绿结束板、中央浅桃椭圆餐盘轮廓和下方一枚青绿色圆点完全静止，椭圆与圆点的数量、位置、尺寸和颜色不变，只叠加备忘文字",
        "In post-production, keep the deep-teal end board, central peach oval plate outline, and single turquoise dot below completely still; preserve their count, position, size, and color, adding reminder copy only in post",
    ),
}


SHOT_SEMANTIC_CONTRACTS_003: dict[str, dict[str, Any]] = {
    "S01": {"storyboard": {"人物动作": ("看向餐桌上已经添加过的餐盘",), "相机": ("高位斜俯中景", "缓慢下降"), "ai_source_layer": ("一次停顿与看盘动作",)}, "prompt_zh": ("视线停在", "已经添加过食物的小餐盘", "一次安静停顿", "缓慢下降")},
    "S02": {"storyboard": {"人物动作": ("盛菜勺放回公用盘边",), "相机": ("手部与餐桌关系近景固定",), "ai_source_layer": ("只完成放勺动作",)}, "prompt_zh": ("完成放勺", "公用盘边", "松手", "近景固定")},
    "S03": {"storyboard": {"人物动作": ("空碗与添加后的餐盘",), "相机": ("俯拍静物", "确定性切换"), "ai_source_layer": ("无AI动态源", "两张餐桌静物板")}, "prompt_zh": ("确定性切换", "空碗", "添加后餐盘", "不生成倒菜")},
    "S04": {"storyboard": {"人物动作": ("准备再夹菜时停手",), "相机": ("侧面手臂中近景", "焦点落在停手"), "ai_source_layer": ("伸手后停住",)}, "prompt_zh": ("唯一一把叉子", "未接触食物", "另一只手保持静止", "向菜品靠近一小段后停住")},
    "S05": {"storyboard": {"人物动作": ("先整理轻便物品",), "相机": ("客厅广角固定", "后期事项块移动"), "ai_source_layer": ("只整理一件轻便物品",)}, "prompt_zh": ("一只米白靠垫", "轻移并摆正一次", "广角固定", "不新增收纳物")},
    "S06": {"storyboard": {"人物动作": ("先盛较少份量", "把勺放下"), "相机": ("餐盘俯拍", "手部侧近景"), "ai_source_layer": ("盛一次并放勺",)}, "prompt_zh": ("唯一一把盛菜勺", "公用盘保持在左侧", "开场为空的小餐盘", "不再添加第二勺")},
    "S07": {"storyboard": {"人物动作": ("没有克数", "开放式份量轮廓"), "相机": ("无相机运动",), "ai_source_layer": ("无AI动态源", "确定性餐盘轮廓板")}, "prompt_zh": ("一个青绿色C形开放餐盘轮廓", "一双短筷", "一把浅桃色勺", "不新增刻度、仪表或图表")},
    "S08": {"storyboard": {"人物动作": ("照常坐到餐桌前",), "相机": ("门口中远景", "人物入画后停"), "ai_source_layer": ("走到座位并坐下",)}, "prompt_zh": ("朝餐椅", "迈完一小步", "一次自然坐下", "不反转路线")},
    "S09": {"storyboard": {"人物动作": ("放下餐具并起身离开餐桌",), "相机": ("侧面全身中景", "短跟半步"), "ai_source_layer": ("放下餐具后起身",)}, "prompt_zh": ("唯一一把叉子已经平放", "半起身相位", "仍保持半起身", "不站直、不迈步、不碰叉")},
    "S10": {"storyboard": {"人物动作": ("深青绿卡片", "浅桃色餐盘轮廓"), "相机": ("无相机运动",), "ai_source_layer": ("无AI动态源", "确定性结束板")}, "prompt_zh": ("深青绿结束板", "浅桃椭圆餐盘轮廓", "一枚青绿色圆点", "完全静止")},
}


VISUAL_REVIEW_NOTES_003 = {
    "S01": "人物坐在餐桌前低头看小餐盘，前景公用菜盘和盛菜勺清楚",
    "S02": "手持盛菜勺贴近桌面，公用盘和个人小盘位置稳定",
    "S03": "左右静物分别为空碗和添加后餐盘，白色中线分隔",
    "S04": "叉子举在个人餐盘上方，适合向前少量后停手",
    "S05": "人物双手扶一只米白靠垫站在沙发旁，物件单一",
    "S06": "盛菜勺中已有一小份豆腐豆角，空小盘位于落点",
    "S07": "暖米白底为开放餐盘及餐具轮廓，无数字或刻度",
    "S08": "人物沿明确方向走向餐椅，桌上现有两只餐盘",
    "S09": "唯一叉子已平放，人物仍处于半起身相位，只允许轻微抬起后停住",
    "S10": "深青绿结束板含一个浅桃椭圆和一个青绿圆点，无文字",
}


PROMPT_ACTIONS_004: dict[str, tuple[str, str]] = {
    "S01": (
        "后期保持七块纵向色板与其中七个人形完全静止，严格保留坐、走、坐、走、坐、走、坐的顺序；坐姿的椅背、坐面、屈膝和落地脚与步行姿态的分腿、对侧摆臂不改变，只在后期叠加标题",
        "In post-production, hold exactly seven vertical panels and their seven figures completely still, preserving the strict seated, walking, seated, walking, seated, walking, seated order; keep every seated chair back, seat, bent knee, and grounded foot and every walking split-leg, counter-swinging-arm silhouette unchanged, adding the title only in post",
    ),
    "S02": (
        "无人社区平坦步道与唯一长椅保持原位，只让树叶和地面树影低幅轻动；24mm环境广角只做极慢推入，全程不得出现行人或跑者，不将长椅变成台阶",
        "Keep the empty flat community path and single bench in place, allowing only low-amplitude leaf and tree-shadow movement; make one extremely slow push-in with the 24 mm environmental wide view, with no pedestrian or runner entering and no bench changing into steps",
    ),
    "S03": (
        "必须分别生成 Source A 和 Source B：Source A 只让当前同一长椅上的同一人物坐稳并自然呼吸；Source B 从匹配构图的同一长椅起身后只向步道前走一步。两次生成的人物衣着、长椅、路径与机位一致；不得在单条 clip 内制作硬切或分屏，不得融合成双人，两条独立源只在后期硬切",
        "You must generate Source A and Source B separately: Source A only keeps the same woman settled on the current bench with natural breathing; Source B starts from the matching setup on the same bench, rises, and takes exactly one step onto the path. Match clothing, bench, path, and camera position across both generations; do not create a hard cut or split screen inside one clip, do not merge them into two people, and hard-cut the two independent sources only in post",
    ),
    "S04": (
        "同一位女性在长椅上坐稳，只完成一次低幅自然呼吸；双手始终平放大腿、双脚落地，不起身、不走动、不出现手机或记录物，侧面全身远景固定",
        "The same woman remains settled on the bench and completes one low-amplitude natural breath only; keep both hands flat on her thighs and both feet grounded, with no rising, walking, phone, or recording item, in a fixed side full-body long shot",
    ),
    "S05": (
        "同一位女性站定在平坦步道入口，只把头部转向右侧安全路线一次后停住，身体和双脚不走动；低机位广角仅轻微前移，不把入口变成楼梯或坡道",
        "The same woman stands still at the entrance to the flat path and turns her head once toward the safe route on her right, then stops, while her body and feet do not walk; make only a slight forward camera move from the low wide angle and do not turn the entrance into stairs or a slope",
    ),
    "S06": (
        "同一位女性沿当前方向以自然步幅严格完成三步，第三步后停止继续前走；平行侧跟中远景保持恒速，不反向、不跑步、不跨越、不循环多走",
        "The same woman completes exactly three natural steps in the current direction and stops advancing after the third step; keep a constant-speed parallel side follow in the medium-long view, with no reversal, running, crossing, or extra looping steps",
    ),
    "S07": (
        "人物已在平坦步道出口停稳，只用右手食指向唯一手机的纯深青灰空白屏外做一次低幅点按后收回；手机四角完整、外框约2.13–2.17、中央70%留空，越肩中近景固定，不让指尖进入屏幕",
        "With the woman already stopped at the flat-path exit, make one restrained tap toward the outside of the single phone's uniform deep-teal-gray blank screen and withdraw the right index finger; keep all four phone corners complete, the outer ratio about 2.13–2.17, the central 70 percent empty, and the over-shoulder medium-close view fixed, with the fingertip never entering the screen",
    ),
    "S08": (
        "后期保持上下两张人物验收状态和深青底板完全静止，恰好两个人形、两种颜色及其上下关系不改变，只在后期叠加“不预设”边界文字，不生成动态或图表",
        "In post-production, hold the two vertically arranged accepted figure states and deep-teal board completely still; preserve exactly two figures, their two colors, and the top-bottom relationship, adding the non-predetermined boundary copy only in post without generated motion or charts",
    ),
    "S09": (
        "人物在左侧湿滑路面前保持停止，只朝右侧干燥安全路段转向一次并再次停稳，不踏入湿路、不折返多次；保留当前脚步全景与侧面人物关系，只做一次短侧跟",
        "Keep the woman stopped before the wet surface on the left; turn once toward the dry safe path on the right and stop again, never stepping into the wet path or reversing repeatedly; preserve the current full-foot and side-person relationship with one short lateral follow only",
    ),
    "S10": (
        "后期保持深青底上恰好七块圆角面板完全静止，其中只有一块浅桃色例外，其余六块青绿色的数量、位置与间距不变，不改成统计图或路径动画",
        "In post-production, hold exactly seven rounded panels on the deep-teal board completely still, with only one peach exception and the other six teal panels unchanged in count, position, and spacing; do not turn the board into a chart or path animation",
    ),
}


SHOT_SEMANTIC_CONTRACTS_004: dict[str, dict[str, Any]] = {
    "S01": {"storyboard": {"人物动作": ("七块日光色板", "坐姿与步行剪影交替"), "相机": ("无相机运动", "确定性铺陈"), "ai_source_layer": ("无AI动态源", "七块无字色板与剪影")}, "prompt_zh": ("七块纵向色板", "坐、走、坐、走、坐、走、坐", "椅背、坐面、屈膝和落地脚", "分腿、对侧摆臂")},
    "S02": {"storyboard": {"人物动作": ("社区步道全景与长椅同框",), "相机": ("24mm环境广角", "极慢推入"), "ai_source_layer": ("无人环境动态源", "树影轻动")}, "prompt_zh": ("无人社区平坦步道", "唯一长椅", "极慢推入", "不得出现行人或跑者")},
    "S03": {"storyboard": {"人物动作": ("同一人物一天坐长椅", "另一天从长椅起步"), "相机": ("匹配构图硬切", "不做分屏人物融合"), "ai_source_layer": ("两条独立动态源", "坐姿呼吸", "起身一步")}, "prompt_zh": ("分别生成 Source A 和 Source B", "Source A", "坐稳并自然呼吸", "Source B", "只向步道前走一步", "不得在单条 clip 内制作硬切或分屏", "两条独立源只在后期硬切")},
    "S04": {"storyboard": {"人物动作": ("长椅安静坐着", "手里没有记录物"), "相机": ("侧面全身远景固定",), "ai_source_layer": ("自然坐姿与呼吸",)}, "prompt_zh": ("一次低幅自然呼吸", "双手始终平放大腿", "双脚落地", "不出现手机或记录物")},
    "S05": {"storyboard": {"人物动作": ("站在平坦步道入口观察路面",), "相机": ("低机位广角", "轻微前移"), "ai_source_layer": ("只转头确认路线",)}, "prompt_zh": ("站定在平坦步道入口", "只把头部转向", "身体和双脚不走动", "不把入口变成楼梯或坡道")},
    "S06": {"storyboard": {"人物动作": ("轻松走动", "步幅自然"), "相机": ("平行侧跟中远景", "速度恒定"), "ai_source_layer": ("连续走三步", "方向不反转")}, "prompt_zh": ("严格完成三步", "第三步后停止继续前走", "恒速", "不反向、不跑步、不跨越、不循环多走")},
    "S07": {"storyboard": {"人物动作": ("步道出口停下", "点按黑屏手机一个空位"), "相机": ("越肩中近景", "手机不生成界面"), "ai_source_layer": ("停步后单次点按",)}, "prompt_zh": ("平坦步道出口停稳", "只用右手食指", "一次低幅点按", "四角完整", "外框约2.13–2.17", "中央70%留空", "不让指尖进入屏幕")},
    "S08": {"storyboard": {"人物动作": ("坐后与走后两张人物验收帧上下排列",), "相机": ("无相机运动",), "ai_source_layer": ("无AI动态源", "确定性对照板")}, "prompt_zh": ("上下两张人物验收状态", "恰好两个人形", "完全静止", "不生成动态或图表")},
    "S09": {"storyboard": {"人物动作": ("湿滑路面前人物停下", "转向安全路段"), "相机": ("脚步全景转侧面中景",), "ai_source_layer": ("停步并转向一次",)}, "prompt_zh": ("左侧湿滑路面前保持停止", "右侧干燥安全路段转向一次", "不踏入湿路、不折返多次")},
    "S10": {"storyboard": {"人物动作": ("七块色板保留一块例外色", "结束在暖米白底"), "相机": ("无相机运动",), "ai_source_layer": ("无AI动态源", "确定性结束板")}, "prompt_zh": ("恰好七块圆角面板", "只有一块浅桃色例外", "其余六块青绿色", "完全静止")},
}


VISUAL_REVIEW_NOTES_004 = {
    "S01": "恰好七块纵向色板，坐姿和步行剪影严格交替，坐姿椅子与步行分腿可辨",
    "S02": "无人平坦社区步道与唯一长椅同框，树影可做低幅环境运动",
    "S03": "同一人物在同一长椅坐稳，双手在大腿、双脚落地，用于匹配两条独立源",
    "S04": "人物安静坐长椅，低头、双手平放大腿、双脚落地，无记录物",
    "S05": "人物在平坦步道入口站定，可只做一次转头查看路线",
    "S06": "人物处于步行相位，道路平坦且方向清楚，适合精确三步侧跟",
    "S07": "人物在平坦路径出口停稳，唯一手机四角完整、纯深青灰屏，指尖在屏外",
    "S08": "深青板上恰好两个不同颜色人形，可作确定性静态对照",
    "S09": "人物停在湿滑左路与干燥右路分界处，转向安全路段的方向清楚",
    "S10": "深青底恰好七块面板，六块青绿与一块浅桃例外的数量关系清楚",
}


PROMPT_ACTIONS_005: dict[str, tuple[str, str]] = {
    "S01": (
        "同一位女性面对唯一台纯深青色显示器，只将右手从腿上低幅抬起一次后放回腿上，结束时两手都离开唯一键盘；正面中景快速小幅推近后立即停住，屏幕不出现待办或界面",
        "Facing the single solid deep-teal monitor, the same woman raises only her right hand a short distance from her lap once and returns it to her lap, ending with both hands away from the single keyboard; make one quick small push-in in the frontal medium view and stop immediately, with no task list or interface appearing on the screen",
    ),
    "S02": (
        "俯拍桌面中保持唯一台显示器、唯一键盘和左右两只完整手，两手已离开键盘，只同时向身体方向短距离收回后停住；机位固定，不新增倒置头部、桌面物件或屏幕内容",
        "In the overhead desk view, preserve one monitor, one keyboard, and exactly two complete hands; with both hands already away from the keyboard, withdraw them together a short distance toward the body and stop; keep the camera fixed and add no inverted head, desk item, or screen content",
    ),
    "S03": (
        "同一位女性保持头部和坐姿稳定，只将视线从屏幕方向缓慢转向左侧环境光一次后停住；三分之二侧脸近景固定，不操作屏幕，不出现任务文字或计时内容",
        "Keep the same woman's head and seated posture stable, moving only her gaze once from the screen direction toward the environmental light on the left and then stopping; hold the three-quarter side-face close view fixed, with no screen operation, task text, or timing content",
    ),
    "S04": (
        "后期保持恰好三张竖向无人生活场景板完全静止，左侧办公位、中间空椅与右侧远景窗的数量、顺序和构图不变，只在后期依次硬切或高亮一板，不引入人形或动态源",
        "In post-production, hold exactly three vertical, people-free life-scene panels completely still, preserving the count, order, and composition of the workstation on the left, empty chair in the middle, and distant window view on the right; hard-cut or highlight one panel at a time only in post, introducing no person silhouette or generated motion",
    ),
    "S05": (
        "越肩近景中只保留一部四角完整、外框约2.1、纯青空白屏的手机；右手食指从当前位置完成一次轻点后离开屏幕，随后只把手机短距离向桌面放低并停住；中央70%保持空白，不生成计时UI",
        "In the over-shoulder close view, keep a single phone with all four corners complete, an outer ratio about 2.1, and a uniform teal blank screen; complete one light tap from the current right-index-finger position, lift the finger off the screen, then lower the phone only a short distance toward the desk and stop; keep the central 70 percent blank and generate no timer UI",
    ),
    "S06": (
        "人物已从办公位朝窗边迈步，只沿当前方向完成余下两步，到窗前站稳后只望向远处；办公室广角转窗边侧面中景的衔接交给后期，源内不切镜，不多走、不返回键盘",
        "The woman is already striding from the workstation toward the window; complete only the remaining two steps in the current direction, stand still at the window, and look into the distance; leave the wide-office to side-window-medium cut to post-production, with no in-source cut, extra steps, or return to the keyboard",
    ),
    "S07": (
        "人物已回到普通办公位并坐下，只完成一次极小的落座稳定和自然呼吸后停顿；双手保持大腿、双脚落地，唯一纯青显示器无界面，侧面全身中景固定，不继续工作或触键盘",
        "The woman has returned to the ordinary workstation and is already seated; complete one tiny settling motion and one natural breath, then pause, keeping both hands on her thighs, both feet grounded, and the single solid-teal monitor free of interface; lock the side full-body medium view and do not resume work or touch the keyboard",
    ),
    "S08": (
        "后期保持恰好三块分开的中性生活场景块静止，上部深青块、中部暖色空块和下部含一把普通休息椅的青绿块数量与位置不变，不排成阶梯、不新增人物或评分图",
        "In post-production, keep exactly three separated neutral life-scene blocks still: the upper deep-teal block, middle warm empty block, and lower teal block containing one ordinary lounge chair; preserve their count and positions, never arranging them as stairs or adding a person or score chart",
    ),
    "S09": (
        "后期保持普通办公桌上恰好一把大汽车钥匙完全静止，钥匙的方向、轮廓、金属齿与黑色外壳不变；保持无人，不出现按钮图标、第二把钥匙、车辆或设备，暂停图形只在后期进入",
        "In post-production, hold exactly one large car key completely still on the ordinary office desk, preserving its direction, outline, metal blade, and black shell; keep the frame people-free and add no button pictogram, second key, vehicle, or device, with the pause graphic entering only in post",
    ),
    "S10": (
        "后期保持暖米白结束板上的一枚青绿圆点和一条短曲线路径静止，只让圆点沿现有短路径单向移动一次后停住；远处一把椅子的光影不动，不把圆点变成勾选、文字或复杂路线",
        "In post-production, preserve the single teal dot and one short curved path on the warm off-white end board, moving the dot once in one direction along the existing short path and then stopping; keep the distant chair shadow still and do not turn the dot into a check mark, text, or complex route",
    ),
}


SHOT_SEMANTIC_CONTRACTS_005: dict[str, dict[str, Any]] = {
    "S01": {"storyboard": {"人物动作": ("面对办公屏幕", "三张后期任务块挤在一起"), "相机": ("正面中景快速推近后停",), "ai_source_layer": ("抬手又放下", "屏幕保持纯色")}, "prompt_zh": ("唯一台纯深青色显示器", "右手从腿上低幅抬起一次后放回腿上", "两手都离开唯一键盘", "不出现待办或界面")},
    "S02": {"storyboard": {"人物动作": ("后期任务块收成一个", "人物离开键盘"), "相机": ("顶视办公桌", "确定性图形收拢"), "ai_source_layer": ("人物手离开键盘", "图形全部后期")}, "prompt_zh": ("唯一台显示器", "唯一键盘", "左右两只完整手", "两手已离开键盘", "不新增倒置头部")},
    "S03": {"storyboard": {"人物动作": ("看向屏幕旁的环境光",), "相机": ("三分之二侧脸近景固定",), "ai_source_layer": ("只转眼一次",)}, "prompt_zh": ("只将视线", "环境光", "一次后停住", "三分之二侧脸近景固定")},
    "S04": {"storyboard": {"人物动作": ("三张无人物板依次出现",), "相机": ("无相机运动", "三板硬切"), "ai_source_layer": ("无AI动态源", "三个无字生活剪影板")}, "prompt_zh": ("恰好三张竖向无人生活场景板", "左侧办公位", "中间空椅", "右侧远景窗", "不引入人形")},
    "S05": {"storyboard": {"人物动作": ("点亮手机系统计时占位后放下",), "相机": ("越肩手机近景", "屏幕纯色"), "ai_source_layer": ("一次点按", "系统计时由后期制作")}, "prompt_zh": ("一部四角完整", "外框约2.1", "纯青空白屏", "一次轻点", "手机短距离向桌面放低", "中央70%保持空白", "不生成计时UI")},
    "S06": {"storyboard": {"人物动作": ("离开屏幕", "站到窗边只看远处"), "相机": ("办公位广角转窗边侧面中景",), "ai_source_layer": ("起身走两步后看向远处",)}, "prompt_zh": ("已从办公位朝窗边迈步", "完成余下两步", "到窗前站稳", "只望向远处", "源内不切镜")},
    "S07": {"storyboard": {"人物动作": ("回到普通办公位", "落座后停顿感受"), "相机": ("侧面全身中景", "落座后镜头固定"), "ai_source_layer": ("回座并停顿一次",)}, "prompt_zh": ("已回到普通办公位并坐下", "一次极小的落座稳定", "双手保持大腿", "不继续工作或触键盘")},
    "S08": {"storyboard": {"人物动作": ("三个中性色块", "分开出现"), "相机": ("无相机运动",), "ai_source_layer": ("无AI动态源", "确定性三分支信息板")}, "prompt_zh": ("恰好三块分开", "上部深青块", "中部暖色空块", "下部含一把普通休息椅", "不排成阶梯")},
    "S09": {"storyboard": {"人物动作": ("普通办公桌上的车钥匙保持不动",), "相机": ("办公桌静物近景固定",), "ai_source_layer": ("无AI人物动态源", "车钥匙验收帧")}, "prompt_zh": ("恰好一把大汽车钥匙", "完全静止", "保持无人", "不出现按钮图标、第二把钥匙、车辆或设备")},
    "S10": {"storyboard": {"人物动作": ("单一青绿圆点沿短路径进入结束板",), "相机": ("无相机运动",), "ai_source_layer": ("无AI动态源", "确定性结束板")}, "prompt_zh": ("一枚青绿圆点", "一条短曲线路径", "单向移动一次后停住", "不把圆点变成勾选、文字或复杂路线")},
}


VISUAL_REVIEW_NOTES_005 = {
    "S01": "人物面对一台纯青显示器，双手已在腿上并离开唯一键盘",
    "S02": "俯拍中恰好一显示器、一键盘和两只完整手，两手明确离键盘",
    "S03": "三分之二侧脸与环境光清楚，人物已朝左侧视线相位",
    "S04": "恰好三张无人生活板：办公位、空椅、远景窗，无人形",
    "S05": "越肩唯一手机四角完整、纯青屏、比例约2.1，指尖靠下且中央留空",
    "S06": "人物处于朝窗边迈步的行走相位，双手双脚完整且方向清楚",
    "S07": "人物已在办公位坐稳，双手大腿、双脚落地，显示器保持纯色",
    "S08": "三块分离的中性场景块非阶梯式，只在下块有一把普通椅子",
    "S09": "普通办公桌上仅一把大车钥匙，无人、无第二钥匙、无伪图标",
    "S10": "暖色结束板含一圆点一短路径，远处椅子光影不影响单一路径语义",
}


PROMPT_ACTIONS_006: dict[str, tuple[str, str]] = {
    "S01": (
        "必须分别生成 Source A 和 Source B：Source A 只把同一位女性右手中的唯一一部无品牌手机短距离放到现有圆桌上后松手；Source B 保持当前客厅沙发与同一机位的匹配构图，从闭眼静止相位只睁眼醒来一次。手机四角完整并保持纯深青空白，现有杯子和靠垫不动；不得在单条 clip 内制作硬切或分屏，不得融合成连续变形镜头，两条独立源只在后期硬切",
        "You must generate Source A and Source B separately: in Source A, the same woman only lowers the single unbranded phone from her right hand onto the existing round table and releases it; Source B preserves the matching living-room sofa composition and camera position and lets her open her eyes once from a still eyes-closed phase. Keep all four phone corners complete and uniformly deep teal and blank, with the existing cup and cushions still; do not create a hard cut or split screen inside one clip, never blend them into a morphing continuous shot, and hard-cut the two independent sources only in post",
    ),
    "S02": (
        "后期保持暖米白底上恰好四段无字色带完全静止，严格保留躺下、等待、睡着、醒来的从左到右顺序、形状、颜色与间距；不做相机运动，不添加时钟、时间、数字、曲线或进度动画，只在后期叠加解释文字",
        "In post-production, hold exactly four text-free phase blocks completely still on the warm off-white background, preserving the left-to-right lying-down, waiting, asleep, and waking order, shapes, colors, and spacing; use no camera motion and add no clock, time, numbers, curve, or progress animation, adding explanatory copy only in post",
    ),
    "S03": (
        "同一位女性只把双手已经扶住的一只米白靠垫向沙发靠背轻移并摆正一次，随即松手；客厅全身广角固定，边桌上唯一一部黑屏手机始终平放且不触碰，不新增第二个靠垫、床品或其他物件",
        "The same woman makes one adjustment to the single warm-white cushion already held in both hands, shifting it slightly toward the sofa back and straightening it before releasing; keep the living-room full-body wide shot locked, keep the single black-screen phone flat and untouched on the side table throughout, and add no second cushion, bedding, or other object",
    ),
    "S04": (
        "同一位女性保持当前侧卧靠枕、闭眼和双手交叠姿态，只完成一次低幅自然呼吸，同时窗帘日光均匀缓慢变暗后稳定；侧面中远景固定，不翻身、不睁眼，不表演不适或疲惫症状",
        "Keep the same woman in the current side reclining pose against the cushion, eyes closed and hands folded, and allow only one low-amplitude natural breath while the curtain daylight dims slowly and evenly before settling; lock the side medium-long view, with no turning over, eye opening, or performance of discomfort or fatigue symptoms",
    ),
    "S05": (
        "同一位女性已经自然睁眼，只把头部和视线朝右侧窗光再转动一次后停住，双手继续放在腿上；眼平中近景只做一次极慢后拉，圆桌上唯一一部手机始终黑屏平放且全程不触碰，不出现触控笔、第二设备或幽灵物体",
        "The same woman is already naturally awake; move only her head and gaze once farther toward the window light on the right and then stop, keeping both hands on her lap; make one extremely slow pull-back from the eye-level medium-close view, while the single phone remains flat, black-screened, and untouched on the round table throughout, with no stylus, second device, or ghost object",
    ),
    "S06": (
        "越肩近正面固定构图中只保留唯一一部手机和现有两只手；左手稳持手机，右手食指依次向空白屏外三个分开的后期锚点做三次低幅点按后收回，每次指尖始终在屏幕外。手机外框约2.05、屏幕约2.12，四角与边框完整，屏幕为无渐变的纯深青色，中央70%全程空白，不生成任何界面",
        "In the fixed near-front over-shoulder composition, preserve only the single phone and the two existing hands; the left hand holds the phone steady while the right index finger makes exactly three restrained taps toward three separated post-production anchor points outside the blank screen, then withdraws, with the fingertip remaining outside the screen on every tap. Keep the outer phone ratio about 2.05 and the screen ratio about 2.12, all four corners and bezel complete, the screen uniformly deep teal with no gradient, and the central 70 percent blank throughout, generating no interface",
    ),
    "S07": (
        "同一位女性在沙发边缘保持双脚落地，只完成一次极小的坐直稳定和一次自然呼吸后安静停住，双手始终平放大腿；侧面全身中景固定，前景玄关托盘内现有的一只黑色钥匙扣和一把金属钥匙保持原位，人物不触碰、不取走，也不出现驾驶或机器操作",
        "At the sofa edge, the same woman keeps both feet grounded, completes one tiny upright settling motion and one natural breath, then rests quietly with both hands flat on her thighs; lock the side full-body medium view, preserve the existing one black key fob and one metal key in the foreground entry tray, and do not let her touch or take them or depict driving or machinery operation",
    ),
    "S08": (
        "夜间卧室门口的同一位女性从手机已接近床头柜的相位继续，只把唯一一部纯黑空白屏手机放平并松手，随后一次关掉现有床头灯后停住；门口中远景静态构图，手机不再拿起，灯不循环开关，不增加界面、第二手机或其他物件",
        "From the phase where the phone is already close to the bedside table at the nighttime bedroom doorway, the same woman only lays the single uniformly black blank-screen phone flat and releases it, then switches off the existing bedside lamp once and stops; keep the doorway medium-long composition static, do not pick the phone up again or toggle the lamp repeatedly, and add no interface, second phone, or other object",
    ),
    "S09": (
        "后期保持暖米白底上恰好三张同一人物的醒后状态验收帧完全静止，严格保留正视、闭眼、看向窗光三种不同状态及从左到右的顺序、尺寸和间距；不生成表情过渡，不添加量表、评分、数字、医学暗示或相机运动",
        "In post-production, hold exactly three accepted waking-state frames of the same woman completely still on the warm off-white background, preserving the distinct forward-looking, eyes-closed, and window-looking states and their left-to-right order, size, and spacing; generate no expression transition and add no scale, score, number, medical implication, or camera motion",
    ),
    "S10": (
        "后期保持俯视暖米白结束板上的一条青绿色短路径和三个宽距分开的圆形标记完全静止，三个标记的数量、位置、尺寸及现有路径形状不变；不移动标记，不把路径改成上升曲线、趋势图、统计图或文字",
        "In post-production, hold the single teal short path and exactly three widely separated circular markers completely still on the top-down warm off-white end board, preserving marker count, position, size, and the existing path shape; do not move the markers or turn the path into an ascending curve, trend chart, statistical graphic, or text",
    ),
}


SHOT_SEMANTIC_CONTRACTS_006: dict[str, dict[str, Any]] = {
    "S01": {"storyboard": {"人物动作": ("系统闹钟占位", "人物醒来画面硬切"), "相机": ("同机位中景匹配剪辑",), "ai_source_layer": ("两条人物源", "放下手机", "醒来睁眼")}, "prompt_zh": ("分别生成 Source A 和 Source B", "Source A", "唯一一部无品牌手机", "Source B", "只睁眼醒来一次", "不得在单条 clip 内制作硬切或分屏", "两条独立源只在后期硬切")},
    "S02": {"storyboard": {"人物动作": ("无字时间带", "躺下、等待、睡着、醒来"), "相机": ("无相机运动", "确定性时间带"), "ai_source_layer": ("无AI动态源", "不显示数字的色块时间带")}, "prompt_zh": ("恰好四段无字色带", "躺下、等待、睡着、醒来", "完全静止", "不添加时钟、时间、数字、曲线")},
    "S03": {"storyboard": {"人物动作": ("放好靠枕", "黑屏手机留在边桌"), "相机": ("客厅广角固定",), "ai_source_layer": ("只调整一次靠枕",)}, "prompt_zh": ("一只米白靠垫", "摆正一次", "唯一一部黑屏手机", "始终平放且不触碰")},
    "S04": {"storyboard": {"人物动作": ("窗帘光线渐暗", "人物闭眼保持自然姿态"), "相机": ("侧面中远景固定",), "ai_source_layer": ("人物闭眼与自然呼吸",)}, "prompt_zh": ("闭眼和双手交叠姿态", "一次低幅自然呼吸", "窗帘日光均匀缓慢变暗", "侧面中远景固定")},
    "S05": {"storyboard": {"人物动作": ("自然睁眼后看向窗光", "不触手机"), "相机": ("眼平中近景", "慢慢后拉"), "ai_source_layer": ("人物睁眼并转头一次",)}, "prompt_zh": ("已经自然睁眼", "头部和视线朝右侧窗光再转动一次", "极慢后拉", "唯一一部手机", "全程不触碰")},
    "S06": {"storyboard": {"人物动作": ("黑屏手机点按三处",), "相机": ("越肩近景固定",), "ai_source_layer": ("单手三次轻点", "不生成界面")}, "prompt_zh": ("唯一一部手机", "三次低幅点按", "外框约2.05", "屏幕约2.12", "四角与边框完整", "无渐变的纯深青色", "指尖始终在屏幕外", "中央70%全程空白", "不生成任何界面")},
    "S07": {"storyboard": {"人物动作": ("坐在沙发边缘", "双脚落地安静停留", "车钥匙留在玄关盘中"), "相机": ("侧面全身中景固定",), "ai_source_layer": ("人物坐直", "自然呼吸")}, "prompt_zh": ("双脚落地", "一次极小的坐直稳定", "双手始终平放大腿", "一只黑色钥匙扣和一把金属钥匙", "不触碰、不取走")},
    "S08": {"storyboard": {"人物动作": ("夜间卧室门口", "放下手机准备关灯"), "相机": ("门口中远景", "静态构图"), "ai_source_layer": ("人物放下手机并关灯",)}, "prompt_zh": ("唯一一部纯黑空白屏手机", "放平并松手", "一次关掉现有床头灯", "不循环开关")},
    "S09": {"storyboard": {"人物动作": ("三张不同醒后状态", "确定性板上并列"), "相机": ("无相机运动",), "ai_source_layer": ("无AI动态源", "确定性差异信息板")}, "prompt_zh": ("恰好三张", "正视、闭眼、看向窗光", "完全静止", "不添加量表、评分、数字、医学暗示")},
    "S10": {"storyboard": {"人物动作": ("三枚时点圆点", "品牌路径上排列"), "相机": ("无相机运动",), "ai_source_layer": ("无AI动态源", "确定性结束板")}, "prompt_zh": ("一条青绿色短路径", "三个宽距分开的圆形标记", "完全静止", "不把路径改成上升曲线、趋势图、统计图或文字")},
}


VISUAL_REVIEW_NOTES_006 = {
    "S01": "人物坐在客厅沙发，右手仅持一部四角完整、纯深青空白屏手机；现有圆桌杯子与靠垫需保持",
    "S02": "暖米白底恰好四段无字色带，从左到右形状和颜色各异，无时钟或数字",
    "S03": "人物双手正扶唯一米白靠垫，边桌唯一黑屏手机平放且未触碰",
    "S04": "人物已在沙发侧卧闭眼，双手交叠、头靠一只靠枕，适合低幅呼吸和日光渐暗",
    "S05": "人物醒后已朝右侧窗光，双手在腿上；圆桌唯一黑屏手机平放且不触碰",
    "S06": "越肩近正面唯一手机：outer约2.05、screen约2.12、纯深青均匀空屏、四角完整，右食指在屏外且中央70%留空",
    "S07": "人物坐在沙发边缘，双脚落地、双手大腿；前景托盘恰好一黑色钥匙扣和一金属钥匙",
    "S08": "夜间卧室人物正把唯一黑屏手机放向床头柜，现有床头灯可按顺序一次关闭",
    "S09": "恰好三张同一人物醒后状态帧并列，分别正视、闭眼和看向窗光",
    "S10": "俯视暖色结束板含一条青绿短路径和三个宽距分开的圆形标记，不呈上升趋势",
}


PROMPT_ACTIONS_007: dict[str, tuple[str, str]] = {
    "S01": (
        "同一位女性从右手已悬停在唯一一只无品牌陶瓷咖啡杯旁的相位继续，只把手向杯把靠近一小段后停在接触前，不拿起、不喝；镜头从杯口近景极轻微后拉到半身中景并停稳，咖啡液面、杯子位置和人物坐姿不变，不能出现第二只杯子",
        "From the phase where the same woman's right hand is already hovering beside the single unbranded ceramic coffee cup, move the hand only a short distance toward the handle and stop before contact, without lifting or drinking; make an extremely slight pull-back from the cup-rim close view to the half-body medium view and settle, preserving the coffee level, cup position, and seated pose with no second cup",
    ),
    "S02": (
        "从右手已经扶住桌面右侧唯一一只玻璃续杯壶的状态，只把壶沿桌面向右推回一小段后松手；恰好一壶一杯，壶保持直立且咖啡液面不变，不倾斜、不续杯、不倒咖啡；餐桌横向近景只跟随壶短移后固定",
        "From the phase where her right hand already steadies the single glass refill pot on the right side of the table, slide only that pot a short distance farther right and release it; preserve exactly one pot and one cup, keep the pot upright and the coffee level unchanged, and do not tilt, refill, or pour; let the lateral tabletop close view follow the short pot movement and then lock",
    ),
    "S03": (
        "无人俯拍固定构图中保持恰好一只装有咖啡的陶瓷杯完全不动，只让现有斜向窗光和杯影做一次低幅缓慢位移后稳定；液面和杯把方向不变，不出现手、人物、蒸汽、倒入动作或第二只杯子",
        "In the locked overhead composition with no person, keep exactly one coffee-filled ceramic cup completely still and allow only one low-amplitude slow shift of the existing diagonal window light and cup shadow before they settle; preserve the liquid level and handle direction, with no hand, person, steam, pouring, or second cup",
    ),
    "S04": (
        "后期保持左侧一只矮陶瓷杯与右侧一只高圆柱玻璃杯的验收帧完全静止，恰好两杯且杯型不同，杯内液面、间距、木桌和暖米白背景不变；不做容量刻度、数值比较、相机运动或模型生成，只由后期叠加说明",
        "In post-production, hold the accepted frame of one short ceramic mug on the left and one tall cylindrical glass on the right completely still; preserve exactly two vessels with different shapes, their liquid levels, spacing, wooden tabletop, and warm off-white background, with no capacity scale, numeric comparison, camera motion, or model generation, adding explanation only in post",
    ),
    "S05": (
        "当前唯一一部纯黑空白屏手机已经平放在床头柜上，同一位女性的右手也已到达唯一一盏床头灯的开关；只完成一次关灯后停住，手机全程不再触碰、不再拿起，门侧中远景仅极轻微推入；保持一人、一手机、一盏灯和现有床铺，不循环开关灯",
        "The single uniformly black blank-screen phone is already lying flat on the bedside table and the same woman's right hand has already reached the switch of the single bedside lamp; complete only one switch-off action and stop, never touching or lifting the phone again, with only an extremely slight push-in from the doorway medium-long view; preserve one person, one phone, one lamp, and the existing bed, without toggling the lamp repeatedly",
    ),
    "S06": (
        "越肩近正面固定构图中只保留唯一一部手机和现有两只手；左手稳持手机，右手食指依次朝屏幕外两个分开的后期锚点做恰好两次低幅点按后收回，每次指尖都不得越过边框或接触屏幕。手机外框与屏幕可见高宽比都约2.09，四角、外框和边框完整，屏幕始终为均匀纯灰色空屏，中央70%全程留空，不缩放、不拉伸、不生成任何界面，外框比例达到2.20或以上即淘汰",
        "In the fixed near-front over-shoulder composition, preserve only the single phone and the two existing hands; the left hand holds the phone steady while the right index finger makes exactly two restrained taps toward two separated post-production anchors outside the screen, then withdraws, never crossing the bezel or touching the screen. Keep both the visible outer-body and screen aspect ratios about 2.09, all four corners, outer frame, and bezel complete, the screen uniformly solid gray and blank, and the central 70 percent empty throughout; do not scale, stretch, or generate any interface, and reject any result with an outer ratio of 2.20 or greater",
    ),
    "S07": (
        "后期保持沿三段日光路径排列的恰好三只同型陶瓷咖啡杯完全静止，三只杯子的杯型、把手方向、咖啡液面、间距和从上到下的顺序不变，唯一差异只保留现有光线位置；不增加人物、时钟、数字、第四只杯子或相机运动",
        "In post-production, hold exactly three matching ceramic coffee cups arranged along the three sunlight bands completely still; preserve their shape, handle direction, coffee levels, spacing, and top-to-bottom order, leaving the existing light position as the only difference, with no person, clock, number, fourth cup, or camera movement",
    ),
    "S08": (
        "后期只在现有三块竖向夜窗色板之间按左到右顺序做一次确定性硬切比较，每块内部的窗框、窗帘、床沿和光色都保持静止，三栏数量与分隔不变；不加入人物、个人因果动作、时钟、数字或模型动态",
        "In post-production, make one deterministic left-to-right hard-cut comparison among the three existing vertical night-window color panels; keep the window frame, curtain, bed edge, and light color inside each panel static and preserve the three-panel count and dividers, adding no person, personal causal action, clock, number, or model-generated motion",
    ),
    "S09": (
        "同一位女性从当前背向餐桌、朝沙发迈步的相位沿原方向只再完成一小步后停住；前景桌面始终保留恰好一只咖啡杯，以及一只钥匙环上恰好两把金属车钥匙，杯与钥匙组彼此分离且完全不动，人物不回头、不拿钥匙、不驾车。单一连续镜头只从桌面中景低幅移焦到远处人物，末帧稳定供后期短停0.60秒",
        "From the current phase with the same woman facing away from the dining table and stepping toward the sofa, let her complete only one more small step in the same direction and stop; keep exactly one coffee cup and exactly two metal car keys on one key ring on the foreground table throughout, separated from each other and completely still, with no turn-back, key pickup, or driving. In one continuous shot, make only a low-amplitude focus shift from the tabletop medium view to the distant woman, then hold a stable end frame for the 0.60-second post-production extension",
    ),
    "S10": (
        "后期以当前暖米白静物板左下方唯一一只无把手杯的轮廓为起点，确定性叠加一条短青绿色路径并保持静止，杯子、木桌、墙面日光与大面积留白不动；当前正式帧没有短路径，必须仅由后期补足，不上传Grok，不改成实拍循环、数字、界面或复杂路线",
        "In post-production, use the outline of the single handleless cup at the lower left of the current warm off-white still board as the starting point and deterministically overlay one short teal path, then keep it static; preserve the cup, wooden table, wall light, and large negative space. The current formal frame has no short path, so supply it only in post, do not upload to Grok, and do not turn it into a live-action loop, number, interface, or complex route",
    ),
}


SHOT_SEMANTIC_CONTRACTS_007: dict[str, dict[str, Any]] = {
    "S01": {"storyboard": {"人物动作": ("一只咖啡杯居中", "人物伸手前停住"), "相机": ("杯口特写向后拉到半身中景",), "ai_source_layer": ("人物手伸向杯子后停住",)}, "prompt_zh": ("唯一一只无品牌陶瓷咖啡杯", "向杯把靠近一小段后停在接触前", "不拿起、不喝", "杯口近景极轻微后拉到半身中景", "不能出现第二只杯子")},
    "S02": {"storyboard": {"人物动作": ("把续杯壶推回桌边",), "相机": ("餐桌横向近景", "焦点跟随壶"), "ai_source_layer": ("只完成推回壶动作",)}, "prompt_zh": ("唯一一只玻璃续杯壶", "沿桌面向右推回一小段后松手", "恰好一壶一杯", "不倾斜、不续杯、不倒咖啡", "横向近景只跟随壶短移后固定")},
    "S03": {"storyboard": {"人物动作": ("咖啡杯旁日光角度形成时点线索",), "相机": ("静物俯拍固定",), "ai_source_layer": ("无人动态源", "自然光低幅变化")}, "prompt_zh": ("无人俯拍固定构图", "恰好一只", "斜向窗光和杯影", "低幅缓慢位移", "不出现手、人物、蒸汽、倒入动作或第二只杯子")},
    "S04": {"storyboard": {"人物动作": ("两只不同杯型", "确定性静物板并列"), "相机": ("无相机运动",), "ai_source_layer": ("无AI动态源", "杯型静物板")}, "prompt_zh": ("一只矮陶瓷杯", "一只高圆柱玻璃杯", "恰好两杯且杯型不同", "完全静止", "不做容量刻度、数值比较")},
    "S05": {"storyboard": {"人物动作": ("坐在床边准备关灯",), "相机": ("门侧中远景", "轻微推入"), "ai_source_layer": ("人物放下手机并伸手关灯",)}, "prompt_zh": ("手机已经平放在床头柜", "已到达唯一一盏床头灯的开关", "只完成一次关灯", "手机全程不再触碰、不再拿起", "一人、一手机、一盏灯", "不循环开关灯")},
    "S06": {"storyboard": {"人物动作": ("黑屏手机点按时间与份量位置",), "相机": ("越肩手机近景", "纯色屏幕"), "ai_source_layer": ("人物两次点按", "不生成界面")}, "prompt_zh": ("唯一一部手机", "恰好两次低幅点按", "指尖都不得越过边框或接触屏幕", "外框与屏幕可见高宽比都约2.09", "四角、外框和边框完整", "均匀纯灰色空屏", "中央70%全程留空", "不生成任何界面", "外框比例达到2.20或以上即淘汰")},
    "S07": {"storyboard": {"人物动作": ("三只同款杯子沿日光路径排开",), "相机": ("无相机运动", "确定性排列"), "ai_source_layer": ("无AI动态源", "同款杯静物板")}, "prompt_zh": ("恰好三只同型陶瓷咖啡杯", "完全静止", "杯型、把手方向、咖啡液面、间距", "唯一差异只保留现有光线位置", "不增加人物、时钟、数字、第四只杯子")},
    "S08": {"storyboard": {"人物动作": ("不同日子的夜间窗光色板交替",), "相机": ("无相机运动",), "ai_source_layer": ("无AI动态源", "品牌色夜间板")}, "prompt_zh": ("三块竖向夜窗色板", "左到右顺序", "确定性硬切比较", "三栏数量与分隔不变", "不加入人物、个人因果动作、时钟、数字或模型动态")},
    "S09": {"storyboard": {"人物动作": ("把咖啡杯留在桌上", "远离车钥匙"), "相机": ("桌面中景转玄关远景",), "ai_source_layer": ("人物离桌走向沙发", "不拿钥匙")}, "prompt_zh": ("朝沙发迈步", "只再完成一小步后停住", "恰好一只咖啡杯", "一只钥匙环上恰好两把金属车钥匙", "彼此分离且完全不动", "不回头、不拿钥匙、不驾车", "低幅移焦", "后期短停0.60秒")},
    "S10": {"storyboard": {"人物动作": ("咖啡杯轮廓与短路径",), "相机": ("无相机运动",), "ai_source_layer": ("无AI动态源", "确定性结束板")}, "prompt_zh": ("唯一一只无把手杯", "确定性叠加一条短青绿色路径", "当前正式帧没有短路径", "仅由后期补足", "不上传Grok", "不改成实拍循环")},
}


VISUAL_REVIEW_NOTES_007 = {
    "S01": "一位人物、唯一一只居中陶瓷咖啡杯；右手已悬停在杯把前，适合只靠近后停住",
    "S02": "一位人物、唯一一杯与唯一一只玻璃续杯壶；右手已扶壶，壶可沿桌面推回而不可倾倒",
    "S03": "无人俯拍，恰好一只盛有咖啡的杯子与斜向窗光，适合只做低幅光影位移",
    "S04": "无人静物板含恰好两种杯型：左侧矮陶瓷杯、右侧高圆柱玻璃杯，无容量刻度",
    "S05": "一位人物、一部纯黑空白屏手机和一盏床头灯；手机已平放，手已到开关，首帧处于关灯动作的后半相位",
    "S06": "越肩近正面唯一手机：外框/屏幕约2.09、四角与边框完整、均匀纯灰空屏，指尖在屏外且中央70%留空",
    "S07": "无人俯拍，恰好三只同型同把手方向的咖啡杯沿三段日光排列",
    "S08": "无人夜窗色板，恰好三栏且窗框、窗帘、床沿与分隔清楚，只允许确定性后期比较",
    "S09": "一位人物正离桌走向沙发；桌面恰好一杯及一只钥匙环上的两把金属钥匙，二者分离",
    "S10": "正式帧只有左下方一只无把手杯与大面积留白，分镜短路径尚不可见，必须由确定性后期补足且不上传Grok",
}


PROMPT_ACTIONS_008: dict[str, tuple[str, str]] = {
    "S01": (
        "同一位女性从张开五指的右手已经悬在唯一一碗零食上方的相位，只让手向碗靠近一小段并在接触前停住；五指始终清楚张开，左手留在大腿，人物不拿、不吃零食。侧面手臂与人物同框中景固定，唯一零食碗、桌椅和现有休息区陈设完全不动，不表演捂腹或夸张饥饿",
        "From the phase where the same woman's open five-finger right hand is already hovering above the single snack bowl, move it only a short distance toward the bowl and stop before contact; keep all five fingers clearly open and the left hand on her thigh, without taking or eating any snack. Lock the side medium view containing her arm and body, keep the single bowl, furniture, and existing rest-area setting still, and show no stomach clutching or exaggerated hunger",
    ),
    "S02": (
        "后期保持已经分开落位的恰好三枚无字形状块完全静止，三块的形状、颜色、间距和左右顺序不变；三块只作为饿、渴、场景三个彼此独立的观察字段，不画箭头、连线、流程、图表或人物，也不把任意两块解释成因果",
        "In post-production, hold exactly the three text-free shapes that are already separately placed completely still, preserving their shapes, colors, spacing, and left-to-right order. Treat them only as three independent observation fields for hunger, thirst, and context; add no arrow, connector, flow, chart, or person, and imply no causal relation between any two shapes",
    ),
    "S03": (
        "社区长椅上的同一位女性只完成一次低幅自然呼吸后停稳，双手分别平放在大腿、双脚始终落地，头部、表情和坐姿保持中性；正面中景机位固定，不捂腹、不模拟症状、不加入第二个人或任何新物件",
        "The same woman on the community bench completes one restrained natural breath and settles, keeping both hands separately flat on her thighs, both feet grounded, and her head, expression, and seated posture neutral. Lock the frontal medium camera; do not clutch the stomach, simulate a symptom, introduce a second person, or add any new prop",
    ),
    "S04": (
        "社区长椅旁只保留前景唯一一只普通无品牌玻璃水杯；同一位女性只完成一次朝水杯的短暂转眼并停住，头部、双手和坐姿不动，不伸手、不拿杯、不喝水。镜头在杯子前景与人物侧脸之间只做一次低幅拉焦后固定，不出现吸管、药品、第二只杯子或其他物件",
        "Keep only the single ordinary unbranded glass of water in the foreground beside the community bench. The same woman makes one brief eye movement toward the glass and settles, keeping her head, hands, and seated pose still, without reaching, lifting, or drinking. Make one restrained focus pull between the foreground glass and her side face, then lock; show no straw, medicine, second cup, or other new prop",
    ),
    "S05": (
        "后期保持恰好三张彼此独立的无字环境板完全静止：左侧现有零食陈列、中间现有休息位置、右侧现有午后日光；三板的数量、顺序、边界和内部物件不变。不得加入人物或人物剪影、可读铃声文字、箭头、连续剧情、相机运动或模型动态",
        "In post-production, keep exactly three independent text-free environment panels completely still: the existing snack display on the left, the existing rest setting in the center, and the existing afternoon light on the right. Preserve their count, order, boundaries, and contents; add no person or human silhouette, readable bell copy, arrow, continuous story, camera movement, or model-generated motion",
    ),
    "S06": (
        "社区越肩近景固定，只保留同一位女性、唯一一部手机和现有两只手；左手稳持手机，右手食指依次朝三个分开的后期锚点做恰好三次低幅点按手势后收回，每次指尖始终停在屏幕边框外并且不接触屏幕。手机可见外框高宽比保持约2.05，四角、外框和边框完整，屏幕全程为均匀纯深青色空屏、无渐变无界面，中央70%始终留空；不缩放、不拉伸，2.23、2.36或2.50宽屏比例均一票淘汰",
        "Lock the community over-shoulder close view and preserve only the same woman, the single phone, and the two existing hands. The left hand holds the phone steady while the right index finger makes exactly three restrained tapping gestures toward three separated post-production anchors, then withdraws; the fingertip must remain outside the screen bezel and never touch the screen. Keep the visible outer-body aspect ratio about 2.05, all four corners, outer frame, and bezel complete, and the screen uniformly solid deep teal, blank, interface-free, and non-gradient with the central 70 percent empty throughout. Do not scale or stretch; reject any 2.23, 2.36, or 2.50 wide-screen proportion",
    ),
    "S07": (
        "后期保持恰好三张无字结果板完全静止且彼此独立：左侧现有一份食物、中间现有一杯合理份量的水、右侧现有离开位置的空椅与短路；三板数量、顺序、物件和分隔不变。不得加入人物或手，不让同一人物连续表演三项，不加因果箭头、路径连接、医学结论或模型动态",
        "In post-production, keep exactly three text-free outcome panels completely still and independent: the existing single serving of food on the left, the existing ordinary portion of water in the center, and the existing empty chair and short route for leaving the position on the right. Preserve panel count, order, props, and dividers; add no person or hand, do not stage all three as one person's sequence, and add no causal arrow, connecting path, medical conclusion, or model-generated motion",
    ),
    "S08": (
        "后期保持代表饿与渴的两枚错开大色块以及现有中性小圆点完全静止，三枚现有形状的数量、间距、方向和颜色不变；不让任一形状移动到另一形状，不画因果箭头、连接路径、趋势线、流程图、文字或结论，也不生成任何动态",
        "In post-production, hold the two offset large color shapes representing hunger and thirst plus the existing neutral small dot completely still, preserving the count, spacing, direction, and color of all three existing shapes. Do not move one shape into another, draw a causal arrow, connecting path, trend line, flowchart, text, or conclusion, or generate any motion",
    ),
    "S09": (
        "同一位女性手中的普通玻璃杯已经举起，只完成举杯动作最后一次极小幅落稳后停住，杯子不再靠近嘴唇且人物不喝水。锁定关键物件为恰好1只远处大水壶、1只手中普通玻璃杯、1碗前景零食，三者全程可见且位置关系不变，尤其零食碗不得被遮住；环境中景固定，不移动水壶、不隐藏零食、不新增任何物体，也不表演大量喝水或长时间强忍",
        "The ordinary glass in the same woman's hand is already raised; complete only the final tiny settling phase of the lift and stop, without bringing the glass closer to her lips or drinking. Lock the key prop count to exactly one distant carafe, one ordinary glass in hand, and one foreground snack bowl, all visible throughout with unchanged spatial relationships and the bowl never obscured. Keep the environmental medium shot fixed; do not move the carafe, hide the snack, add any object, or portray excessive water drinking or prolonged forced restraint",
    ),
    "S10": (
        "后期保持社区短路上恰好三枚不同形状完全静止，三枚形状的数量、前后顺序、颜色、间距和现有短路构图不变；只作为下次观察的中性参照，不加人物、文字、数字、因果箭头、评分、趋势、医学建议或模型动态",
        "In post-production, keep exactly three different shapes on the short community route completely still, preserving their count, front-to-back order, colors, spacing, and the existing route composition. Use them only as neutral reference marks for a later observation; add no person, text, number, causal arrow, score, trend, medical advice, or model-generated motion",
    ),
}


SHOT_SEMANTIC_CONTRACTS_008: dict[str, dict[str, Any]] = {
    "S01": {"storyboard": {"人物动作": ("社区休息区人物伸向零食前停手",), "相机": ("侧面手臂与人物同框中景",), "ai_source_layer": ("人物伸手后停住", "不拿起零食")}, "prompt_zh": ("张开五指", "唯一一碗零食", "向碗靠近一小段并在接触前停住", "左手留在大腿", "不拿、不吃零食")},
    "S02": {"storyboard": {"人物动作": ("饿、渴、场景三个无字形状分开落位",), "相机": ("无相机运动",), "ai_source_layer": ("无AI动态源", "三枚不同形状色块")}, "prompt_zh": ("恰好三枚无字形状块", "三个彼此独立的观察字段", "不画箭头、连线、流程、图表或人物", "不把任意两块解释成因果")},
    "S03": {"storyboard": {"人物动作": ("人物坐在长椅", "双手自然放腿上"), "相机": ("正面中景固定",), "ai_source_layer": ("一次自然呼吸", "不做夸张动作")}, "prompt_zh": ("一次低幅自然呼吸", "双手分别平放在大腿", "双脚始终落地", "不捂腹、不模拟症状")},
    "S04": {"storyboard": {"人物动作": ("普通水杯放在长椅一侧", "人物看向杯子"), "相机": ("水杯前景与侧脸中景拉焦",), "ai_source_layer": ("只做转眼动作", "不喝水")}, "prompt_zh": ("唯一一只普通无品牌玻璃水杯", "一次朝水杯的短暂转眼", "不伸手、不拿杯、不喝水", "只做一次低幅拉焦", "不出现吸管、药品、第二只杯子")},
    "S05": {"storyboard": {"人物动作": ("零食摊、休息铃色块、午后日光三张环境板",), "相机": ("无相机运动", "三板错位切换"), "ai_source_layer": ("无AI动态源", "无字场景剪影板")}, "prompt_zh": ("恰好三张彼此独立的无字环境板", "现有零食陈列", "现有休息位置", "现有午后日光", "不得加入人物或人物剪影", "箭头、连续剧情")},
    "S06": {"storyboard": {"人物动作": ("人物在黑屏手机依次点按三个空位",), "相机": ("越肩近景固定",), "ai_source_layer": ("人物三次轻点", "不生成界面")}, "prompt_zh": ("唯一一部手机", "恰好三次低幅点按手势", "指尖始终停在屏幕边框外", "外框高宽比保持约2.05", "四角、外框和边框完整", "均匀纯深青色空屏", "中央70%始终留空", "不缩放、不拉伸", "2.23、2.36或2.50宽屏比例均一票淘汰")},
    "S07": {"storyboard": {"人物动作": ("三个独立结果板", "吃一份、喝适量水、离开位置"), "相机": ("无相机运动", "不让人物三选一连续表演"), "ai_source_layer": ("无AI动态源", "三个确定性结果板")}, "prompt_zh": ("恰好三张无字结果板", "完全静止且彼此独立", "不让同一人物连续表演三项", "不加因果箭头", "医学结论")},
    "S08": {"storyboard": {"人物动作": ("饿与渴两个色块错开", "不做因果箭头"), "相机": ("顶视确定性图形板",), "ai_source_layer": ("无AI动态源", "禁止因果路径")}, "prompt_zh": ("饿与渴的两枚错开大色块", "现有中性小圆点", "不画因果箭头、连接路径、趋势线、流程图", "不生成任何动态")},
    "S09": {"storyboard": {"人物动作": ("人物把大水壶留在远处", "只拿普通杯", "零食保持未隐藏"), "相机": ("环境中景固定",), "ai_source_layer": ("人物拿起普通杯后停住",)}, "prompt_zh": ("普通玻璃杯已经举起", "最后一次极小幅落稳后停住", "恰好1只远处大水壶、1只手中普通玻璃杯、1碗前景零食", "零食碗不得被遮住", "不新增任何物体", "不表演大量喝水或长时间强忍")},
    "S10": {"storyboard": {"人物动作": ("三类形状沿社区步道短线排列",), "相机": ("无相机运动",), "ai_source_layer": ("无AI动态源", "确定性结束板")}, "prompt_zh": ("社区短路上恰好三枚不同形状", "完全静止", "中性参照", "不加人物、文字、数字、因果箭头、评分、趋势、医学建议")},
}


VISUAL_REVIEW_NOTES_008 = {
    "S01": "同一人物坐在现有休息区，右手五指完整张开并悬在唯一零食碗上方，左手留在大腿",
    "S02": "暖米白板上恰好三枚形状、颜色和间距不同的无字色块，彼此无箭头或连线",
    "S03": "社区长椅正面坐姿人物，双手分别平放大腿、双脚落地，适合仅做一次自然呼吸",
    "S04": "社区长椅旁前景恰好一只普通玻璃水杯，人物侧脸视线朝杯，不饮用",
    "S05": "恰好三张无人环境板，依次为现有零食陈列、休息位置和午后日光；铃意仅由后期文案说明",
    "S06": "社区越肩唯一手机：外框约2.05、四角与边框完整、均匀纯深青空屏，指尖在屏外且中央70%留空",
    "S07": "恰好三张彼此独立的无人结果板：一份食物、一杯水、空椅与短路；不得串成同一人连续剧情",
    "S08": "两枚错开大色块及一个现有中性小圆点，无箭头路径；小圆点不解释为第三种因果变量",
    "S09": "同一人物手中一只普通玻璃杯、远处一只大水壶、前景一碗零食，关键数量与空间关系清楚",
    "S10": "社区短路上恰好三枚不同形状，沿路前后分开排列，无文字、数字、评分或医学结论",
}


PROMPT_ACTIONS_009: dict[str, tuple[str, str]] = {
    "S01": (
        "必须分别生成 Source A 和 Source B，并把正式首帧作为同一办公位的匹配构图：Source A 只保留较早下午的自然窗光，Source B 只保留完全相同机位和构图的较晚下午光线；同一位女性始终坐定，双手停在唯一一把键盘旁，唯一一台纯深色显示器和桌椅位置不动，人物身份、米色开衫、低饱和蓝色内搭、深蓝长裤、姿势和物件数量一致。不得在单条 clip 内制作硬切或分屏，不做叠化、人物融合、时间码或可读时钟，也不让人物输入或离座；两条独立源只在后期硬切",
        "You must generate Source A and Source B separately, using the formal first frame as the matched composition of the same workstation: Source A keeps only the earlier-afternoon natural window light, while Source B keeps only the later-afternoon light at the identical camera position and composition. Keep the same woman seated with both hands paused beside the single keyboard, the single solid-dark monitor, desk, and chair fixed, and preserve identity, beige cardigan, muted-blue top, navy trousers, pose, and prop count. Do not create a hard cut or split screen inside one clip, and add no dissolve, person blend, timecode, readable clock, typing, or leaving the seat; hard-cut the two independent sources only in post",
    ),
    "S02": (
        "后期保持现有一枚金色空心圆环和下方恰好三枚个人路径色块的形状、数量、顺序、间距与暖米白背景不变，只让金色圆环做一次低幅淡出，三枚色块全程静止并在淡出后留下；不把圆环做成带指针或刻度的可读时钟，不出现数字、时间、统一时段结论、评分图、效率仪表或模型动态，不上传Grok",
        "In post-production, preserve the existing single hollow gold ring and exactly three personal-path color blocks below it, including their shapes, count, order, spacing, and warm off-white background. Fade only the gold ring once at low amplitude while all three blocks remain completely still and stay after the fade. Do not turn the ring into a readable clock with hands or ticks, and add no number, time, universal-time conclusion, score chart, efficiency dashboard, or model-generated motion; do not upload to Grok",
    ),
    "S03": (
        "同一位女性保持越肩坐姿并注视唯一一台纯蓝灰空屏显示器，左手与唯一一把键盘不动，右手只在唯一一个触控板上完成一次短距离单向拖动后停住；一个小色块的位移只留给后期确定性叠加，模型画面中的屏幕始终纯色、无界面、无任务卡。越肩中景固定，显示器、键盘、触控板和双手的数量与位置关系不变；不得拖多个块、点按、继续输入或转头看镜头",
        "Keep the same woman seated over the shoulder and looking at the single solid blue-gray blank monitor; keep her left hand and the single keyboard still while her right hand performs exactly one short one-way drag on the single trackpad and stops. Reserve the movement of one small color block for deterministic post-production only; the model-rendered screen must remain solid, blank, interface-free, and card-free. Lock the over-shoulder medium camera and preserve the count and spatial relationship of the monitor, keyboard, trackpad, and two hands; do not drag multiple blocks, tap, continue typing, or turn toward the camera",
    ),
    "S04": (
        "同一位女性从已经坐直、双手已离开工作台并悬在大腿上方的相位，只完成一次极小幅坐姿落稳并把双手自然落在大腿后停住；侧面半身中景全程固定，人物不输入、不离座。保持一人、一台纯深色显示器以及原工作位的一把键盘关系不变；正式首帧中键盘未清楚入镜，因此画外键盘不得移入画面，也不得补出新键盘或其他物件",
        "From the phase where the same woman is already sitting upright with both hands off the work surface and hovering above her thighs, complete only one tiny seated settling movement, lower both hands naturally onto her thighs, and stop. Keep the side half-body medium shot locked, with no typing or leaving the chair. Preserve one person, one solid-dark monitor, and the workstation relationship to its single keyboard; because the keyboard is not clearly visible in the formal first frame, it must remain out of frame rather than moving into view, and no new keyboard or other prop may appear",
    ),
    "S05": (
        "同一位女性从当前看向左侧窗光、双手已经相合放在大腿的相位继续，只让视线和头部低幅回到右侧唯一一台纯深色显示器一次并停住；三分之二侧脸近景固定，双手、坐姿、显示器、键盘、窗和办公室陈设不动。不得再次转回窗外、长时间望窗、输入、做手势或加入第二个人",
        "Continue from the current phase where the same woman is looking toward the window light on the left with both hands joined on her lap. Move only her gaze and head at low amplitude back to the single solid-dark monitor on the right once, then stop. Lock the three-quarter profile close view and keep her hands, seated pose, monitor, keyboard, window, and office setting still. Do not turn back toward the window again, prolong the window gaze, type, gesture, or introduce a second person",
    ),
    "S06": (
        "同一位女性从双手已经悬在唯一一把白色键盘上方的收尾相位，只完成最后一次极短输入，随后双手同时向后撤离键盘并落稳在桌边，不站起、不走动；唯一一台纯深色显示器、唯一一个白色鼠标、键盘和现有桌面薄物件均不移动。镜头只从桌面手部近景做一次低幅转正到人物中景后固定，不跟随走动；双手不同步、再次回键盘或多次输入均淘汰",
        "From the finishing phase where both hands of the same woman are already hovering above the single white keyboard, complete only one final very short input, then withdraw both hands together from the keyboard and settle them at the desk edge, without standing or walking. Keep the single solid-dark monitor, single white mouse, keyboard, and existing thin tabletop item stationary. Make only one restrained reframe from the tabletop hand close view toward the frontal medium view and then lock, never tracking movement; reject asynchronous hands, any return to the keyboard, or repeated typing",
    ),
    "S07": (
        "这是同一任务在另一个下午时点的新一段，不与其他时点同屏：同一位女性从双手已落在唯一一把白色键盘上的相位，只完成一次短输入后停住，视线始终朝唯一一台纯深色显示器；固定中景、较晚下午窗光和现有构图不变，保留唯一一个白色鼠标以及画面右缘既有的一只杯子，所有物件数量和位置不变。不得分屏、硬切到另一时点、换景、换人、移动杯子、输入多项或持续打字",
        "This is a new segment of the same task at another afternoon time point, never shown beside another time point. From the phase where both hands of the same woman already rest on the single white keyboard, let her complete exactly one short input and stop while her gaze remains on the single solid-dark monitor. Lock the medium camera, later-afternoon window light, and existing composition, preserving the single white mouse and the one existing cup at the right edge with all prop counts and positions unchanged. Do not split the screen, hard-cut to another time point, change scene or person, move the cup, enter multiple items, or type continuously",
    ),
    "S08": (
        "后期保持现有左右恰好两个圆角色块和中央一枚由两根竖条组成的中性暂停符完全静止，两个记录块的颜色、尺寸、间距和左右关系不变；只作为两次独立记录与暂停边界，不画箭头、因果连线、基准线、评分、成绩、KPI或效率仪表，不加入文字、人物或模型动态，不上传Grok",
        "In post-production, hold the existing exactly two rounded color blocks and the single neutral pause symbol made of two vertical bars between them completely still, preserving the blocks' colors, sizes, spacing, and left-right relationship. Use them only as two independent records and a pause boundary; add no arrow, causal connector, benchmark line, score, grade, KPI, efficiency dashboard, text, person, or model-generated motion, and do not upload to Grok",
    ),
    "S09": (
        "同一位女性从输入已经停止、双手已经在桌边相合的相位继续，只让眼睛沿现有方向朝左侧窗光移动一次并停住，双手不得分开或再次触碰唯一一把键盘和唯一一个鼠标；侧面办公室中景固定，唯一一台纯深色显示器、键盘、鼠标、人物坐姿和窗光不变。不得重新打字、转动全身、离座、反复看窗或让后期安全区遮住眼睛与双手",
        "Continue from the phase where the same woman has already stopped typing and her hands are already joined at the desk edge. Move only her eyes once along the existing direction toward the window light on the left and stop; her hands must not separate or touch the single keyboard or single mouse again. Lock the side office medium shot and preserve the single solid-dark monitor, keyboard, mouse, seated pose, and window light. Do not resume typing, rotate her body, leave the seat, look back and forth, or let the post-production safe area cover her eyes or hands",
    ),
    "S10": (
        "后期保持现有竖向周历抽象板的恰好七个无字圆角色块及从上到下顺序不变，只让当前第四位唯一一个浅蓝色难任务块移动一次到另一个既有空位后停住，其余六块完全不动；不得移动第二项、增减色块、出现可读日期或星期、数字、箭头、评分、完成率、KPI、效率仪表或医学结论，不上传Grok",
        "In post-production, preserve exactly the seven text-free rounded blocks and their top-to-bottom order in the existing abstract weekly board. Move only the single light-blue hard-task block currently in the fourth position once to another existing open slot and stop, while the other six blocks remain completely still. Do not move a second item, change the block count, or show readable dates or weekdays, numbers, arrows, scores, completion rates, KPI, efficiency dashboards, or medical conclusions; do not upload to Grok",
    ),
}


SHOT_SEMANTIC_CONTRACTS_009: dict[str, dict[str, Any]] = {
    "S01": {"storyboard": {"人物动作": ("同一办公位在较早与较晚日光下匹配切换",), "相机": ("固定广角匹配构图",), "ai_source_layer": ("两段环境动态源", "人物坐定准备开始")}, "prompt_zh": ("分别生成 Source A 和 Source B", "Source A", "较早下午", "Source B", "较晚下午", "不得在单条 clip 内制作硬切或分屏", "两条独立源只在后期硬切", "叠化、人物融合、时间码或可读时钟")},
    "S02": {"storyboard": {"人物动作": ("黄金色时钟轮廓淡出", "个人路径色块留下"), "相机": ("无相机运动",), "ai_source_layer": ("无AI动态源", "确定性图形板")}, "prompt_zh": ("一枚金色空心圆环", "恰好三枚个人路径色块", "只让金色圆环做一次低幅淡出", "不把圆环做成带指针或刻度的可读时钟", "效率仪表", "不上传Grok")},
    "S03": {"storyboard": {"人物动作": ("只拖出一个小色块",), "相机": ("越肩中景", "屏幕纯色无界面"), "ai_source_layer": ("一次拖动", "任务卡由后期叠加")}, "prompt_zh": ("唯一一台纯蓝灰空屏显示器", "唯一一个触控板", "一次短距离单向拖动", "一个小色块的位移只留给后期确定性叠加", "不得拖多个块")},
    "S04": {"storyboard": {"人物动作": ("人物坐直", "手离键盘"), "相机": ("侧面半身中景固定",), "ai_source_layer": ("人物只做坐直动作",)}, "prompt_zh": ("已经坐直", "双手已离开工作台", "一次极小幅坐姿落稳", "人物不输入、不离座", "画外键盘不得移入画面")},
    "S05": {"storyboard": {"人物动作": ("看向窗外一秒再回到屏幕",), "相机": ("三分之二侧脸近景",), "ai_source_layer": ("只做一次视线往返",)}, "prompt_zh": ("看向左侧窗光", "双手已经相合放在大腿", "回到右侧唯一一台纯深色显示器一次", "不得再次转回窗外")},
    "S06": {"storyboard": {"人物动作": ("完成小段后收回双手",), "相机": ("桌面手部转正面中景", "不跟随走动"), "ai_source_layer": ("结束输入并收手",)}, "prompt_zh": ("最后一次极短输入", "双手同时向后撤离键盘", "不站起、不走动", "唯一一个白色鼠标", "双手不同步、再次回键盘或多次输入均淘汰")},
    "S07": {"storyboard": {"人物动作": ("第二个下午", "同构图重新开始同类小段"), "相机": ("固定中景", "光线匹配切换"), "ai_source_layer": ("只完成开始输入动作",)}, "prompt_zh": ("同一任务在另一个下午时点的新一段", "不与其他时点同屏", "只完成一次短输入后停住", "画面右缘既有的一只杯子", "不得分屏、硬切到另一时点")},
    "S08": {"storyboard": {"人物动作": ("两次记录色块并列", "中性暂停图形"), "相机": ("无相机运动",), "ai_source_layer": ("无AI动态源", "确定性对照与暂停信息板")}, "prompt_zh": ("恰好两个圆角色块", "两根竖条组成的中性暂停符", "两次独立记录与暂停边界", "基准线、评分、成绩、KPI或效率仪表", "不上传Grok")},
    "S09": {"storyboard": {"人物动作": ("停下输入", "视线转向窗光"), "相机": ("办公位侧面中景固定",), "ai_source_layer": ("停手并转移视线一次",)}, "prompt_zh": ("输入已经停止", "双手已经在桌边相合", "眼睛沿现有方向朝左侧窗光移动一次", "唯一一把键盘和唯一一个鼠标", "不得重新打字")},
    "S10": {"storyboard": {"人物动作": ("一周日程色块中仅移动一个难任务块",), "相机": ("无相机运动",), "ai_source_layer": ("无AI动态源", "确定性结束板")}, "prompt_zh": ("恰好七个无字圆角色块", "当前第四位唯一一个浅蓝色难任务块", "移动一次", "其余六块完全不动", "可读日期或星期", "KPI、效率仪表", "不上传Grok")},
}


VISUAL_REVIEW_NOTES_009 = {
    "S01": "同一人物在普通办公室坐定，唯一一台纯深色显示器、唯一一把键盘和双手清楚；只适合固定匹配机位下的早/晚光硬切，不能分屏",
    "S02": "无人无字静态板含一枚金色空心圆环和下方恰好三枚色块；圆环无指针刻度，不得转成可读时钟或指标仪表",
    "S03": "越肩构图中一台纯蓝灰空屏显示器、一把键盘和一个触控板清楚；右手已在触控板，屏上小色块必须留给后期",
    "S04": "同一人物已经坐直且双手离开工作台，一台纯深色显示器可见；键盘未清楚入镜是非阻断限制，提示词锁定画外不补物",
    "S05": "同一人物正看左侧窗光，双手自然相合在大腿；右侧一台纯深色显示器和键盘保持不动，只允许视线回屏一次",
    "S06": "同一人物双手完整悬在一把白色键盘上方，一台纯深色显示器、一个白色鼠标及既有薄桌面物件可见；只做输入结束后双手同步撤离",
    "S07": "同一人物在较晚下午光下已开始输入；一台显示器、一把键盘、一个白色鼠标及画面右缘既有一只杯子均须保持，单镜不呈现另一时点",
    "S08": "无人无字静态板含左右恰好两个圆角色块和中央双竖条暂停符；不得解释成评分、基准或效率仪表",
    "S09": "同一人物已停手并朝左侧窗光，双手相合；一台显示器、一把键盘和一个鼠标清楚，只允许视线沿现有方向移动一次",
    "S10": "无人无字抽象周历板含恰好七个纵向圆角色块，其中第四块为唯一浅蓝色难任务；只能后期移动这一项且不上传Grok",
}


PROMPT_ACTIONS_010: dict[str, tuple[str, str]] = {
    "S01": (
        "后期保持俯视客厅桌面上的恰好七块无字记录块完全静止：六块同色青绿块继续留在圆形内，一块浅桃例外块继续留在圆形外，数量、颜色、内外关系、间距、桌面和窗光均不变；只做一次低幅整体淡入，不增减类别，不改成数字、统计图、周历或待办界面，不上传Grok",
        "In post-production, hold exactly seven text-free record blocks completely still in the overhead living-room tabletop composition: six matching teal blocks remain inside the circle and one peach exception block remains outside it, with count, color, inside/outside relation, spacing, tabletop, and window light unchanged. Apply one low-amplitude whole-frame fade-in only; do not add or remove a category or turn the board into numbers, a chart, weekly calendar, or task interface, and do not upload to Grok",
    ),
    "S02": (
        "以正式首帧为唯一构图参考：45岁中国女性在沙发上坐稳，双脚落地，右手单手持唯一一部手机背壳，左手平放在左侧大腿；正面中远景、人物、右手、手机背壳与左手全部保持静态，不抬起、不转动、不点按。米色开衫、低饱和蓝色内搭、深蓝长裤、沙发和光线不变；出现马克杯、第二部手机、额外人物或额外手，或手机翻向另一面，均一票淘汰",
        "Use the formal first frame as the sole composition reference: keep the 45-year-old Chinese woman settled on the sofa with both feet grounded; her right hand alone holds the back shell of the only phone while her left hand stays flat on her left thigh. Hold the frontal medium-long composition, woman, right hand, phone back, and left hand completely static—no lifting, turning, or tapping. Preserve the beige cardigan, muted-blue top, navy trousers, sofa, and light; reject any mug, second phone, extra person, extra hand, or turn toward the opposite face of the phone",
    ),
    "S03": (
        "后期保持现有上下恰好两张无字生活板完全静止：上板仅为夜间关灯环境，下板仅为清晨拉帘环境；两板的床、灯、窗、窗帘、手部数量、上下位置和光线相位不变，只用一次确定性硬切安排前后顺序。不得补人物因果表演、时钟、数字、周历、待办界面或模型动态，不上传Grok",
        "In post-production, hold the existing exactly two text-free life panels completely still: the upper panel remains only the nighttime light-off environment and the lower panel only the morning curtain-opening environment. Preserve the bed, lamp, window, curtains, hand count, vertical placement, and light phase, using one deterministic hard cut only to order them. Add no person-led causal performance, clock, number, weekly calendar, task interface, or model-generated motion, and do not upload to Grok",
    ),
    "S04": (
        "同一位女性从正式首帧双手托住唯一一只正面可见餐盘、身体已迈出一步的相位继续，只完成这一步的最后落脚并停住，不再迈第二步；餐桌侧面全身中景固定，餐盘始终正面可辨且不倾斜、不旋转，双手、双脚和单盘完整保留。出现边缘第二只盘、餐具、额外人物或额外手，或餐盘转为侧面，均一票淘汰",
        "Continue from the formal-frame phase in which the same woman already holds the only front-readable plate with both hands and is mid-step; complete only the final foot placement of that one step and stop, with no second step. Lock the side full-body dining-table medium view, keeping the plate front-readable without tilt or rotation and preserving both hands, both feet, and the single-plate count. Reject a second plate at the edge, any utensil, extra person, extra hand, or an edge-on plate",
    ),
    "S05": (
        "必须分别生成 Source A 和 Source B，并把正式首帧作为同一房间、同一人物和同一把椅子的匹配依据，形成两个彼此独立的时点：Source A 只让人物手扶椅背、肩部轻微放松后短暂停住；Source B 表示稍后，她只把同一把椅子向原位轻推一小段并停住。两个侧面全身机位分别固定，人物身份、服装、房间、椅子和折叠布数量不变；不得在单条 clip 内制作硬切或分屏，不得叠化、角色融合、同步发生、夸张虚弱表演、诊断暗示或新增任务物件，两条独立源只在后期硬切",
        "You must generate Source A and Source B separately, using the formal first frame as the matching reference for the same room, woman, and single chair: in Source A, she only rests one hand on the chair back, lets her shoulders relax slightly, and pauses; in Source B, at a later time point, she only moves that same chair a short distance back toward its place and stops. Lock each side full-body camera and preserve identity, clothing, room, chair, and folded-cloth count; do not create a hard cut or split screen inside one clip, and reject dissolve, person blending, simultaneous phases, exaggerated weakness, diagnostic implication, or any new task prop; hard-cut the two independent sources only in post",
    ),
    "S06": (
        "后期保持俯拍置物台上的恰好七个位置完全静止：六块青绿色实心记录块保持原位，唯一一处暖米白空位只保留现有细边框，不填色、不写零、不补猜；数量、两行排列、植物、镜面边缘和光影均不变。不得改成评分格、周历、待办界面、数字或模型动态，不上传Grok",
        "In post-production, hold exactly seven positions completely still on the overhead console: keep the six solid teal record blocks in place and retain the single warm off-white empty position only as its existing thin outline, without filling it, writing zero, or guessing a value. Preserve the count, two-row arrangement, plant, mirror edge, and light. Do not turn it into a score grid, weekly calendar, task interface, numbers, or model-generated motion, and do not upload to Grok",
    ),
    "S07": (
        "后期保持现有恰好七块无字记录块完全静止：左侧六块同色青绿块继续组成紧密的两行聚类，右侧唯一一块浅桃例外块继续与聚类分开；数量、颜色、间距、置物台和光线不变。不画数字、百分比、统计图、因果箭头、周历、待办界面或医学结论，不上传Grok",
        "In post-production, hold the existing exactly seven text-free record blocks completely still: the six matching teal blocks remain as the tight two-row cluster on the left, while the single peach exception remains separated on the right. Preserve count, color, spacing, console, and light. Add no number, percentage, statistical chart, causal arrow, weekly calendar, task interface, or medical conclusion, and do not upload to Grok",
    ),
    "S08": (
        "俯拍固定构图中保持恰好三件普通生活物：现有左手握着的一只灰色陶杯、一块右上方浅桃色折叠布和一个右下方圆形木杯垫。只让灰色陶杯随现有左手沿最短路径移动一次到圆形木杯垫中央并停住，折叠布和木杯垫从头到尾完全不动；不替换物件，不同时移动第二件物品，不新增手、纸张、笔或本册，任一数量或位置关系漂移均一票淘汰",
        "In the locked overhead composition, preserve exactly three ordinary household items: the single gray ceramic cup already held by the existing left hand, the peach folded cloth at upper right, and the round wooden coaster at lower right. Move only the gray cup once along the shortest path to the center of the round coaster and stop, with the existing hand accompanying it; keep the folded cloth and wooden coaster completely motionless throughout. Do not replace an item, move a second item, or add a hand, paper, pen, or notebook; reject any drift in count or spatial relationship",
    ),
    "S09": (
        "后期保持现有左右两组无字块及中央一条短连接线完全静止：左组五块、右组两块，数量、顺序、间距、短线长度、背景陈设和光线不变；这只表示七天的编辑观察窗，不形成习惯或稳定结论。不得画周历、日期、星期、待办界面、结论徽章、因果箭头、评分或医学结论，不上传Grok",
        "In post-production, hold the existing two text-free groups and the single short connector completely still: five blocks on the left and two on the right, preserving count, order, spacing, connector length, background objects, and light. This represents only a seven-day editorial observation window, not a habit or stable conclusion. Do not draw a weekly calendar, date, weekday, task interface, conclusion badge, causal arrow, score, or medical conclusion, and do not upload to Grok",
    ),
    "S10": (
        "后期保持现有浅青短路径、路径上的恰好七块无字米白字段块和起点旁唯一一枚浅桃安全标记完全静止，数量、顺序、间距、路径方向、木桌和生活静物不变；字段只留给下一轮，当下安全含义仅由后期文案表达。不得做路径动画、最终成绩、周历、待办界面、数字、医疗建议或医学结论，不上传Grok",
        "In post-production, hold the existing pale-teal short path, exactly seven text-free warm-white field blocks along it, and the single peach safety marker beside the starting point completely still. Preserve count, order, spacing, path direction, wooden table, and household still life; reserve the fields for the next round and express immediate safety only with later copy. Add no path animation, final score, weekly calendar, task interface, number, medical advice, or medical conclusion, and do not upload to Grok",
    ),
}


SHOT_SEMANTIC_CONTRACTS_010: dict[str, dict[str, Any]] = {
    "S01": {"storyboard": {"人物动作": ("七块记录色板围成一圈", "重复与例外用不同位置表示"), "相机": ("俯视确定性构图", "低幅淡入"), "ai_source_layer": ("无AI动态源", "七块无字记录板")}, "prompt_zh": ("恰好七块", "六块同色青绿块", "一块浅桃例外块", "圆形内", "圆形外", "一次低幅整体淡入", "周历或待办界面")},
    "S02": {"storyboard": {"人物动作": ("人物坐在沙发上", "看向黑屏手机"), "相机": ("正面中远景固定",), "ai_source_layer": ("人物只抬起手机看一眼",)}, "prompt_zh": ("双脚落地", "右手单手持唯一一部手机背壳", "左手平放在左侧大腿", "全部保持静态", "不抬起、不转动、不点按", "马克杯", "第二部手机")},
    "S03": {"storyboard": {"人物动作": ("夜晚关灯", "早晨拉帘", "两张生活板"), "相机": ("无相机运动",), "ai_source_layer": ("无AI动态源", "确定性日夜剪影板")}, "prompt_zh": ("恰好两张无字生活板", "夜间关灯", "清晨拉帘", "确定性硬切", "时钟、数字、周历、待办界面")},
    "S04": {"storyboard": {"人物动作": ("收好餐具并离开餐桌",), "相机": ("餐桌侧面全身中景",), "ai_source_layer": ("收一只餐具后离开一步",)}, "prompt_zh": ("唯一一只正面可见餐盘", "完成这一步的最后落脚", "不再迈第二步", "侧面全身中景固定", "边缘第二只盘")},
    "S05": {"storyboard": {"人物动作": ("先倚椅发沉", "另一时点顺畅完成一小事"), "相机": ("相同房间两个机位硬切",), "ai_source_layer": ("两条独立人物源", "短暂停顿", "完成小动作")}, "prompt_zh": ("分别生成 Source A 和 Source B", "Source A", "肩部轻微放松后短暂停住", "Source B", "同一把椅子向原位轻推一小段", "不得在单条 clip 内制作硬切或分屏", "两条独立源只在后期硬切", "诊断暗示")},
    "S06": {"storyboard": {"人物动作": ("七块色板中一块保持暖米白空白",), "相机": ("无相机运动",), "ai_source_layer": ("无AI动态源", "确定性缺失板")}, "prompt_zh": ("恰好七个位置", "六块青绿色实心记录块", "唯一一处暖米白空位", "不填色、不写零、不补猜", "评分格、周历、待办界面")},
    "S07": {"storyboard": {"人物动作": ("相同颜色色块靠拢", "一块例外色保持距离"), "相机": ("无相机运动",), "ai_source_layer": ("无AI动态源", "确定性聚类板")}, "prompt_zh": ("恰好七块", "六块同色青绿块", "唯一一块浅桃例外块", "两行聚类", "百分比、统计图", "医学结论")},
    "S08": {"storyboard": {"人物动作": ("三个生活物件中只移动一个位置",), "相机": ("俯拍家中置物台固定",), "ai_source_layer": ("只移动一个普通生活物件",)}, "prompt_zh": ("恰好三件普通生活物", "一只灰色陶杯", "一块右上方浅桃色折叠布", "一个右下方圆形木杯垫", "只让灰色陶杯", "折叠布和木杯垫从头到尾完全不动", "不同时移动第二件物品")},
    "S09": {"storyboard": {"人物动作": ("工作日与周末两组色块", "一条短线连接"), "相机": ("无相机运动",), "ai_source_layer": ("无AI动态源", "确定性边界板")}, "prompt_zh": ("左组五块、右组两块", "一条短连接线", "七天的编辑观察窗", "不形成习惯或稳定结论", "不得画周历", "待办界面", "医学结论")},
    "S10": {"storyboard": {"人物动作": ("同组字段沿路径进入下一周", "安全提示停在路径起点"), "相机": ("无相机运动",), "ai_source_layer": ("无AI动态源", "确定性结束板")}, "prompt_zh": ("恰好七块无字米白字段块", "唯一一枚浅桃安全标记", "起点", "完全静止", "周历、待办界面", "医疗建议或医学结论")},
}


VISUAL_REVIEW_NOTES_010 = {
    "S01": "俯视桌面恰好七块：六块同色青绿块围成圆形，一块浅桃例外块在圆外；仅适合确定性静态板",
    "S02": "同一人物双脚落地坐在沙发；仅右手持唯一手机背壳，左手平放左侧大腿，全程静态，不作相反一面的任何声称",
    "S03": "上下恰好两张生活板分别呈现夜间关灯与清晨拉帘；无时钟、数字或周历",
    "S04": "同一人物双手托住唯一一只正面可见餐盘，处于一步的迈步相位；只完成当前步后停住",
    "S05": "同一人物在房间内手扶唯一一把椅子，折叠布留在右后方；适合两个独立时点硬切，不作症状或诊断演绎",
    "S06": "俯拍恰好七个位置，其中六块青绿实心、一处暖米白空框；空位不得补零或填满",
    "S07": "左侧六块同色青绿块成两行聚类，右侧唯一浅桃块分开；仅作静态聚类与例外板",
    "S08": "俯拍三物清楚：左手中的灰色陶杯、右上浅桃折叠布、右下圆形木杯垫；只允许杯移动，另两物保持",
    "S09": "左右两组分别五块与两块，由一条短线连接；只表示编辑观察窗，不得改成周历、待办或结论板",
    "S10": "浅青短路径上恰好七块米白字段块，起点旁一枚浅桃安全标记；全程静态，不形成医疗结论",
}


PROMPT_ACTIONS_BY_CONTENT = {
    "HC20260810-001": PROMPT_ACTIONS,
    "HC20260810-002": PROMPT_ACTIONS_002,
    "HC20260810-003": PROMPT_ACTIONS_003,
    "HC20260810-004": PROMPT_ACTIONS_004,
    "HC20260810-005": PROMPT_ACTIONS_005,
    "HC20260810-006": PROMPT_ACTIONS_006,
    "HC20260810-007": PROMPT_ACTIONS_007,
    "HC20260810-008": PROMPT_ACTIONS_008,
    "HC20260810-009": PROMPT_ACTIONS_009,
    "HC20260810-010": PROMPT_ACTIONS_010,
}
SHOT_SEMANTIC_CONTRACTS_BY_CONTENT = {
    "HC20260810-001": SHOT_SEMANTIC_CONTRACTS,
    "HC20260810-002": SHOT_SEMANTIC_CONTRACTS_002,
    "HC20260810-003": SHOT_SEMANTIC_CONTRACTS_003,
    "HC20260810-004": SHOT_SEMANTIC_CONTRACTS_004,
    "HC20260810-005": SHOT_SEMANTIC_CONTRACTS_005,
    "HC20260810-006": SHOT_SEMANTIC_CONTRACTS_006,
    "HC20260810-007": SHOT_SEMANTIC_CONTRACTS_007,
    "HC20260810-008": SHOT_SEMANTIC_CONTRACTS_008,
    "HC20260810-009": SHOT_SEMANTIC_CONTRACTS_009,
    "HC20260810-010": SHOT_SEMANTIC_CONTRACTS_010,
}
VISUAL_REVIEW_NOTES_BY_CONTENT = {
    "HC20260810-001": VISUAL_REVIEW_NOTES,
    "HC20260810-002": VISUAL_REVIEW_NOTES_002,
    "HC20260810-003": VISUAL_REVIEW_NOTES_003,
    "HC20260810-004": VISUAL_REVIEW_NOTES_004,
    "HC20260810-005": VISUAL_REVIEW_NOTES_005,
    "HC20260810-006": VISUAL_REVIEW_NOTES_006,
    "HC20260810-007": VISUAL_REVIEW_NOTES_007,
    "HC20260810-008": VISUAL_REVIEW_NOTES_008,
    "HC20260810-009": VISUAL_REVIEW_NOTES_009,
    "HC20260810-010": VISUAL_REVIEW_NOTES_010,
}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _as_posix(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _require_regular_file(path: Path, label: str) -> None:
    _assert_no_reparse_ancestors(path)
    if not path.is_file() or path.is_symlink():
        raise ManualPackError(f"missing or unsafe {label}: {path}")
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    if attributes & REPARSE_POINT_FLAG:
        raise ManualPackError(f"reparse point forbidden for {label}: {path}")


def _lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _inspect_lexical_chain(path: Path) -> None:
    current = path
    while True:
        if os.path.lexists(current):
            attributes = getattr(current.lstat(), "st_file_attributes", 0)
            if current.is_symlink() or attributes & REPARSE_POINT_FLAG:
                raise ManualPackError(f"reparse path forbidden: {current}")
        if current.parent == current:
            break
        current = current.parent


def _assert_no_reparse_ancestors(path: Path) -> Path:
    lexical = _lexical_absolute(path)
    _inspect_lexical_chain(lexical)
    resolved = lexical.resolve(strict=False)
    _inspect_lexical_chain(resolved)
    return resolved


def _require_within(path: Path, parent: Path, label: str) -> None:
    try:
        path.relative_to(parent)
    except ValueError as exc:
        raise ManualPackError(f"{label} escapes required root: {path}") from exc


def _load_json(path: Path, label: str) -> dict[str, Any]:
    _require_regular_file(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManualPackError(f"invalid {label}: {path}") from exc
    if not isinstance(value, dict):
        raise ManualPackError(f"{label} must be an object: {path}")
    return value


def _parse_storyboard(path: Path) -> list[dict[str, str]]:
    _require_regular_file(path, "storyboard")
    lines = path.read_text(encoding="utf-8").splitlines()
    header_index = next(
        (index for index, line in enumerate(lines) if line.startswith("|") and "镜号" in line),
        None,
    )
    if header_index is None or header_index + 1 >= len(lines):
        raise ManualPackError("storyboard shot table not found")

    def cells(line: str) -> list[str]:
        return [cell.strip() for cell in line.strip().strip("|").split("|")]

    headers = cells(lines[header_index])
    required = {
        "镜号",
        "起点",
        "终点",
        "画面目的",
        "人物动作",
        "相机",
        "ai_source_layer",
        "禁物",
        "复用状态",
        "minimum_grok_source_seconds",
        "final_visual_seconds",
        "extension_strategy",
    }
    if not required <= set(headers):
        missing = sorted(required - set(headers))
        raise ManualPackError(f"storyboard missing columns: {missing}")

    separator = cells(lines[header_index + 1])
    if len(separator) != len(headers) or not all(re.fullmatch(r":?-{3,}:?", item) for item in separator):
        raise ManualPackError("invalid storyboard table separator")

    rows: list[dict[str, str]] = []
    for line in lines[header_index + 2 :]:
        if not line.startswith("|"):
            break
        values = cells(line)
        if len(values) != len(headers):
            raise ManualPackError("storyboard row width does not match headers")
        rows.append(dict(zip(headers, values, strict=True)))
    if [row["镜号"] for row in rows] != EXPECTED_SHOTS:
        raise ManualPackError("storyboard must contain exactly S01-S10 in order")
    return rows


def _validate_semantic_contracts(
    storyboard_rows: list[dict[str, str]],
    prompts: dict[str, str],
    *,
    content_id: str = "HC20260810-001",
) -> None:
    rows_by_shot = {row["镜号"]: row for row in storyboard_rows}
    if set(rows_by_shot) != set(EXPECTED_SHOTS) or set(prompts) != set(EXPECTED_SHOTS):
        raise ManualPackError("semantic contract requires exact S01-S10 storyboard and prompt sets")
    contracts = SHOT_SEMANTIC_CONTRACTS_BY_CONTENT.get(content_id)
    if contracts is None or set(contracts) != set(EXPECTED_SHOTS):
        raise ManualPackError("semantic contract mapping must cover exact S01-S10")

    for shot in EXPECTED_SHOTS:
        contract = contracts[shot]
        row = rows_by_shot[shot]
        for column, fragments in contract["storyboard"].items():
            value = row[column]
            for fragment in fragments:
                if fragment not in value:
                    raise ManualPackError(
                        f"semantic contract mismatch: {shot} storyboard {column} missing {fragment!r}"
                    )
        for fragment in contract["prompt_zh"]:
            if fragment not in prompts[shot]:
                raise ManualPackError(
                    f"semantic contract mismatch: {shot} prompt missing {fragment!r}"
                )


def _validate_batch(repo_root: Path, content_id: str) -> dict[str, Any]:
    batch_root = _assert_no_reparse_ancestors(
        repo_root / "09_泛健康日更" / "data" / "01_一般生活方式50集" / "batch-01"
    )
    _require_within(batch_root, repo_root, "batch root")
    active_path = batch_root / "active-batch.json"
    ref_path = batch_root / "current-batch-ref.json"
    active = _load_json(active_path, "active batch")
    reference = _load_json(ref_path, "current batch reference")
    if reference.get("active_sha256") != _sha256_file(active_path):
        raise ManualPackError("current batch reference does not bind active batch bytes")
    snapshot_value = reference.get("path")
    if not isinstance(snapshot_value, str) or Path(snapshot_value).is_absolute():
        raise ManualPackError("invalid batch snapshot path")
    snapshot_path = batch_root / Path(snapshot_value)
    snapshot_resolved = _assert_no_reparse_ancestors(snapshot_path)
    _require_within(snapshot_resolved, batch_root, "batch snapshot")
    snapshot_path = snapshot_resolved
    _require_regular_file(snapshot_path, "batch snapshot")
    if reference.get("sha256") != _sha256_file(snapshot_path):
        raise ManualPackError("current batch reference does not bind snapshot bytes")
    if reference.get("batch_id") != active.get("batch_id"):
        raise ManualPackError("batch identity mismatch")
    topics = active.get("topics")
    if not isinstance(topics, list):
        raise ManualPackError("active batch topics are missing")
    matches = [topic for topic in topics if isinstance(topic, dict) and topic.get("content_id") == content_id]
    if len(matches) != 1 or matches[0].get("state") != "production":
        raise ManualPackError(f"active topic is not production: {content_id}")
    return {
        "batch_id": active["batch_id"],
        "active_path": active_path,
        "active_sha256": _sha256_file(active_path),
        "snapshot_path": snapshot_path,
        "snapshot_sha256": _sha256_file(snapshot_path),
        "reference_path": ref_path,
        "reference_sha256": _sha256_file(ref_path),
    }


def _validate_inputs(content_id: str, repo_root: Path) -> dict[str, Any]:
    if content_id not in SUPPORTED_CONTENT_IDS:
        raise ManualPackError(f"unsupported batch content id: {content_id}")
    if content_id not in PROMPT_ACTIONS_BY_CONTENT:
        raise ManualPackError(f"manual prompt specification is not authored: {content_id}")
    repo_root = _assert_no_reparse_ancestors(repo_root)
    batch = _validate_batch(repo_root, content_id)
    episode_root = repo_root / "09_泛健康日更" / "work" / content_id
    production_root = episode_root / "production" / VERSION
    _require_within(_assert_no_reparse_ancestors(production_root), repo_root, "production root")
    episode_manifest_path = episode_root / "manifest.json"
    episode_manifest = _load_json(episode_manifest_path, "episode manifest")
    if episode_manifest.get("content_id") != content_id or episode_manifest.get("batch_id") != batch["batch_id"]:
        raise ManualPackError("episode manifest identity does not match active batch")

    storyboard_path = production_root / "02_script_storyboard" / "storyboard-v01.md"
    storyboard_rows = _parse_storyboard(storyboard_path)
    deterministic_shots = {
        row["镜号"] for row in storyboard_rows if row["复用状态"] == "deterministic-board"
    }
    prompts = {
        shot: _prompt_line(
            shot,
            content_id=content_id,
            deterministic_shots=deterministic_shots,
        )
        for shot in EXPECTED_SHOTS
    }
    _validate_semantic_contracts(storyboard_rows, prompts, content_id=content_id)
    first_frame_root = production_root / "03_first_frames"
    _assert_no_reparse_ancestors(first_frame_root)
    expected_names = [f"{content_id}-{VERSION}-{shot}-firstframe.png" for shot in EXPECTED_SHOTS]
    actual_names = sorted(path.name for path in first_frame_root.glob("*-firstframe.png") if path.is_file())
    if actual_names != expected_names:
        raise ManualPackError("formal first-frame root must contain exactly the expected S01-S10 inputs")

    images: dict[str, dict[str, Any]] = {}
    hashes: set[str] = set()
    for shot, name in zip(EXPECTED_SHOTS, expected_names, strict=True):
        path = first_frame_root / name
        _require_regular_file(path, f"formal first frame {shot}")
        if path.parent != first_frame_root:
            raise ManualPackError(f"first frame is not root-level: {path}")
        data = path.read_bytes()
        digest = _sha256_bytes(data)
        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.format != "PNG" or image.size != (1080, 1920):
                    raise ManualPackError(f"invalid first-frame format or dimensions: {path}")
                image.verify()
        except (OSError, SyntaxError) as exc:
            raise ManualPackError(f"invalid PNG first frame: {path}") from exc
        hashes.add(digest)
        images[shot] = {"path": path, "bytes": data, "sha256": digest}
    if len(hashes) != len(EXPECTED_SHOTS):
        raise ManualPackError("formal first frames must have ten unique SHA-256 values")

    episode_qa_path = production_root / "05_qa" / "first-frame-qa-v01.md"
    batch_qa_path = (
        repo_root
        / "09_泛健康日更"
        / "work"
        / "HC20260810-B01-task6-qa"
        / "HC20260810-B01-first-frame-qa-v01.md"
    )
    contact_sheet_path = production_root / "05_qa" / "storyboard-with-copy-contactsheet-v01.png"
    _require_regular_file(episode_qa_path, "episode Task 6 QA")
    _require_regular_file(batch_qa_path, "batch Task 6 QA")
    _require_regular_file(contact_sheet_path, "storyboard-with-copy contact sheet")
    episode_qa_text = episode_qa_path.read_text(encoding="utf-8")
    batch_qa_text = batch_qa_path.read_text(encoding="utf-8")
    if not all(image["sha256"] in episode_qa_text for image in images.values()):
        raise ManualPackError("episode Task 6 QA does not bind all current first-frame hashes")
    if "BATCH R3 EVIDENCE CURRENT" not in batch_qa_text or "not Task 8 factual approval" not in batch_qa_text:
        raise ManualPackError("batch Task 6 QA is not the required current non-approval evidence")

    for row in storyboard_rows:
        shot = row["镜号"]
        expected_deterministic = shot in deterministic_shots
        if (row["复用状态"] == "deterministic-board") != expected_deterministic:
            raise ManualPackError(f"unexpected generation mode in storyboard: {shot}")
        try:
            seconds = float(row["minimum_grok_source_seconds"])
        except ValueError as exc:
            raise ManualPackError(f"invalid minimum Grok source seconds: {shot}") from exc
        if expected_deterministic and seconds != 0.0:
            raise ManualPackError(f"deterministic shot must require zero Grok seconds: {shot}")
        if not expected_deterministic and not 0.0 < seconds <= 5.8:
            raise ManualPackError(f"dynamic minimum Grok source seconds exceeds 5.8: {shot}")

    return {
        "repo_root": repo_root,
        "content_id": content_id,
        "episode_root": episode_root,
        "production_root": production_root,
        "episode_manifest_path": episode_manifest_path,
        "storyboard_path": storyboard_path,
        "storyboard_rows": storyboard_rows,
        "prompts": prompts,
        "deterministic_shots": deterministic_shots,
        "images": images,
        "episode_qa_path": episode_qa_path,
        "batch_qa_path": batch_qa_path,
        "contact_sheet_path": contact_sheet_path,
        "batch": batch,
    }


def _prompt_line(
    shot: str,
    *,
    content_id: str = "HC20260810-001",
    deterministic_shots: set[str] | None = None,
) -> str:
    actions = PROMPT_ACTIONS_BY_CONTENT.get(content_id)
    if actions is None or shot not in actions:
        raise ManualPackError(f"manual prompt specification is not authored: {content_id}/{shot}")
    chinese_action, english_action = actions[shot]
    deterministic = shot in (DETERMINISTIC_SHOTS if deterministic_shots is None else deterministic_shots)
    mode = "deterministic_post" if deterministic else "grok_manual"
    operation_zh = (
        "无需上传 Grok，只在后期按本条制作确定性动效"
        if deterministic
        else "使用 Grok 浏览器扩展手动上传对应无字首帧，首帧是唯一构图参考"
    )
    operation_en = (
        "Do not upload to Grok; create only this deterministic motion in post-production"
        if deterministic
        else "Manually upload the matching text-free first frame with the Grok browser extension; the first frame is the sole composition reference"
    )
    omit_phone_face_terms = (content_id, shot) == ("HC20260810-010", "S02")
    safety_zh = (
        "不新增文字、数字、Logo、水印、纸张、纸笔、本册、人物或物体。"
        if omit_phone_face_terms
        else "不新增文字、数字、Logo、水印、UI、纸张、纸笔、本册、人物或物体。"
    )
    safety_en = (
        "add no text, numbers, Logo, watermark, paper, pen, notebook, person, or object."
        if omit_phone_face_terms
        else "add no text, numbers, Logo, watermark, UI, paper, pen, notebook, person, or object."
    )
    return (
        f"{shot}｜generation_mode={mode}｜中文指令：{operation_zh}。低幅动作：{chinese_action}。"
        "保持人物身份与场景、服装、道具数量、结构、路径、光线与竖屏构图；"
        f"{safety_zh}"
        f" English instruction: {operation_en}. Low-amplitude action: {english_action}. "
        "Preserve identity and scene, clothing, prop count, structure, direction, lighting, and vertical framing; "
        f"{safety_en}"
    )


def _csv_bytes(fieldnames: list[str], rows: list[dict[str, str]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _render_expected(inputs: dict[str, Any], output_dir: Path) -> dict[str, bytes]:
    repo_root: Path = inputs["repo_root"]
    content_id: str = inputs["content_id"]
    rows_by_shot = {row["镜号"]: row for row in inputs["storyboard_rows"]}
    prompts = inputs["prompts"]
    artifacts: dict[str, bytes] = {}
    manifest_rows: list[dict[str, str]] = []
    storyboard_sha = _sha256_file(inputs["storyboard_path"])
    episode_qa_sha = _sha256_file(inputs["episode_qa_path"])
    batch_qa_sha = _sha256_file(inputs["batch_qa_path"])
    raw_root = (
        f"09_泛健康日更/work/{content_id}/production/{VERSION}/"
        "05_grok_videos/01_raw/"
    )

    for shot in EXPECTED_SHOTS:
        image = inputs["images"][shot]
        image_name = image["path"].name
        copy_relative = Path("01_first_frames") / image_name
        prompt_name = f"{content_id}-{VERSION}-{shot}-prompt-zh-en.txt"
        prompt_relative = Path("02_prompts") / prompt_name
        prompt_bytes = (prompts[shot] + "\n").encode("utf-8")
        artifacts[copy_relative.as_posix()] = image["bytes"]
        artifacts[prompt_relative.as_posix()] = prompt_bytes
        storyboard_row = rows_by_shot[shot]
        deterministic = shot in inputs["deterministic_shots"]
        mode = "deterministic_post" if deterministic else "grok_manual"
        if deterministic:
            output_template = (
                f"09_泛健康日更/work/{content_id}/production/{VERSION}/06_edit/01_rough_cut/"
                f"{content_id}-{VERSION}-{shot}-deterministic-post.mp4"
            )
        elif (content_id, shot) in DUAL_SOURCE_SHOTS:
            output_template = "|".join(
                f"{raw_root}{content_id}-{VERSION}-{shot}{source}-takeNN.mp4"
                for source in ("A", "B")
            )
        else:
            output_template = (
                f"{raw_root}{content_id}-{VERSION}-{shot}-takeNN.mp4"
            )
        manifest_rows.append(
            {
                "batch_id": inputs["batch"]["batch_id"],
                "content_id": content_id,
                "version": VERSION,
                "shot": shot,
                "source_path": _as_posix(image["path"], repo_root),
                "copy_path": _as_posix(output_dir / copy_relative, repo_root),
                "bytes": str(len(image["bytes"])),
                "sha256": image["sha256"],
                "prompt_path": _as_posix(output_dir / prompt_relative, repo_root),
                "prompt_sha256": _sha256_bytes(prompt_bytes),
                "timeline_start": storyboard_row["起点"],
                "timeline_end": storyboard_row["终点"],
                "generation_mode": mode,
                "minimum_grok_source_seconds": storyboard_row["minimum_grok_source_seconds"],
                "output_template": output_template,
                "storyboard_sha256": storyboard_sha,
                "episode_qa_sha256": episode_qa_sha,
                "batch_qa_sha256": batch_qa_sha,
            }
        )

    combined_name = f"{content_id}-{VERSION}-Grok-Automation-10条提示词.txt"
    artifacts[combined_name] = ("\n\n".join(prompts[shot] for shot in EXPECTED_SHOTS) + "\n").encode("utf-8")
    fields = list(manifest_rows[0])
    artifacts["MANIFEST.csv"] = _csv_bytes(fields, manifest_rows)

    dynamic_list = "、".join(shot for shot in EXPECTED_SHOTS if shot not in inputs["deterministic_shots"])
    deterministic_list = "、".join(shot for shot in EXPECTED_SHOTS if shot in inputs["deterministic_shots"])
    required_output_count = sum(
        0
        if row["generation_mode"] == "deterministic_post"
        else 2
        if (content_id, row["shot"]) in DUAL_SOURCE_SHOTS
        else 1
        for row in manifest_rows
    )
    guide_rows: list[str] = []
    dual_guide_rows: list[str] = []
    for row in manifest_rows:
        shot = row["shot"]
        target_seconds = float(row["timeline_end"]) - float(row["timeline_start"])
        templates = row["output_template"].split("|")
        names = [Path(template).name for template in templates]
        row_output_count = (
            0
            if row["generation_mode"] == "deterministic_post"
            else len(templates)
        )
        guide_rows.append(
            f"| {shot} | `{row['generation_mode']}` | {target_seconds:.2f}s / "
            f"{float(row['minimum_grok_source_seconds']):.2f}s | {row_output_count} | "
            f"{'；'.join(f'`{name}`' for name in names)} |"
        )
        if (content_id, shot) in DUAL_SOURCE_SHOTS:
            dual_guide_rows.append(
                f"- {shot}：required_output_count=2；Source A 保存为 `{names[0]}`；"
                f"Source B 保存为 `{names[1]}`；两条独立源只在后期硬切；"
                "不得在单条 clip 内制作硬切或分屏。"
            )
    guide_table = "\n".join(guide_rows)
    dual_guide = "\n".join(dual_guide_rows) or "- 本期无双源镜头。"
    combined_path = (
        f"09_泛健康日更/work/{content_id}/production/{VERSION}/04_grok_batch/"
        f"manual_pack/{combined_name}"
    )
    first_frame_directory = (
        f"09_泛健康日更/work/{content_id}/production/{VERSION}/04_grok_batch/"
        "manual_pack/01_first_frames/"
    )
    grok_save_folder = f"{content_id}-S01-S10"
    guide = f"""# {content_id} {VERSION} Grok 手动生成指南

## 边界

- 本包是用户操作的浏览器扩展输入包，不包含已生成视频，也不代表外部审批或最终 QA。
- 动态镜头 {dynamic_list}：使用 **Grok 浏览器扩展**手动上传 `{first_frame_directory}` 中的对应图片，并粘贴 `02_prompts/` 中的同号提示词。
- {deterministic_list} 无需上传 Grok；它们标记为 `generation_mode=deterministic_post`，只按提示词在后期制作确定性动效。

## 本期操作参数

- 合并提示词：`{combined_path}`。
- 首帧图片目录：`{first_frame_directory}`。
- Grok 保存文件夹名称：`{grok_save_folder}`。
- 动态源保存目录：`{raw_root}`。
- 镜头总数：10。
- 必需动态源输出总数：{required_output_count}（已计入双源镜头的 A/B 增量）。
- 并发：1；任何时刻只运行一个生成任务。
- 每次生成后等待：至少 30 秒，再开始下一次生成。
- 每个必需动态源候选：至少 2 个；本期至少保存 {required_output_count * 2} 个候选文件。
- 动态输出使用带 `takeNN` 的候选文件名；`NN` 从 `01` 起按候选递增。
- `deterministic_post` 不上传 Grok，使用表内固定后期输出名，不使用 `takeNN`。

## 目标时长 / 最低源时长

| 镜号 | generation_mode | 目标时长 / 最低源时长 | required_output_count | 输出命名 |
|---|---|---:|---:|---|
{guide_table}

## 双源镜头

{dual_guide}

## 手动操作

1. 按 S01 到 S10 顺序处理；动态镜头的无字首帧是唯一构图参考。
2. 每个动态镜头只执行提示词中的一个低幅动作，不生成文字、Logo、水印、纸张、纸笔、本册或 UI。
3. 手动保存动态输出到上述 `05_grok_videos/01_raw/` 仓库完整路径，使用 `MANIFEST.csv` 的 `output_template` 文件名；双源镜头分别生成并分别保存 A/B。
4. 保持 1.0 倍速；禁止慢动作、循环、插帧或模型生成 UI。任何补时只按锁定分镜的 `extension_strategy` 使用末帧短停或确定性叠加。
5. 生成完成不等于通过质检；后续必须保留原文件并逐镜检查首、中、尾帧。
"""
    artifacts["MANUAL-GENERATION-GUIDE.md"] = guide.encode("utf-8")

    visual_notes = VISUAL_REVIEW_NOTES_BY_CONTENT[content_id]
    visual_review_rows = "\n".join(
        f"| {shot} | `{inputs['images'][shot]['sha256']}` | {visual_notes[shot]} |"
        for shot in EXPECTED_SHOTS
    )
    contact_sheet_path = inputs["contact_sheet_path"]
    dual_qa = (
        f"- 双源镜头：{'、'.join(shot for cid, shot in sorted(DUAL_SOURCE_SHOTS) if cid == content_id)}；"
        "每个提示词明确要求 Source A / Source B 分别生成，两个命名模板写入 MANIFEST，"
        "不得在单条 clip 内制作硬切或分屏，只允许后期硬切。"
        if any(cid == content_id for cid, _ in DUAL_SOURCE_SHOTS)
        else "- 双源镜头：无；每个动态镜头 required_output_count=1。"
    )
    qa = f"""# {content_id} {VERSION} Grok 手动包 QA

## 结果

- 活动主题状态：`production`；批次：`{inputs['batch']['batch_id']}`。
- 分镜：`{_as_posix(inputs['storyboard_path'], repo_root)}`，SHA-256 `{storyboard_sha}`，按表头名解析并确认恰好 S01–S10。
- 正式首帧：仅消费 `03_first_frames/` 根目录中 10 张无字 PNG；全部 1080×1920、哈希唯一，拷贝后字节与源文件相同。
- 排除：未消费 `storyboard_with_copy/`、带字联系表、UI 预览或候选图。
- 提示词：10 条中英双语单行，{deterministic_list} 为 `deterministic_post` 且无需上传 Grok；其余动态镜头为 `grok_manual`，最小 Grok 源时长均不超过 5.8 秒。
- 合并 TXT：恰好 10 条非空提示词，相邻恰好一个空行，UTF-8 + LF。
- 必需动态源输出：{required_output_count} 个；每个必需源至少保留 2 个候选，并发为 1，每次生成后至少等待 30 秒。
{dual_qa}

## 必需源质量证据

- 单期 Task 6：`{_as_posix(inputs['episode_qa_path'], repo_root)}`，SHA-256 `{episode_qa_sha}`。
- 批次 Task 6：`{_as_posix(inputs['batch_qa_path'], repo_root)}`，SHA-256 `{batch_qa_sha}`。
- 两份 QA 只是必需的当前源质量证据，**不是外部审批**、Task 8 事实批准、最终 QA 授权或发布许可。

## 视觉核对边界

- 审阅方式：`view_image`。
- 审阅日期：`2026-08-17`。
- 审阅者：`Codex Task 8 manual-pack review`。
- 带字联系表：`{_as_posix(contact_sheet_path, repo_root)}`，SHA-256 `{_sha256_file(contact_sheet_path)}`；只用于理解文案/动作上下文，不会被复制。

| 镜号 | 正式首帧 SHA-256 | `view_image` 逐镜结论 |
|---|---|---|
{visual_review_rows}

- 上述记录不是 Grok 动态或最终 QA 批准，也不是外部审批或发布许可。
"""
    artifacts["MANUAL-PACK-QA.md"] = qa.encode("utf-8")
    return artifacts


def _tree_bytes(root: Path) -> dict[str, bytes]:
    if not root.is_dir() or root.is_symlink():
        raise ManualPackError(f"manual pack is missing or unsafe: {root}")
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or getattr(path.stat(), "st_file_attributes", 0) & REPARSE_POINT_FLAG:
            raise ManualPackError(f"reparse path forbidden inside manual pack: {path}")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = path.read_bytes()
    return files


def _compare_tree(output_dir: Path, expected: dict[str, bytes]) -> None:
    actual = _tree_bytes(output_dir)
    if actual.keys() != expected.keys():
        raise ManualPackError("manual pack has different existing bytes or file set")
    differences = [name for name, data in expected.items() if actual[name] != data]
    if differences:
        raise ManualPackError(f"manual pack has different existing bytes: {differences[0]}")


def _write_staging(staging: Path, artifacts: dict[str, bytes]) -> None:
    for relative, data in artifacts.items():
        target = staging / Path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_output(inputs: dict[str, Any]) -> Path:
    return inputs["production_root"] / "04_grok_batch" / "manual_pack"


def build_manual_pack(
    content_id: str,
    *,
    repo_root: Path | str | None = None,
    output_dir: Path | str | None = None,
) -> Path:
    root_input = Path(repo_root) if repo_root is not None else _default_repo_root()
    root = _assert_no_reparse_ancestors(root_input)
    inputs = _validate_inputs(content_id, root)
    destination_input = Path(output_dir) if output_dir is not None else _default_output(inputs)
    destination = _assert_no_reparse_ancestors(destination_input)
    if output_dir is None:
        _require_within(destination, inputs["production_root"], "manual pack output")
    expected = _render_expected(inputs, destination)

    destination.parent.mkdir(parents=True, exist_ok=True)
    _assert_no_reparse_ancestors(destination.parent)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.staging-", dir=destination.parent))
    try:
        _write_staging(staging, expected)
        _compare_tree(staging, expected)
        if destination.exists():
            _compare_tree(destination, expected)
            return destination
        _assert_no_reparse_ancestors(destination.parent)
        try:
            os.replace(staging, destination)
        except OSError:
            if destination.exists():
                _compare_tree(destination, expected)
            else:
                raise
        return destination
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def verify_manual_pack(
    content_id: str,
    *,
    repo_root: Path | str | None = None,
    output_dir: Path | str | None = None,
) -> Path:
    root_input = Path(repo_root) if repo_root is not None else _default_repo_root()
    root = _assert_no_reparse_ancestors(root_input)
    inputs = _validate_inputs(content_id, root)
    destination_input = Path(output_dir) if output_dir is not None else _default_output(inputs)
    destination = _assert_no_reparse_ancestors(destination_input)
    if output_dir is None:
        _require_within(destination, inputs["production_root"], "manual pack output")
    expected = _render_expected(inputs, destination)
    _compare_tree(destination, expected)
    return destination


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or verify a deterministic Grok browser-extension manual pack.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("build", "verify"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--content-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        path = (
            build_manual_pack(args.content_id)
            if args.command == "build"
            else verify_manual_pack(args.content_id)
        )
    except ManualPackError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 3
    print(json.dumps({"status": "ok", "command": args.command, "path": str(path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
