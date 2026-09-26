"""Prompt templates for per-channel photo scenes and for copy (one per language, written natively).

The scene is planned first; each language's copy is then written for that photo, so words and picture tell one
story. Neither language ever sees the other's copy (rule 6).

Channel tone, length, CTA and hashtag style come from channels.json; nothing channel-specific is hardcoded here.
The art-direction rules in scene_prompt are adapted from docs/generation_prompts.md.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.caption_length import LengthCounting
from app.channels import ChannelSpec
from app.headline_overlay import TextZone, allowed_text_zones
from app.models import Language

HEADLINE_MAX_WORDS = 8

# Appended in code to every image prompt, whatever the scene writer returned. Headlines are overlaid later.
NO_TEXT_CLAUSE = (
    "No text, no letters, no words, no numbers, no typography, no logos, no brand names on clothes or packaging, "
    "no signage, no watermark."
)
QUIET_SPACE = "quiet, empty space (open sky, a plain wall or soft-focus background) with no people in it"
HEADLINE_ZONE_CLAUSES = {
    TextZone.TOP: f"The top third of the frame is {QUIET_SPACE}.",
    TextZone.BOTTOM: f"The bottom third of the frame is {QUIET_SPACE}.",
    TextZone.LEFT: f"The left third of the frame is {QUIET_SPACE}; the subject is in the right two thirds.",
    TextZone.RIGHT: f"The right third of the frame is {QUIET_SPACE}; the subject is in the left two thirds.",
}


class ChannelCopy(BaseModel):
    channel: str
    headline: str
    caption: str
    hashtags: list[str]


class CopySet(BaseModel):
    posts: list[ChannelCopy]


class ChannelScene(BaseModel):
    channel: str
    text_zone: str = Field(description="Where the headline goes: one of the channel's headline zones.")
    scene: str = Field(description="The image prompt, starting with the composition.")


class SceneSet(BaseModel):
    scenes: list[ChannelScene]


@dataclass(frozen=True)
class BriefContext:
    title: str
    goal: str
    audience: str
    tone: str
    insights: tuple[str, ...] = ()


def final_image_prompt(scene: str, text_zone: TextZone) -> str:
    return f"{scene.strip()} {HEADLINE_ZONE_CLAUSES[text_zone]} {NO_TEXT_CLAUSE}"


def _orientation(width: int, height: int) -> str:
    if width > height:
        return "landscape"
    if width < height:
        return "portrait"
    return "square"


# ---------------------------------------------------------------- copy prompts

ENGLISH_COPY_OPENING = (
    "You are a senior social media copywriter for brands in West Bengal, India. "
    "Write original English copy for each channel below, directly in English."
)
BENGALI_COPY_OPENING = (
    "তুমি পশ্চিমবঙ্গের ব্র্যান্ডের জন্য কাজ করা একজন অভিজ্ঞ সোশ্যাল মিডিয়া কপিরাইটার। "
    "নিচের প্রতিটি চ্যানেলের জন্য সরাসরি বাংলায় মৌলিক লেখা লেখো — কোনো ইংরেজি লেখা থেকে অনুবাদ নয়। "
    "কলকাতার মানুষ যেভাবে স্বাভাবিকভাবে কথা বলে ও লেখে, সেভাবে লেখো।"
)
# A model once wrote the brief's গড়িয়াহাট as গড়েরহাট, rebuilding it from "Gariahat" in the English photo
# description. Names keep the brief's spelling, in headlines, captions and hashtags alike.
ENGLISH_NAME_SPELLING_RULE = (
    "Spell every name of a place, shop, brand, product or person exactly as the brief does, in the headline, "
    "caption and hashtags. A name the brief gives only in Bengali takes its usual English spelling."
)
BENGALI_NAME_SPELLING_RULE = (
    "জায়গা, দোকান, ব্র্যান্ড, পণ্য বা মানুষের নাম ব্রিফে যে বানানে লেখা আছে, headline, caption আর hashtags-এ "
    "হুবহু সেই বানানেই লেখো। ছবির ইংরেজি বর্ণনায় থাকা কোনো নামের বাংলা বানান নিজে বানাবে না। ব্রিফে নাম শুধু "
    "ইংরেজিতে থাকলে কলকাতায় প্রচলিত বাংলা বানানটা লেখো।"
)


def _english_channel_line(channel: str, spec: ChannelSpec) -> str:
    emoji_note = " (emoji count as 2)" if spec.caption.length_counting == LengthCounting.X_WEIGHTED else ""
    return (
        f"- {channel}: {spec.style.copy_style} Hard limits: caption plus hashtags at most "
        f"{spec.caption.max_chars} characters{emoji_note}; at most {spec.caption.max_hashtags} hashtags."
    )


def _bengali_channel_line(channel: str, spec: ChannelSpec) -> str:
    emoji_note = " (ইমোজি ২ অক্ষর ধরা হয়)" if spec.caption.length_counting == LengthCounting.X_WEIGHTED else ""
    return (
        f"- {channel}: {spec.style.copy_style} কঠোর সীমা: ক্যাপশন ও হ্যাশট্যাগ মিলিয়ে সর্বোচ্চ "
        f"{spec.caption.max_chars} অক্ষর{emoji_note}; সর্বোচ্চ {spec.caption.max_hashtags}টি হ্যাশট্যাগ।"
    )


def _english_copy_prompt(
    brief: BriefContext, specs: Mapping[str, ChannelSpec], scenes: Mapping[str, str], feedback: Sequence[str]
) -> str:
    sections = [
        ENGLISH_COPY_OPENING,
        "Brief\n"
        f"- Title: {brief.title}\n- Goal: {brief.goal}\n- Audience: {brief.audience}\n- Tone: {brief.tone}",
    ]
    if brief.insights:
        sections.append("What worked before (apply these lessons):\n" + "\n".join(f"- {i}" for i in brief.insights))
    sections.append(
        "Channels. Each post must feel native to its channel (tone, length, call to action, hashtag style):\n"
        + "\n".join(_english_channel_line(channel, spec) for channel, spec in specs.items())
    )
    if scenes:
        sections.append(
            "Photos. Each post is published with the photo described below, and its headline is set on that photo. "
            "Write each channel's headline and caption for its photo, so the words and the picture tell one story. "
            "The descriptions only show you the picture: do not state their details (fabrics, colours, places) "
            "as facts about the product.\n" + _scene_lines(scenes)
        )
    sections.append(
        "Rules\n"
        "- Write every headline and caption in English, even if the brief above is written in Bengali.\n"
        "- Use only facts stated in the brief. Do not invent addresses, prices, discounts, dates, phone numbers, "
        "URLs or product details.\n"
        f"- {ENGLISH_NAME_SPELLING_RULE}\n"
        f"- headline: at most {HEADLINE_MAX_WORDS} words, no hashtags, no emoji. It is set large on the photo, "
        "so make it one strong line that fits what the photo shows.\n"
        "- hashtags: the words only, without the '#' sign. Put them only here, never in the caption.\n"
        f"- Return exactly one post per channel, with these channel ids: {', '.join(specs)}."
    )
    if feedback:
        sections.append(
            "Your previous answer broke these limits. Rewrite so every post fits:\n"
            + "\n".join(f"- {problem}" for problem in feedback)
        )
    return "\n\n".join(sections)


def _bengali_copy_prompt(
    brief: BriefContext, specs: Mapping[str, ChannelSpec], scenes: Mapping[str, str], feedback: Sequence[str]
) -> str:
    sections = [
        BENGALI_COPY_OPENING,
        "ব্রিফ\n"
        f"- শিরোনাম: {brief.title}\n- লক্ষ্য: {brief.goal}\n- দর্শক: {brief.audience}\n- টোন: {brief.tone}",
    ]
    if brief.insights:
        sections.append("আগের পোস্ট থেকে শেখা (এগুলো মাথায় রাখো):\n" + "\n".join(f"- {i}" for i in brief.insights))
    sections.append(
        "চ্যানেল। প্রতিটি পোস্ট যেন সেই চ্যানেলের নিজস্ব ধাঁচের হয় (টোন, দৈর্ঘ্য, কল টু অ্যাকশন, হ্যাশট্যাগের ধরন)। "
        "চ্যানেলের ধরন ইংরেজিতে বর্ণনা করা আছে, কিন্তু তোমার লেখা হবে পুরোপুরি বাংলায়:\n"
        + "\n".join(_bengali_channel_line(channel, spec) for channel, spec in specs.items())
    )
    if scenes:
        sections.append(
            "ছবি। প্রতিটি পোস্ট নিচে বর্ণনা করা ছবির সঙ্গে প্রকাশ হবে, আর headline বসবে সেই ছবির উপর। "
            "প্রতিটি চ্যানেলের headline ও caption তার ছবির সঙ্গে মিলিয়ে লেখো, যাতে লেখা আর ছবি একই গল্প বলে। "
            "বর্ণনা ইংরেজিতে, শুধু ছবিটা বোঝানোর জন্য: অনুবাদ করবে না, আর এর খুঁটিনাটি (কাপড়, রং, জায়গা) "
            "পণ্যের তথ্য হিসেবে লিখবে না।\n" + _scene_lines(scenes)
        )
    sections.append(
        "নিয়ম\n"
        "- ব্রিফ ইংরেজিতে লেখা থাকলেও প্রতিটি headline ও caption বাংলায় লিখবে।\n"
        "- শুধু ব্রিফে দেওয়া তথ্য ব্যবহার করো। ঠিকানা, দাম, ছাড়, তারিখ, ফোন নম্বর, ওয়েবসাইট বা পণ্যের বিবরণ "
        "বানিয়ে লিখবে না।\n"
        f"- {BENGALI_NAME_SPELLING_RULE}\n"
        f"- headline: সর্বোচ্চ {HEADLINE_MAX_WORDS} শব্দ, হ্যাশট্যাগ বা ইমোজি ছাড়া। এটি ছবির উপর বড় করে বসবে, "
        "তাই ছবির সঙ্গে মানানসই একটি জোরালো লাইন লেখো।\n"
        "- hashtags: '#' চিহ্ন ছাড়া শুধু শব্দ; পশ্চিমবঙ্গে যা স্বাভাবিকভাবে ব্যবহৃত হয় (বাংলা বা ইংরেজি)। "
        "হ্যাশট্যাগ শুধু এখানেই দেবে, caption-এ কখনো নয়।\n"
        f"- প্রতিটি চ্যানেলের জন্য ঠিক একটি পোস্ট দাও, চ্যানেল আইডি হুবহু: {', '.join(specs)}।"
    )
    if feedback:
        sections.append(
            "তোমার আগের উত্তর এই সীমাগুলো ভেঙেছে। প্রতিটি পোস্ট যেন সীমার মধ্যে থাকে, এমনভাবে আবার লেখো:\n"
            + "\n".join(f"- {problem}" for problem in feedback)
        )
    return "\n\n".join(sections)


def _scene_lines(scenes: Mapping[str, str]) -> str:
    return "\n".join(f"- {channel}: {scene}" for channel, scene in scenes.items())


def copy_prompt(
    brief: BriefContext,
    language: Language,
    specs: Mapping[str, ChannelSpec],
    scenes: Mapping[str, str],
    feedback: Sequence[str] = (),
) -> str:
    """Each language gets its own prompt from the brief and the channel photos; no other language's copy ever
    goes in."""
    scenes = {channel: scene for channel, scene in scenes.items() if channel in specs}
    if language == Language.BENGALI:
        return _bengali_copy_prompt(brief, specs, scenes, feedback)
    return _english_copy_prompt(brief, specs, scenes, feedback)


# ---------------------------------------------------------------- image scene prompt


def _zone_options(spec: ChannelSpec) -> str:
    zones = [zone.value for zone in allowed_text_zones(spec.image.width, spec.image.height)]
    return ", ".join(zones[:-1]) + f" or {zones[-1]}"


def scene_prompt(brief: BriefContext, specs: Mapping[str, ChannelSpec]) -> str:
    channel_lines = "\n".join(
        f"- {channel} ({spec.image.width}x{spec.image.height}, {spec.image.aspect_ratio} "
        f"{_orientation(spec.image.width, spec.image.height)}): {spec.style.visual_style} "
        f"Headline zone: {_zone_options(spec)}."
        for channel, spec in specs.items()
    )
    sections = [
        "You are an art director and photographer for brands in West Bengal, India. Plan one photograph per channel for "
        "this campaign; an image model renders each from your prompt. Each channel gets its own scene and "
        "composition; do not reuse one scene across channels. The headline is added later as typography, so the "
        "photo itself carries no text.",
        "Brief\n"
        f"- Title: {brief.title}\n- Goal: {brief.goal}\n- Audience: {brief.audience}\n- Tone: {brief.tone}",
    ]
    if brief.insights:
        sections.append("What worked before:\n" + "\n".join(f"- {i}" for i in brief.insights))
    sections.append(f"Channels\n{channel_lines}")
    sections.append(
        "How to plan each photo\n"
        "- Subject: name what is literally in the frame, in concrete nouns. Whatever the brief is about (product, "
        "occasion, place, craft, audience) must be physically present and recognisable. If the brief speaks to "
        "families, show a family.\n"
        "- Authentic detail: clothes, fabrics, objects, surfaces and settings that someone in West Bengal would "
        "recognise as true, not a generic international version.\n"
        "- Moment: let the goal choose it. A launch wants the product seen clearly; a celebration wants people "
        "caught mid-moment, not posing.\n"
        "- Avoid the stock-photo default for this subject, such as a model smiling at the camera in front of a "
        "plain backdrop.\n"
        "- Light: commit to one lighting design and state its direction, quality and colour temperature (low warm "
        "sun from one side, a single soft window, a dusk sky). Flat, even light looks like a generic AI render.\n"
        "- Colour: one dominant tone, a secondary colour and a small accent; let the subject's real colours lead.\n"
        "- Headline zone: choose text_zone from that channel's options. Place the subject off-centre, away from "
        "it, and make that zone genuinely quiet: say what fills it (open sky, a plain wall, soft-focus background, "
        "calm water, an empty table top), with no people, faces or hands in it."
    )
    sections.append(
        "Rules for every prompt\n"
        "- Begin with the composition: where the subject sits and what fills the headline zone. Then the "
        "subject's details, the light and the colours. 50 to 90 words, photographic.\n"
        "- No text of any kind: no words, letters, numbers, logos, signs, shop signage, banners, posters or labels. "
        "Avoid scenes that naturally contain signs, such as shopfronts or street markets with boards.\n"
        "- Clothes, bags and packaging are plain and unbranded.\n"
        "- If the brief names a real person, do not show their face; show their work or their place instead.\n"
        f"- Return exactly one prompt per channel, with these channel ids: {', '.join(specs)}."
    )
    return "\n\n".join(sections)
