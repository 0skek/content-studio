"""Prompt templates for copy (one per language, written natively) and per-channel image scenes.

Channel tone, length, CTA and hashtag style come from channels.json; nothing channel-specific is hardcoded here.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import BaseModel

from app.caption_length import LengthCounting
from app.channels import ChannelSpec
from app.models import Language

HEADLINE_MAX_WORDS = 8

# Appended in code to every image prompt, whatever the scene writer returned. Headlines are overlaid later.
NO_TEXT_CLAUSE = "No text, no letters, no words, no numbers, no typography, no logos, no signage, no watermark."
HEADLINE_SPACE_CLAUSE = "Keep the bottom third of the frame calm and uncluttered."


class ChannelCopy(BaseModel):
    channel: str
    headline: str
    caption: str
    hashtags: list[str]


class CopySet(BaseModel):
    posts: list[ChannelCopy]


class ChannelScene(BaseModel):
    channel: str
    scene: str


class SceneSet(BaseModel):
    scenes: list[ChannelScene]


@dataclass(frozen=True)
class BriefContext:
    title: str
    goal: str
    audience: str
    tone: str
    insights: tuple[str, ...] = ()


def final_image_prompt(scene: str) -> str:
    return f"{scene.strip()} {HEADLINE_SPACE_CLAUSE} {NO_TEXT_CLAUSE}"


def _orientation(width: int, height: int) -> str:
    if width > height:
        return "landscape"
    if width < height:
        return "portrait"
    return "square"


# ---------------------------------------------------------------- copy prompts

ENGLISH_COPY_OPENING = (
    "You are a senior social media copywriter for Bangladeshi brands. "
    "Write original English copy for each channel below, directly in English."
)
BENGALI_COPY_OPENING = (
    "তুমি বাংলাদেশের ব্র্যান্ডের জন্য কাজ করা একজন অভিজ্ঞ সোশ্যাল মিডিয়া কপিরাইটার। "
    "নিচের প্রতিটি চ্যানেলের জন্য সরাসরি বাংলায় মৌলিক লেখা লেখো — কোনো ইংরেজি লেখা থেকে অনুবাদ নয়। "
    "ঢাকার মানুষ যেভাবে স্বাভাবিকভাবে কথা বলে ও লেখে, সেভাবে লেখো।"
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


def _english_copy_prompt(brief: BriefContext, specs: Mapping[str, ChannelSpec], feedback: Sequence[str]) -> str:
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
    sections.append(
        "Rules\n"
        "- Use only facts stated in the brief. Do not invent addresses, prices, discounts, dates, phone numbers, "
        "URLs or product details.\n"
        f"- headline: at most {HEADLINE_MAX_WORDS} words, no hashtags, no emoji. It is printed on the image.\n"
        "- hashtags: the words only, without the '#' sign.\n"
        f"- Return exactly one post per channel, with these channel ids: {', '.join(specs)}."
    )
    if feedback:
        sections.append(
            "Your previous answer broke these limits. Rewrite so every post fits:\n"
            + "\n".join(f"- {problem}" for problem in feedback)
        )
    return "\n\n".join(sections)


def _bengali_copy_prompt(brief: BriefContext, specs: Mapping[str, ChannelSpec], feedback: Sequence[str]) -> str:
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
    sections.append(
        "নিয়ম\n"
        "- শুধু ব্রিফে দেওয়া তথ্য ব্যবহার করো। ঠিকানা, দাম, ছাড়, তারিখ, ফোন নম্বর, ওয়েবসাইট বা পণ্যের বিবরণ "
        "বানিয়ে লিখবে না।\n"
        f"- headline: সর্বোচ্চ {HEADLINE_MAX_WORDS} শব্দ, হ্যাশট্যাগ বা ইমোজি ছাড়া। এটি ছবির উপর বসানো হবে।\n"
        "- hashtags: '#' চিহ্ন ছাড়া শুধু শব্দ; বাংলাদেশে যা স্বাভাবিকভাবে ব্যবহৃত হয় (বাংলা বা ইংরেজি)।\n"
        f"- প্রতিটি চ্যানেলের জন্য ঠিক একটি পোস্ট দাও, চ্যানেল আইডি হুবহু: {', '.join(specs)}।"
    )
    if feedback:
        sections.append(
            "তোমার আগের উত্তর এই সীমাগুলো ভেঙেছে। প্রতিটি পোস্ট যেন সীমার মধ্যে থাকে, এমনভাবে আবার লেখো:\n"
            + "\n".join(f"- {problem}" for problem in feedback)
        )
    return "\n\n".join(sections)


def copy_prompt(
    brief: BriefContext, language: Language, specs: Mapping[str, ChannelSpec], feedback: Sequence[str] = ()
) -> str:
    """Each language gets its own prompt from the brief alone; no other language's output ever goes in."""
    if language == Language.BENGALI:
        return _bengali_copy_prompt(brief, specs, feedback)
    return _english_copy_prompt(brief, specs, feedback)


# ---------------------------------------------------------------- image scene prompt


def scene_prompt(brief: BriefContext, specs: Mapping[str, ChannelSpec]) -> str:
    channel_lines = "\n".join(
        f"- {channel} ({spec.image.width}x{spec.image.height}, {spec.image.aspect_ratio} "
        f"{_orientation(spec.image.width, spec.image.height)}): {spec.style.visual_style}"
        for channel, spec in specs.items()
    )
    sections = [
        "You are an art director. Write one image-generation prompt per channel for this campaign. "
        "Each channel gets its own scene and composition; do not reuse one scene across channels.",
        "Brief\n"
        f"- Title: {brief.title}\n- Goal: {brief.goal}\n- Audience: {brief.audience}\n- Tone: {brief.tone}",
    ]
    if brief.insights:
        sections.append("What worked before:\n" + "\n".join(f"- {i}" for i in brief.insights))
    sections.append(f"Channels\n{channel_lines}")
    sections.append(
        "Rules for every prompt\n"
        "- Describe only what is visible: subject, setting, composition, lighting, colours, mood. "
        "Photographic and culturally accurate for Bangladesh.\n"
        "- No text of any kind: no words, letters, numbers, logos, signs, shop signage, banners, posters or labels. "
        "Avoid scenes that naturally contain signs, such as shopfronts or street markets with boards.\n"
        "- Keep the bottom third of the frame calm and uncluttered; a headline will be placed there.\n"
        f"- Return exactly one prompt per channel, with these channel ids: {', '.join(specs)}."
    )
    return "\n\n".join(sections)
