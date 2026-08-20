#!/usr/bin/env python3
"""
生成 100 天的内容计划。

计划刻意拆成"账号档案 + 排期条目"两层：所有视频共用的参数写在档案里，
排期只保留每条视频真正不同的部分（日期、主题、文案）。这样既避免了两百
多条重复配置，也让"改一次风格、全账号生效"成为可能。

重新生成：
    uv run python scripts/build_content_plan.py
"""

import json
import os
from datetime import date, timedelta

PLAN_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "content_plan.json"
)

START_DATE = date(2026, 8, 24)  # 周一开始，给新账号留出人工预热时间
TOTAL_DAYS = 100
POSTING_WEEKDAYS = {0, 1, 2, 3, 4}  # 周一至周五，每周 5 条


ACCOUNTS = {
    "why": {
        "instagram_username": "why.though101",
        # 片尾角标叠在正片最后两秒多，不额外增加时长。
        "outro": {
            "logo": "resource/branding/whyThough.jpg",
            "handle": "@why.though101",
            "duration": 2.2,
        },
        "theme": "Everyday science and curiosity",
        "defaults": {
            "video_aspect": "9:16",
            "video_source": "pexels",
            "paragraph_number": 1,
            "video_clip_duration": 3,
            "video_concat_mode": "random",
            "voice_name": "en-US-AvaMultilingualNeural-Female",
            "voice_rate": 1.0,
            "voice_volume": 1.0,
            "bgm_type": "song",
            "bgm_volume": 0.18,
            "subtitle_enabled": True,
            "max_subtitle_words": 3,
            "subtitle_highlight_enabled": True,
            "subtitle_highlight_color": "#FF2E88",
            "subtitle_uppercase": True,
            "font_name": "BeVietnamPro-Bold.ttf",
            "stroke_width": 8,
            "font_size": 80,
            "subtitle_position": "center",
            "video_language": "en-US",
        },
        # 开场句决定 90% 的完播率，因此把它写成硬性要求而不是建议。
        # 字数区间来自实测：一次真实生成得到 68 词 / 25.2 秒，即约 2.70 词/秒。
        # Instagram 更看重总观看时长，因此把成片时长瞄准 33-43 秒而不是更短。
        "video_script_prompt": (
            "Open with the exact question in the subject, asked in under 8 words. "
            "Then answer it plainly in everyday language, no jargon, no filler. "
            "End on the single most surprising detail. Never say 'in this video', "
            "never greet the viewer, never ask them to subscribe. "
            "Keep the whole script between 95 and 115 words."
        ),
        # 固定标签定义账号主题，平台据此分类；轮换标签负责触达不同的检索面。
        # 每条文案都带上这两行：观众看到的是单条视频，不是账号主页，
        # 所以"这个号是干什么的、多久更新"必须写在视频里。
        "tagline": [
            "The questions you stopped asking as a kid.",
            "One answer a day, in 40 seconds.",
        ],
        "hashtag_core": ["#science", "#didyouknow"],
        "hashtag_pool": [
            "#curiosity", "#explained", "#sciencefacts", "#learnsomethingnew",
            "#education", "#mindblown", "#howitworks", "#everydayscience",
            "#physics", "#whytho",
        ],
    },
    "waypoint": {
        "instagram_username": "waypoint.60",
        # 片尾角标叠在正片最后两秒多，不额外增加时长。
        "outro": {
            "logo": "resource/branding/Waypoint.jpg",
            "handle": "@waypoint.60",
            "duration": 2.2,
        },
        "theme": "Remote and remarkable places",
        "defaults": {
            "video_aspect": "9:16",
            "video_source": "pexels",
            # 旅行内容适合稍长：Instagram 更看重总观看时长而非完播率。
            "paragraph_number": 2,
            "video_clip_duration": 4,
            "video_concat_mode": "random",
            "voice_name": "en-GB-RyanNeural-Male",
            "voice_rate": 0.95,
            "voice_volume": 1.0,
            "bgm_type": "song",
            "bgm_volume": 0.2,
            "subtitle_enabled": True,
            "max_subtitle_words": 3,
            "subtitle_highlight_enabled": True,
            "subtitle_highlight_color": "#22D3EE",
            "subtitle_uppercase": True,
            "font_name": "BeVietnamPro-Bold.ttf",
            "stroke_width": 8,
            "font_size": 76,
            "subtitle_position": "bottom",
            "video_language": "en-GB",
        },
        "video_script_prompt": (
            "Open with a single striking factual statement about the place, "
            "under 10 words, no question. Then explain how it came to be that way "
            "and what it is like to be there. Documentary tone, calm and precise. "
            "Never greet the viewer, never mention the video itself. "
            "Keep the whole script between 110 and 140 words."
        ),
        # 每条文案都带上这两行：观众看到的是单条视频，不是账号主页，
        # 所以"这个号是干什么的、多久更新"必须写在视频里。
        "tagline": [
            "Places that shouldn't exist — and do.",
            "One place a day, in 40 seconds.",
        ],
        "hashtag_core": ["#geography", "#travel"],
        "hashtag_pool": [
            "#hiddenplaces", "#remoteplaces", "#earth", "#explore", "#travelfacts",
            "#offthebeatenpath", "#planetearth", "#islands", "#maps", "#wanderlust",
        ],
    },
    "creature": {
        "instagram_username": "creature.feature60",
        # 片尾角标叠在正片最后两秒多，不额外增加时长。
        "outro": {
            "logo": "resource/branding/CreatureFeature.jpg",
            "handle": "@creature.feature60",
            "duration": 2.2,
        },
        "theme": "Strange facts about wild animals",
        "defaults": {
            "video_aspect": "9:16",
            "video_source": "pexels",
            "paragraph_number": 1,
            "video_clip_duration": 3,
            "video_concat_mode": "random",
            "voice_name": "en-US-EmmaMultilingualNeural-Female",
            "voice_rate": 1.05,
            "voice_volume": 1.0,
            "bgm_type": "song",
            "bgm_volume": 0.18,
            "subtitle_enabled": True,
            "max_subtitle_words": 3,
            "subtitle_highlight_enabled": True,
            "subtitle_highlight_color": "#FACC15",
            "subtitle_uppercase": True,
            "font_name": "BeVietnamPro-Bold.ttf",
            "stroke_width": 8,
            "font_size": 84,
            "subtitle_position": "center",
            "video_language": "en-US",
        },
        "video_script_prompt": (
            "Open with the strangest fact stated flatly in under 8 words, no question. "
            "Then explain why it is true and what it lets the animal do. "
            "Bright, energetic tone but never childish. "
            "Never greet the viewer, never mention the video itself. "
            "Keep the whole script between 90 and 110 words."
        ),
        # 每条文案都带上这两行：观众看到的是单条视频，不是账号主页，
        # 所以"这个号是干什么的、多久更新"必须写在视频里。
        "tagline": [
            "Animals are stranger than you think.",
            "One wild fact a day, 40 seconds each.",
        ],
        "hashtag_core": ["#animals", "#wildlife"],
        "hashtag_pool": [
            "#animalfacts", "#nature", "#creatures", "#wildlifefacts",
            "#animalkingdom", "#naturefacts", "#strangebutrue", "#ocean",
            "#birds", "#zoology",
        ],
    },
}


SUBJECTS = {
    "why": [
        "Why is the sky blue?",
        "Why are sunsets red?",
        "Why does it smell like that before it rains?",
        "Why is the sea salty?",
        "Why is snow white when ice is clear?",
        "Why do we hiccup?",
        "Why is yawning contagious?",
        "Why do we get goosebumps?",
        "Why does coffee wake you up?",
        "Why do onions make you cry?",
        "Why does ice float on water?",
        "Why is space black if there are so many stars?",
        "Why do stars twinkle but planets don't?",
        "Why do we always see the same side of the Moon?",
        "Why is Mars red?",
        "Why is there no sound in space?",
        "Why do mirrors flip left and right but not up and down?",
        "Why is glass transparent?",
        "Why does helium change your voice?",
        "Why does metal feel colder than wood at the same temperature?",
        "Why do plants look green?",
        "Why do leaves change colour in autumn?",
        "Why do trees have rings?",
        "Why do bananas ripen faster in a bag?",
        "Why does bread go stale?",
        "Why does spicy food burn?",
        "Why does mint feel cold in your mouth?",
        "Why does chocolate kill dogs?",
        "Why do we dream?",
        "Why do we forget most of our dreams?",
        "Why does time feel faster as you get older?",
        "Why does your recorded voice sound wrong?",
        "Why do fingers wrinkle in the bath?",
        "Why do we blush?",
        "Why do some people sneeze at bright light?",
        "Why does brain freeze happen?",
        "Why does music give you chills?",
        "Why do we blink so often?",
        "Why do we cry when we are sad?",
        "Why does thunder follow lightning?",
        "Why do clouds float if water is heavy?",
        "Why is fog low and clouds high?",
        "Why does a rainbow curve?",
        "Why is the ocean blue from above but clear in your hand?",
        "Why does wind exist?",
        "Why do hurricanes spin?",
        "Why is the deep ocean pitch black?",
        "Why do bubbles pop?",
        "Why does a spinning top stay upright?",
        "Why do magnets stick to some metals only?",
        "Why do phone batteries get worse over time?",
        "Why are aeroplane windows round?",
        "Why do screens look strange on camera?",
        "Why is the keyboard laid out QWERTY?",
        "Why do some countries drive on the left?",
        "Why are stop signs red?",
        "Why do we have leap years?",
        "Why does paper give such painful cuts?",
        "Why do zips work?",
        "Why is the Moon visible during the day?",
        "Why doesn't the Moon fall to Earth?",
        "Why is honey the only food that never spoils?",
        "Why does hot water sometimes freeze faster than cold?",
        "Why do we get motion sickness?",
        "Why does the ocean have tides?",
        "Why is fire hot and what is a flame made of?",
        "Why does static electricity shock you?",
        "Why do birds sit on power lines without dying?",
        "Why does soap actually clean things?",
        "Why do we yawn when we are tired?",
        "Why is the human eye fooled by optical illusions?",
        "Why do cut apples turn brown?",
        "Why does sound travel further at night?",
        "Why is the desert freezing at night?",
        "Why do we have fingerprints?",
        "Why does salt melt ice?",
    ],
    "waypoint": [
        "The city that is sinking two millimetres a year",
        "The town where the sun does not set for months",
        "The most isolated inhabited island on Earth",
        "The most dangerous road in the world",
        "The town where it is illegal to be buried",
        "The deepest lake on the planet",
        "The driest place on Earth",
        "The largest salt flat in the world",
        "The country with no rivers",
        "The wettest place on Earth",
        "The town split in half by a border",
        "The road that vanishes twice a day",
        "The island that changes country every six months",
        "The city that is being moved three kilometres",
        "The sea that has no coastline",
        "The lake that turns bright pink",
        "The crater that has been burning for fifty years",
        "The town where most people live underground",
        "The shortest scheduled flight in the world",
        "The cave large enough to hold a skyscraper",
        "The desert that floods into thousands of lagoons",
        "The oldest continuously inhabited city",
        "The island where cats outnumber people",
        "The highest capital city in the world",
        "The town with canals instead of roads",
        "The mountains striped in seven colours",
        "The largest desert on Earth is frozen",
        "The saltiest water you can float on",
        "The dunes that sing",
        "The longest train journey in the world",
        "The library that sits in two countries",
        "The town that is one single building",
        "The cave of giant crystals",
        "The river that boils",
        "The forest where every tree bends",
        "The city abandoned overnight",
        "The steepest street in the world",
        "The beach that glows at night",
        "The waterfall that freezes solid",
        "The village built inside a cave",
        "The northernmost town on Earth",
        "The island made entirely of shells",
        "The hotel made of ice, rebuilt every year",
        "The place where two oceans appear not to mix",
        "The lake that turns animals to stone",
        "The tree that stood alone for centuries",
        "The country you can cross in fifteen minutes",
        "The underwater museum you can dive through",
        "The volcano you can walk inside",
        "The deepest hole humans ever dug",
        "The fjord so narrow ships barely pass",
        "The field of geysers that never sleeps",
        "The town cut off by tides twice a day",
        "The stone forest that shreds boots",
        "The lake that explodes",
        "The city with no cars at all",
        "The glacier you can walk under",
        "The island where horses arrived by shipwreck",
        "The desert that was once an ocean",
        "The waterfall that flows upward in high wind",
        "The mountain that is taller than Everest from its base",
        "The place with the largest tide on Earth",
        "The town buried by a volcano and dug back out",
        "The staircase carved into a cliff",
        "The lake suspended above a valley",
        "The village that moves with the seasons",
        "The island nation running out of land",
        "The bridge that disappears in fog every morning",
        "The last place on Earth without internet",
        "The forest older than the last ice age",
        "The salt mine with a cathedral inside",
        "The archipelago with more islands than people",
        "The plateau above the clouds",
        "The canyon deeper than the Grand Canyon",
        "The city built on a lake that no longer exists",
    ],
    "creature": [
        "An octopus has three hearts",
        "Why cats purr",
        "This bird flies 11,000 km without landing",
        "Flamingos are not born pink",
        "Dolphins sleep with half their brain awake",
        "This jellyfish can reverse its own ageing",
        "Tardigrades survived open space",
        "The mantis shrimp punches at bullet speed",
        "Axolotls regrow entire limbs",
        "Elephants physically cannot jump",
        "Sharks are older than trees",
        "Cows have best friends",
        "Sea otters hold hands while sleeping",
        "Crows remember human faces for years",
        "An octopus tastes with its arms",
        "Starfish have no brain at all",
        "A jellyfish is 95 percent water",
        "Snails have thousands of teeth",
        "The platypus sweats milk",
        "Wombats produce cube-shaped droppings",
        "Koalas have fingerprints like ours",
        "Penguins propose with a pebble",
        "Male seahorses give birth",
        "A hummingbird's heart beats 1,200 times a minute",
        "A blue whale's heart is the size of a car",
        "Giraffes need enormous blood pressure",
        "Camel humps store fat, not water",
        "Chameleons do not change colour to hide",
        "Geckos climb glass using molecular forces",
        "Spider silk is stronger than steel by weight",
        "Ants farm other insects for food",
        "Bees give directions by dancing",
        "Butterflies taste with their feet",
        "Cicadas stay underground for 17 years",
        "A dragonfly catches 95 percent of its targets",
        "A cockroach can live a week without its head",
        "Only female mosquitoes bite",
        "Fireflies make light with almost no heat",
        "The anglerfish male fuses to the female",
        "The pistol shrimp shoots a bubble hotter than the sun",
        "Electric eels can stun a horse",
        "The archerfish shoots down insects with water",
        "Some fish walk on land",
        "The lungfish can survive years without water",
        "Some frogs freeze solid and thaw alive",
        "Poison dart frogs lose their poison in captivity",
        "Crocodile tears are real",
        "Some turtles breathe through their rear",
        "Snakes see body heat as an image",
        "The chameleon's tongue accelerates faster than a rocket",
        "Sloths move so slowly that algae grows on them",
        "The pangolin is the most trafficked mammal on Earth",
        "Naked mole rats barely feel pain and rarely get cancer",
        "Bats are not blind at all",
        "The honey badger shrugs off cobra venom",
        "Hyena clans are ruled by females",
        "Meerkats take turns on guard duty",
        "Prairie dogs have words for specific predators",
        "Beaver dams can be seen from orbit",
        "Forgetful squirrels plant thousands of trees",
        "Ravens use tools and hold grudges",
        "Parrots understand what words mean",
        "Pigeons navigate using Earth's magnetic field",
        "Owls fly in complete silence",
        "The peregrine falcon dives at 380 km/h",
        "Hummingbirds can fly backwards",
        "Emperor penguins dive deeper than submarines go",
        "A woodpecker's tongue wraps around its skull",
        "Narwhal tusks are actually teeth",
        "Orcas have regional dialects",
        "Sperm whales sleep standing up",
        "Sea turtles return to the beach they were born on",
        "Horseshoe crab blood is bright blue and saves lives",
        "The immortal hydra does not appear to age",
        "Cuttlefish hypnotise their prey with skin patterns",
    ],
}


# 内置曲库经过实测：29 首的响度只相差 4.7 dB，频谱质心只相差 151 Hz，
# 也就是说它们本质上是同一种氛围音乐。按"情绪"精细分类会是编造出来的
# 区分，因此这里只做两件真实有效的事：
# 1. 按实测能量（响度 65% + 亮度 35%）排序后分成三组，让偏亮偏响的给节奏
#    更快的账号，偏暗偏轻的给纪录片语气的账号；
# 2. 三个账号的曲目池完全不重叠，使每个账号拥有稳定且互不相同的听感。
BGM_POOLS = {
    "creature": [
        "output000.mp3", "output019.mp3", "output015.mp3", "output008.mp3",
        "output004.mp3", "output023.mp3", "output012.mp3", "output011.mp3",
        "output027.mp3", "output001.mp3",
    ],
    "why": [
        "output020.mp3", "output016.mp3", "output013.mp3", "output005.mp3",
        "output009.mp3", "output022.mp3", "output028.mp3", "output018.mp3",
        "output007.mp3", "output002.mp3",
    ],
    "waypoint": [
        "output024.mp3", "output003.mp3", "output014.mp3", "output017.mp3",
        "output006.mp3", "output021.mp3", "output025.mp3", "output010.mp3",
        "output029.mp3",
    ],
}


# 每条 5 个标签：数量早已不是杠杆，2020 年那种 30 个标签的堆砌现在只会被当成
# 垃圾信息。真正起作用的是相关性，以及不要让每条视频都用完全相同的标签块。
ROTATING_HASHTAGS = 3


def build_hashtags(profile: dict, index: int) -> str:
    """
    组装一条视频的标签串。

    固定两个定义账号主题的标签，其余在池内按序轮换，避免同一账号的每条
    视频都挂着一模一样的标签块。
    """
    pool = profile["hashtag_pool"]
    start = (index * ROTATING_HASHTAGS) % len(pool)
    rotating = [pool[(start + offset) % len(pool)] for offset in range(ROTATING_HASHTAGS)]
    tags = " ".join(profile["hashtag_core"] + rotating)
    return tags


def build_caption(profile: dict, subject: str, index: int) -> str:
    """标题、账号定位两行、标签，中间各空一行。"""
    tagline = "\n".join(profile.get("tagline", []))
    blocks = [subject, tagline, build_hashtags(profile, index)]
    return "\n\n".join(block for block in blocks if block)


def build_schedule() -> list[dict]:
    """按工作日排期，并让三个账号错开主题顺序，避免同一天风格雷同。"""
    cursors = {account: 0 for account in ACCOUNTS}
    counters = {account: 0 for account in ACCOUNTS}
    schedule = []

    for offset in range(TOTAL_DAYS):
        current = START_DATE + timedelta(days=offset)
        if current.weekday() not in POSTING_WEEKDAYS:
            continue

        for account, profile in ACCOUNTS.items():
            pool = SUBJECTS[account]
            index = cursors[account]
            if index >= len(pool):
                # 主题池用尽后停止排期，而不是重复投放同一主题：
                # 重复内容正是平台判定"模板化生产"的依据。
                continue

            cursors[account] = index + 1
            counters[account] += 1
            subject = pool[index]
            caption = build_caption(profile, subject, index)
            # 在池内轮换而不是随机：同一账号相邻两条不会撞曲，且计划可复现。
            bgm_pool = BGM_POOLS[account]
            bgm_file = bgm_pool[index % len(bgm_pool)]
            schedule.append(
                {
                    "id": f"{account}-{counters[account]:03d}",
                    "date": current.isoformat(),
                    "account": account,
                    "subject": subject,
                    "bgm_file": bgm_file,
                    "caption": caption,
                }
            )

    return schedule


def main() -> int:
    schedule = build_schedule()
    plan = {
        "version": 1,
        "generated_for": {
            "start_date": START_DATE.isoformat(),
            "total_days": TOTAL_DAYS,
            "posting_weekdays": sorted(POSTING_WEEKDAYS),
        },
        "accounts": ACCOUNTS,
        "schedule": schedule,
    }

    with open(PLAN_PATH, "w", encoding="utf-8") as handle:
        json.dump(plan, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    per_account = {}
    for entry in schedule:
        per_account[entry["account"]] = per_account.get(entry["account"], 0) + 1

    print(f"wrote {PLAN_PATH}")
    print(f"total videos: {len(schedule)}")
    for account, count in per_account.items():
        print(f"  {account:10} {count} videos")
    print(f"last scheduled day: {schedule[-1]['date']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
