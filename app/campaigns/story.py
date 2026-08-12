"""Inspectable, provider-neutral short-form story pipeline."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Callable

from app.campaigns.memory import fingerprint, normalize_text
from app.campaigns.models import (
    CampaignConfig,
    CaptionPackage,
    Hook,
    NarrationSegment,
    PlannedContentItem,
    Scene,
    SourceStatus,
    StageMetadata,
    StoryBeat,
    StoryBrief,
    StoryConcept,
    StoryPackage,
    StructuredScript,
    ValidationIssue,
)
from app.campaigns.planner import stable_id


def _metadata(
    stage: str,
    story_id: str,
    seed: int,
    provider: str,
    *,
    version: int = 1,
    parent: str | None = None,
    now: datetime | None = None,
) -> StageMetadata:
    created = now or datetime.now(UTC)
    return StageMetadata(
        stage_id=stable_id(stage, story_id, seed, version, provider),
        version=version,
        parent_stage_id=parent,
        provider=provider,
        random_seed=seed,
        created_at=created,
    )


class StoryConceptProvider(ABC):
    @abstractmethod
    def generate(self, brief: StoryBrief, count: int = 3) -> list[StoryConcept]: ...


class RuleBasedConceptGenerator(StoryConceptProvider):
    """Offline concept generator whose output depends only on the brief and seed."""

    FRAMES = (
        ("An invitation to notice", "recognition to reflection", "Notice what is already close at hand"),
        ("A memory worth asking about", "curiosity to connection", "A careful question can carry memory forward"),
        ("The meaning in an ordinary detail", "familiarity to renewed appreciation", "Ordinary details can hold shared meaning"),
        ("A small act of preservation", "concern to practical hope", "Preservation can begin with one manageable act"),
    )

    def generate(self, brief: StoryBrief, count: int = 3) -> list[StoryConcept]:
        concepts: list[StoryConcept] = []
        for index in range(max(1, count)):
            frame = self.FRAMES[(brief.random_seed + index) % len(self.FRAMES)]
            concept_id = stable_id("concept", brief.story_id, brief.random_seed, index)
            concepts.append(
                StoryConcept(
                    concept_id=concept_id,
                    working_title=f"{frame[0]}: {brief.topic}",
                    premise=(
                        f"Use {brief.topic} as a concrete doorway into {brief.core_message.lower()}, "
                        "without presenting unverified details as fact."
                    ),
                    hook_idea=f"Invite the viewer to reconsider {brief.topic}.",
                    emotional_arc=frame[1],
                    story_format=brief.story_format,
                    core_takeaway=frame[2],
                    cta_direction=brief.cta_objective,
                    estimated_duration_seconds=brief.target_duration_seconds,
                    novelty_notes=[f"deterministic frame {index + 1}", "topic-specific premise"],
                    content_memory_warnings=[],
                    metadata=_metadata(
                        "concept", brief.story_id, brief.random_seed + index, "rule_based_v1",
                        now=brief.metadata.created_at,
                    ),
                )
            )
        return concepts


class LegacyLlmConceptAdapter(StoryConceptProvider):
    """Adapter for the existing script generator; dependency is injected for safe tests."""

    def __init__(self, generate_script: Callable[..., str]):
        self.generate_script = generate_script

    @classmethod
    def from_existing_service(cls) -> "LegacyLlmConceptAdapter":
        from app.services import llm

        return cls(llm.generate_script)

    def generate(self, brief: StoryBrief, count: int = 1) -> list[StoryConcept]:
        script = self.generate_script(
            video_subject=brief.topic,
            language="",
            paragraph_number=1,
            video_script_prompt=(
                f"Use the {brief.story_format} format and this objective: {brief.audience_objective}. "
                "Do not invent citations or specific facts."
            ),
            custom_system_prompt="",
        )
        if not script:
            return []
        return [
            StoryConcept(
                concept_id=stable_id("legacy-concept", brief.story_id, fingerprint("script", script)),
                working_title=f"Legacy draft: {brief.topic}",
                premise=script,
                hook_idea=script.split(".", 1)[0].strip(),
                emotional_arc="provider supplied; requires review",
                story_format=brief.story_format,
                core_takeaway=brief.core_message,
                cta_direction=brief.cta_objective,
                estimated_duration_seconds=round(len(script.split()) / 2.5),
                novelty_notes=["adapted from the repository's existing LLM script generator"],
                content_memory_warnings=["unstructured provider output requires story validation"],
                metadata=_metadata("concept", brief.story_id, brief.random_seed, "legacy_llm_adapter"),
            )
        ]


class StoryEngine:
    def __init__(
        self,
        concept_provider: StoryConceptProvider | None = None,
        speaking_rate_wpm: int = 150,
    ):
        if speaking_rate_wpm < 60:
            raise ValueError("speaking_rate_wpm must be at least 60")
        self.concept_provider = concept_provider or RuleBasedConceptGenerator()
        self.speaking_rate_wpm = speaking_rate_wpm

    def create_brief(
        self,
        campaign: CampaignConfig,
        item: PlannedContentItem,
        *,
        now: datetime | None = None,
    ) -> StoryBrief:
        pillar = next(p for p in campaign.content_pillars if p.id == item.content_pillar)
        seed = next(seed for seed in campaign.seed_content if seed.id == item.seed_id)
        story_id = stable_id("story", item.planned_item_id)
        continuity = item.series.continuity_requirements if item.series else []
        return StoryBrief(
            story_id=story_id,
            planned_item_id=item.planned_item_id,
            campaign_id=campaign.campaign_id,
            content_pillar=item.content_pillar,
            theme=item.theme,
            topic=item.topic,
            target_audience=campaign.target_audience.description,
            audience_objective=item.audience_objective,
            core_message=f"{item.topic.capitalize()} can help people preserve and share meaning with care.",
            desired_emotional_response="warm recognition followed by a practical desire to reflect or respond",
            story_format=item.story_format,
            tone=campaign.brand_voice,
            target_duration_seconds=item.target_duration_seconds,
            target_word_count=round(item.target_duration_seconds * self.speaking_rate_wpm / 60),
            platform=item.platform,
            cta_objective=item.cta_style,
            visual_style=item.visual_style,
            required_facts=seed.required_facts,
            source_notes=seed.source_notes,
            prohibited_claims=campaign.content_exclusions,
            content_warnings=[],
            continuity_references=continuity,
            random_seed=item.random_seed,
            source_status=seed.source_status,
            metadata=_metadata("brief", story_id, item.random_seed, "campaign_item_v1", now=now),
        )

    @staticmethod
    def select_concept(
        brief: StoryBrief,
        concepts: list[StoryConcept],
        memory_similarity_scores: dict[str, float] | None = None,
    ) -> StoryConcept:
        if not concepts:
            raise ValueError("at least one concept candidate is required")
        similarities = memory_similarity_scores or {}
        scored: list[StoryConcept] = []
        for concept in concepts:
            duration_delta = abs(concept.estimated_duration_seconds - brief.target_duration_seconds)
            breakdown = {
                "campaign_fit": 20.0 if concept.story_format == brief.story_format else 0.0,
                "audience_relevance": 15.0 if brief.topic.casefold() in concept.premise.casefold() else 8.0,
                "novelty": 15.0 * (1.0 - min(1.0, similarities.get(concept.concept_id, 0.0))),
                "story_clarity": 12.0 if len(concept.premise.split()) >= 8 else 6.0,
                "emotional_potential": 10.0 if " to " in concept.emotional_arc else 5.0,
                "visual_potential": 10.0 if brief.topic else 0.0,
                "duration_fit": max(0.0, 10.0 - duration_delta),
                "cta_fit": 8.0 if concept.cta_direction == brief.cta_objective else 4.0,
                "safety": 0.0 if concept.content_memory_warnings else 5.0,
            }
            score = round(sum(breakdown.values()), 4)
            scored.append(
                concept.model_copy(
                    update={
                        "score_breakdown": breakdown,
                        "selection_score": score,
                        "selection_reasoning": [
                            f"campaign format fit contributed {breakdown['campaign_fit']}",
                            f"novelty contributed {breakdown['novelty']}",
                            f"duration fit contributed {breakdown['duration_fit']}",
                            "highest total score wins; concept ID breaks ties deterministically",
                        ],
                    }
                )
            )
        return max(scored, key=lambda concept: (concept.selection_score, concept.concept_id))

    def generate_hook(
        self,
        brief: StoryBrief,
        concept: StoryConcept,
        campaign: CampaignConfig,
        *,
        seed_offset: int = 0,
        version: int = 1,
        parent: str | None = None,
    ) -> Hook:
        template = next(fmt for fmt in campaign.story_formats if fmt.id == brief.story_format)
        patterns = template.hook_patterns or ["What does {topic} mean to you?"]
        rendered = [pattern.format(topic=brief.topic) for pattern in patterns]
        index = (brief.random_seed + seed_offset) % len(rendered)
        selected = rendered[index]
        alternatives = [value for value in rendered if value != selected][:3]
        if not alternatives:
            alternatives = [
                f"What does {brief.topic} bring to mind?",
                f"What context might be missing from {brief.topic}?",
            ]
            alternatives = [value for value in alternatives if value != selected][:3]
        return Hook(
            text=selected,
            hook_type=campaign.hook_styles[(brief.random_seed + seed_offset) % len(campaign.hook_styles)],
            intended_audience_response="pause, recognize the subject, and want to hear the next beat",
            estimated_spoken_duration_seconds=round(len(selected.split()) / (self.speaking_rate_wpm / 60), 2),
            novelty_fingerprint=fingerprint("hook", selected, stop_phrases=campaign.stop_phrases),
            risk_flags=[],
            alternatives=alternatives,
            selection_reasoning=[
                f"pattern is allowed for {template.name}",
                "selection is deterministic from the story seed",
                "wording avoids unsupported superlatives and generic clickbait",
            ],
            metadata=_metadata(
                "hook", brief.story_id, brief.random_seed + seed_offset, "rule_based_v1",
                version=version, parent=parent,
                now=brief.metadata.created_at if version == 1 else None,
            ),
        )

    def generate_beats(
        self,
        brief: StoryBrief,
        concept: StoryConcept,
        hook: Hook,
        campaign: CampaignConfig,
        *,
        version: int = 1,
        parent_ids: dict[int, str] | None = None,
    ) -> list[StoryBeat]:
        template = next(fmt for fmt in campaign.story_formats if fmt.id == brief.story_format)
        duration = brief.target_duration_seconds / len(template.beat_structure)
        words = max(5, round(duration * self.speaking_rate_wpm / 60))
        information = {
            "hook": hook.text,
            "context": f"Place {brief.topic} in a familiar, human context without asserting a specific history.",
            "setup": f"Introduce why {brief.topic} may carry meaning for a family or community.",
            "tension": "Acknowledge how details can be forgotten, separated from context, or shared without care.",
            "discovery": f"Show one gentle way to notice, ask about, or document {brief.topic}.",
            "contrast": "Contrast a detail left unexplained with one preserved alongside its context.",
            "example": f"Offer a hypothetical, clearly framed example connected to {brief.topic}.",
            "reflection": f"Invite the viewer to consider what {brief.topic} brings to mind.",
            "resolution": concept.core_takeaway,
            "cta": brief.cta_objective,
        }
        beats: list[StoryBeat] = []
        for index, beat_type in enumerate(template.beat_structure, start=1):
            purpose = information.get(beat_type, f"Advance the {beat_type} stage clearly.")
            beats.append(
                StoryBeat(
                    beat_number=index,
                    beat_type=beat_type,
                    purpose=f"Serve the {beat_type} function in the selected format.",
                    key_information=purpose,
                    emotional_function=(
                        "create attention" if beat_type == "hook" else
                        "create recognition" if beat_type in {"context", "setup", "example"} else
                        "provide closure and agency" if beat_type in {"resolution", "cta"} else
                        "move the emotional arc forward"
                    ),
                    approximate_duration_seconds=round(duration, 2),
                    approximate_word_count=words,
                    visual_objective=f"Show a concrete, respectful visual for the {beat_type} beat.",
                    transition_guidance="Use a simple visual cut that follows the narration change.",
                    required_facts=brief.required_facts if beat_type in {"context", "example"} else [],
                    supporting_details=[],
                    metadata=_metadata(
                        "beat", brief.story_id, brief.random_seed + index, "rule_based_v1",
                        version=version, parent=(parent_ids or {}).get(index),
                        now=brief.metadata.created_at if version == 1 else None,
                    ),
                )
            )
        return beats

    def generate_script(
        self,
        brief: StoryBrief,
        concept: StoryConcept,
        hook: Hook,
        beats: list[StoryBeat],
        *,
        version: int = 1,
        parent: str | None = None,
    ) -> StructuredScript:
        segment_text: dict[str, str] = {
            "hook": hook.text,
            "context": f"Think about {brief.topic}. It can seem ordinary until someone pauses to ask what it means.",
            "setup": "A remembered detail can connect a person, a place, and a moment without needing to become a grand claim.",
            "tension": "When context is lost, even a treasured object or routine can become harder for the next person to understand.",
            "discovery": "Begin with one careful question, write down what is known, and clearly mark what is uncertain.",
            "contrast": "A name alone may fade, while a name kept with a date, a voice, or a short note has somewhere to belong.",
            "example": f"For example, {brief.topic} might open a conversation; the meaning comes from the people who remember it.",
            "reflection": f"What does {brief.topic} bring to mind for you, and whose perspective would add context?",
            "resolution": f"{concept.core_takeaway}. Small acts of attention can keep meaning connected to its source.",
            "cta": brief.cta_objective,
        }
        segments: list[NarrationSegment] = []
        for beat in beats:
            text = segment_text.get(beat.beat_type, beat.key_information)
            seconds = len(text.split()) / (self.speaking_rate_wpm / 60)
            segments.append(
                NarrationSegment(
                    segment_number=beat.beat_number,
                    beat_number=beat.beat_number,
                    text=text,
                    estimated_duration_seconds=round(seconds, 2),
                )
            )
        narration = " ".join(segment.text for segment in segments)
        word_count = len(narration.split())
        duration = word_count / (self.speaking_rate_wpm / 60)
        return StructuredScript(
            title=concept.working_title,
            hook=hook.text,
            full_narration=narration,
            narration_segments=segments,
            word_count=word_count,
            estimated_spoken_duration_seconds=round(duration, 2),
            estimate_method=f"whitespace word count / {self.speaking_rate_wpm} configurable words per minute",
            tone=brief.tone,
            reading_level="plain-language general audience",
            pronunciation_notes=[],
            fact_references=brief.source_notes,
            cta=brief.cta_objective,
            closing_line=segments[-1].text,
            script_fingerprint=fingerprint("script", narration),
            generation_metadata=_metadata(
                "script", brief.story_id, brief.random_seed, "rule_based_v1",
                version=version, parent=parent,
                now=brief.metadata.created_at if version == 1 else None,
            ),
            validation_warnings=[],
        )

    def generate_scenes(
        self,
        brief: StoryBrief,
        script: StructuredScript,
        *,
        version: int = 1,
        parent_ids: dict[int, str] | None = None,
    ) -> list[Scene]:
        scenes: list[Scene] = []
        cursor = 0.0
        shots = ("close-up", "medium", "wide", "overhead", "detail")
        motions = ("slow push-in", "gentle pan", "static", "slow pull-back")
        for segment in script.narration_segments:
            end = cursor + segment.estimated_duration_seconds
            terms = [
                f"{brief.topic} respectful documentary detail",
                f"{brief.visual_style} community memory",
            ]
            scene = Scene(
                scene_number=segment.segment_number,
                narration_segment=segment.text,
                start_time_seconds=round(cursor, 2),
                end_time_seconds=round(end, 2),
                intended_duration_seconds=segment.estimated_duration_seconds,
                visual_objective=f"Illustrate narration segment {segment.segment_number} without implying literal evidence.",
                subject=brief.topic,
                setting="a non-identifying family or community environment",
                action="hands notice, handle, record, or discuss an everyday detail",
                shot_type=shots[(segment.segment_number - 1) % len(shots)],
                motion=motions[(segment.segment_number - 1) % len(motions)],
                transition="simple cut",
                stock_search_terms=terms,
                visual_prompt={
                    "subject": brief.topic,
                    "style": brief.visual_style,
                    "avoid": ["identifiable private people", "fabricated documents", "readable personal data"],
                },
                continuity_requirements=brief.continuity_references,
                safety_notes=["Do not present generic stock footage as a documented historical source."],
                scene_fingerprint=fingerprint(
                    "scene_plan", {"segment": segment.text, "terms": terms, "shot": shots[(segment.segment_number - 1) % len(shots)]}
                ),
                metadata=_metadata(
                    "scene", brief.story_id, brief.random_seed + segment.segment_number, "rule_based_v1",
                    version=version, parent=(parent_ids or {}).get(segment.segment_number),
                    now=brief.metadata.created_at if version == 1 else None,
                ),
            )
            scenes.append(scene)
            cursor = end
        return scenes

    def generate_caption(
        self,
        brief: StoryBrief,
        script: StructuredScript,
        campaign: CampaignConfig,
        *,
        version: int = 1,
        parent: str | None = None,
    ) -> CaptionPackage:
        question = f"What memory or detail does {brief.topic} bring to mind?"
        primary = f"{script.hook} {script.cta}"
        hashtags = list(campaign.metadata.get("hashtags", ["#CommunityStories", "#SharedMemory"]))
        caption_fp = fingerprint(
            "caption", f"{primary} {' '.join(hashtags)}", stop_phrases=campaign.stop_phrases
        )
        return CaptionPackage(
            primary_caption=primary,
            short_caption=script.hook,
            first_comment=question,
            pinned_comment_suggestion="Share only what is yours to share, and credit the people who provided context.",
            community_question=question,
            cta=script.cta,
            hashtag_suggestions=hashtags,
            accessibility_description=(
                f"A vertical short-form video uses varied, non-identifying documentary-style scenes about {brief.topic}."
            ),
            platform_variants={brief.platform: primary},
            caption_fingerprint=caption_fp,
            metadata=_metadata(
                "caption", brief.story_id, brief.random_seed, "rule_based_v1",
                version=version, parent=parent,
                now=brief.metadata.created_at if version == 1 else None,
            ),
        )

    def validate(
        self,
        package: StoryPackage,
        campaign: CampaignConfig,
        *,
        recent_hook_fingerprints: set[str] | None = None,
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []

        def add(code: str, severity: str, stage: str, message: str, action: str) -> None:
            issues.append(
                ValidationIssue(
                    code=code, severity=severity, stage=stage, message=message,
                    suggested_action=action,
                )
            )

        script = package.script
        brief = package.brief
        if not package.hook.text.strip():
            add("missing_hook", "error", "hook", "Hook text is empty.", "Generate or approve a hook.")
        if package.hook.novelty_fingerprint in (recent_hook_fingerprints or set()):
            add("duplicate_hook", "error", "hook", "Hook matches recent content.", "Regenerate the hook.")
        if brief.story_format not in campaign.allowed_formats:
            add("unsupported_story_format", "error", "brief", "Story format is not allowed.", "Choose an allowed format.")
        template = next((fmt for fmt in campaign.story_formats if fmt.id == brief.story_format), None)
        actual_pattern = [beat.beat_type for beat in package.beats]
        if not template or len(actual_pattern) < 3 or actual_pattern != template.beat_structure:
            add("weak_story_progression", "error", "beats", "Beat progression does not match the format template.", "Regenerate beats from the selected template.")
        duration = script.estimated_spoken_duration_seconds
        if duration < campaign.min_duration_seconds or duration > campaign.max_duration_seconds:
            add("duration_out_of_range", "error", "script", f"Estimated duration is {duration}s.", "Revise script to campaign duration limits.")
        expected = brief.target_word_count
        if script.word_count < expected * 0.65 or script.word_count > expected * 1.35:
            add("word_count_out_of_range", "warning", "script", f"Word count {script.word_count} differs from target {expected}.", "Review speaking rate and target duration.")
        if campaign.calls_to_action and not script.cta.strip():
            add("missing_cta", "error", "script", "Campaign requires a CTA.", "Add an allowed CTA.")
        normalized = normalize_text(script.full_narration)
        sentences = [normalize_text(value) for value in re.split(r"[.!?]+", script.full_narration) if value.strip()]
        if len(sentences) != len(set(sentences)):
            add("repeated_phrase", "warning", "script", "A complete sentence is repeated.", "Remove the repeated sentence.")
        if re.search(r"\{\{[^}]+}}|\{[a-zA-Z_][^}]*}|\[[A-Z_ ]+]", script.full_narration):
            add("unresolved_placeholder", "error", "script", "Unresolved template placeholder found.", "Resolve all placeholders.")
        generic_openings = ("in today s video", "you won t believe", "did you know")
        if any(normalized.startswith(value) for value in generic_openings):
            add("generic_opening", "warning", "hook", "Opening is generic or clickbait-like.", "Use a topic-specific opening.")
        if script.full_narration.casefold().count("disclaimer") > 1:
            add("excessive_disclaimers", "warning", "script", "Multiple disclaimers interrupt the story.", "Move essential context into concise source notes.")
        if script.full_narration.count("?") > 3:
            add("excessive_rhetorical_questions", "warning", "script", "More than three questions appear.", "Replace questions with narrative progression.")
        if "always" in normalized and "never" in normalized:
            add("contradictory_details", "warning", "script", "Absolute always/never claims may conflict.", "Review contradictory absolutes.")
        if brief.source_status in {SourceStatus.SOURCE_REQUIRED, SourceStatus.BLOCKED_PENDING_SOURCE}:
            add("unsupported_factual_claim", "error", "facts", "Required sources have not been verified.", "Block generation until source verification is recorded.")
        for exclusion in campaign.content_exclusions:
            if normalize_text(exclusion) and normalize_text(exclusion) in normalized:
                add("content_exclusion", "error", "script", f"Excluded content found: {exclusion}", "Remove the excluded content.")
        for constraint in campaign.tone_constraints:
            if constraint.casefold().startswith("avoid "):
                prohibited = normalize_text(constraint[6:])
                if prohibited and prohibited in normalized:
                    add("campaign_tone_violation", "error", "script", f"Tone constraint violated: {constraint}", "Revise language to match campaign tone.")
        if re.search(r"(?i)(in the style of|imitate|mimic)\s+[A-Z][\w.-]+", script.full_narration):
            add("living_artist_imitation", "warning", "script", "Artist-imitation language requires removal or review.", "Describe general visual traits without naming a living artist.")
        if re.search(r"(?i)\b(home address|phone number|medical record|private message)\b", script.full_narration):
            add("private_person_claim", "error", "script", "Potential private-person information appears.", "Remove private details and claims.")
        if re.search(r"(?i)\b(build a weapon|bypass safety|steal credentials)\b", script.full_narration):
            add("unsafe_instruction", "error", "script", "Unsafe instruction language appears.", "Remove unsafe instructions.")
        if len(package.scenes) != len(script.narration_segments) or any(
            scene.narration_segment != segment.text
            for scene, segment in zip(package.scenes, script.narration_segments)
        ):
            add("scene_narration_misalignment", "error", "scenes", "Scene-to-narration mapping is incomplete.", "Regenerate the scene plan from the script.")
        if len({scene.shot_type for scene in package.scenes}) < min(3, len(package.scenes)):
            add("insufficient_visual_variety", "warning", "scenes", "Scene plan repeats too few shot types.", "Vary shot type or visual objective.")
        return issues

    def build_package(
        self,
        campaign: CampaignConfig,
        item: PlannedContentItem,
        *,
        concept_count: int = 3,
        memory_similarity_scores: dict[str, float] | None = None,
        now: datetime | None = None,
    ) -> StoryPackage:
        created = now or datetime.now(UTC)
        brief = self.create_brief(campaign, item, now=created)
        candidates = self.concept_provider.generate(brief, concept_count)
        selected = self.select_concept(brief, candidates, memory_similarity_scores)
        candidates = [selected if value.concept_id == selected.concept_id else value for value in candidates]
        hook = self.generate_hook(brief, selected, campaign)
        beats = self.generate_beats(brief, selected, hook, campaign)
        script = self.generate_script(brief, selected, hook, beats)
        scenes = self.generate_scenes(brief, script)
        caption = self.generate_caption(brief, script, campaign)
        package = StoryPackage(
            story_version_id=stable_id("story-version", brief.story_id, brief.random_seed, 1),
            brief=brief,
            concept_candidates=candidates,
            selected_concept_id=selected.concept_id,
            hook=hook,
            beats=beats,
            script=script,
            scenes=scenes,
            caption=caption,
            validation_issues=[],
            created_at=created,
        )
        return package.model_copy(update={"validation_issues": self.validate(package, campaign)})

    def regenerate(
        self,
        package: StoryPackage,
        campaign: CampaignConfig,
        stage: str,
        *,
        beat_number: int | None = None,
    ) -> StoryPackage:
        selected = next(
            concept for concept in package.concept_candidates
            if concept.concept_id == package.selected_concept_id
        )
        version = max(
            package.hook.metadata.version,
            package.script.generation_metadata.version,
            package.caption.metadata.version,
        ) + 1
        updated = package
        if stage == "hook":
            hook = self.generate_hook(
                package.brief, selected, campaign, seed_offset=version,
                version=version, parent=package.hook.metadata.stage_id,
            )
            updated = package.model_copy(update={"hook": hook})
        elif stage == "beat":
            if beat_number is None or beat_number < 1 or beat_number > len(package.beats):
                raise ValueError("beat_number identifies the beat to regenerate")
            replacements = self.generate_beats(
                package.brief, selected, package.hook, campaign, version=version,
                parent_ids={beat.beat_number: beat.metadata.stage_id for beat in package.beats},
            )
            beats = list(package.beats)
            beats[beat_number - 1] = replacements[beat_number - 1]
            updated = package.model_copy(update={"beats": beats})
        elif stage == "script":
            script = self.generate_script(
                package.brief, selected, package.hook, package.beats,
                version=version, parent=package.script.generation_metadata.stage_id,
            )
            updated = package.model_copy(update={"script": script})
        elif stage == "scene_plan":
            scenes = self.generate_scenes(
                package.brief, package.script, version=version,
                parent_ids={scene.scene_number: scene.metadata.stage_id for scene in package.scenes},
            )
            updated = package.model_copy(update={"scenes": scenes})
        elif stage == "caption":
            caption = self.generate_caption(
                package.brief, package.script, campaign, version=version,
                parent=package.caption.metadata.stage_id,
            )
            updated = package.model_copy(update={"caption": caption})
        elif stage == "alternate_concept":
            generated = self.concept_provider.generate(
                package.brief, len(package.concept_candidates) + 1
            )
            existing_ids = {value.concept_id for value in package.concept_candidates}
            alternate = next(
                (value for value in generated if value.concept_id not in existing_ids),
                None,
            )
            if alternate is None:
                raise ValueError("concept provider did not produce a new alternate concept")
            alternate = self.select_concept(package.brief, [alternate])
            candidates = [*package.concept_candidates, alternate]
            hook = self.generate_hook(
                package.brief,
                alternate,
                campaign,
                seed_offset=version,
                version=version,
                parent=package.hook.metadata.stage_id,
            )
            beats = self.generate_beats(
                package.brief,
                alternate,
                hook,
                campaign,
                version=version,
                parent_ids={
                    beat.beat_number: beat.metadata.stage_id for beat in package.beats
                },
            )
            script = self.generate_script(
                package.brief,
                alternate,
                hook,
                beats,
                version=version,
                parent=package.script.generation_metadata.stage_id,
            )
            scenes = self.generate_scenes(
                package.brief,
                script,
                version=version,
                parent_ids={
                    scene.scene_number: scene.metadata.stage_id for scene in package.scenes
                },
            )
            caption = self.generate_caption(
                package.brief,
                script,
                campaign,
                version=version,
                parent=package.caption.metadata.stage_id,
            )
            updated = package.model_copy(
                update={
                    "concept_candidates": candidates,
                    "selected_concept_id": alternate.concept_id,
                    "hook": hook,
                    "beats": beats,
                    "script": script,
                    "scenes": scenes,
                    "caption": caption,
                }
            )
        elif stage == "validation":
            updated = package
        else:
            raise ValueError(f"unsupported regeneration stage: {stage}")
        version_id = stable_id("story-version", package.brief.story_id, version, stage, beat_number)
        updated = updated.model_copy(
            update={
                "story_version_id": version_id,
                "parent_story_version_id": package.story_version_id,
                "validation_issues": [],
                "created_at": datetime.now(UTC),
            }
        )
        return updated.model_copy(update={"validation_issues": self.validate(updated, campaign)})
