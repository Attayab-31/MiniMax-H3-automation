import json
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor

try:
    from google import genai
except Exception:  # pragma: no cover - optional dependency for local development
    genai = None


def _run_with_timeout(fn, *args, timeout_seconds: int = 30, **kwargs):
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fn, *args, **kwargs)
        return future.result(timeout=timeout_seconds)


def _get_client():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or genai is None:
        return None
    return genai.Client(api_key=api_key)


def _fallback_h3_segment_prompts(niche, style_notes, creative_brief, lengths):
    brief = creative_brief or {}
    kind = brief.get("content_type", "cinematic_story")
    tone = brief.get("tone", "cinematic")
    visual = brief.get("visual_style", "live_action")
    camera = brief.get("camera_style", "smooth_cinematic")
    music = brief.get("music_style", "cinematic")
    dialogue = brief.get("dialogue_style", "none")
    aspect_ratio = brief.get("aspect_ratio", "framing suited to the selected output canvas")
    beat_sets = {
        "funny": ["Establish a small, relatable problem with a clear visual setup.", "The subject tries one sensible solution and it goes slightly wrong.", "A harmless complication makes the situation more absurd.", "Land a readable visual punchline, then hold on the subject's reaction."],
        "educational": ["Introduce the subject and show the question or object clearly.", "Demonstrate the first important step with a close, readable view.", "Reveal the result and make the cause-and-effect easy to see.", "End on the key takeaway as a clear visual summary."],
        "product_showcase": ["Reveal the product in a clean hero composition.", "Move closer to show one useful feature in action.", "Show the product being used in a believable everyday setting.", "Finish with a polished hero view and uncluttered composition."],
        "motivational": ["Show the subject facing a specific obstacle.", "They begin the work through a visible, deliberate action.", "Effort builds and a small breakthrough changes their momentum.", "Resolve with a concrete achievement and a confident final pose."],
        "relaxing": ["Establish a calm place and a quiet subject or object.", "Follow one slow, soothing action in a stable composition.", "Notice a gentle environmental change or tactile detail.", "Let the action settle into a peaceful final image."],
        "satisfying_process": ["Show the unworked material and the tools before the process begins.", "Start one precise, tactile transformation.", "Continue the process in a clear close view as the surface changes.", "Reveal the neat finished result and hold briefly."],
        "travel": ["Establish the destination with a strong sense of place.", "Follow the traveler moving through one distinctive location.", "Reveal a local detail, texture, or human moment.", "End on the most memorable view or a natural arrival moment."],
        "food": ["Introduce fresh ingredients and the cooking space.", "Show one clear preparation action in a close view.", "Capture the key cooking transformation with visible texture.", "Present the finished dish with a simple, appetizing final reveal."],
        "nature": ["Establish the habitat and the subject's natural behavior.", "Follow one clear movement through the environment.", "Reveal a small change in weather, light, or animal behavior.", "End on a quiet, memorable view of the habitat."],
        "fashion": ["Establish the full outfit and setting in a clean composition.", "Show one garment detail or styling choice in a close view.", "Follow a natural movement that shows how the outfit moves.", "Finish with a confident full look and clear silhouette."],
        "tutorial": ["Show the starting state and the useful goal.", "Demonstrate the first simple step clearly.", "Complete the key action and reveal what changed.", "Show the finished result in a clean, easy-to-understand view."],
        "cinematic_story": ["Establish the protagonist, place, and immediate goal.", "The protagonist notices a specific clue or change.", "A visible consequence raises the stakes and prompts a reaction.", "Resolve the beat with a memorable image that invites the next moment."],
    }
    beats = beat_sets.get(kind, beat_sets["cinematic_story"])
    result = []
    for index, seconds in enumerate(lengths):
        beat = beats[min(index, len(beats) - 1)]
        if dialogue == "natural_dialogue":
            speech = ["The subject pauses and says: <d>[English] Let's see what happens.</d>",
                      "The subject says: <d>[English] I think I understand.</d>",
                      "The subject reacts: <d>[English] That changed everything.</d>",
                      "The subject smiles and says: <d>[English] We did it.</d>"][min(index, 3)]
            speech = f"A clear, natural-speaking subject (S1) {speech}"
        elif dialogue == "voiceover":
            speech = f"A calm narrator (S1) says in an off-screen voiceover: <d>[English] {['First, notice the starting point.', 'Now watch what changes.', 'The small detail makes the difference.', 'Here is the finished result.'][min(index, 3)]}</d> while the visible subject's lips remain closed."
        else:
            speech = "No dialogue or voice-over."
        result.append(
            f"integrated_multimodal_description: [Shot 1] {visual.replace('_', ' ')}, {tone.replace('_', ' ')}. "
            f"A {camera.replace('_', ' ')} camera frames {niche} in a coherent {aspect_ratio} composition. "
            f"{style_notes or 'Keep the same subject identity, wardrobe, setting, color palette, and lighting across the sequence.'} "
            f"During this {seconds}-second continuous shot, {beat} Use natural movement and a decisive ending state that connects visually to the next clip. "
            f"{speech} "
            f"Avoid unrelated actions, extra characters, and visible text unless requested."
            f"\n\noverall_soundscape: Natural location ambience and quiet physical sounds that match the visible action, kept clear and synchronized."
            f"\n\nnon_diegetic_music: {'N/A' if music == 'none' else music.replace('_', ' ') + ' instrumental music paced to this beat, with a clean transition into the next clip.'}"
        )
    return result


def generate_h3_segment_prompts(niche: str, style_notes: str | None,
                                duration_seconds: float, chunk_seconds: float,
                                creative_brief: dict | None = None) -> list[str]:
    """Write one self-contained, continuous MiniMax H3 shot prompt per notebook segment."""
    niche = (niche or "cinematic short video").strip()
    duration_seconds = float(duration_seconds or 30)
    chunk_seconds = max(5.0, min(15.0, float(chunk_seconds or 10)))
    count = max(1, math.ceil(duration_seconds / chunk_seconds))
    lengths = [min(chunk_seconds, duration_seconds - index * chunk_seconds) for index in range(count)]
    fallback = _fallback_h3_segment_prompts(niche, style_notes, creative_brief or {}, lengths)
    client = _get_client()
    if client is None:
        return fallback

    system_instruction = (
        "You are a MiniMax H3 audiovisual prompt writer. Return valid JSON only, shaped as "
        "{\"clips\":[\"complete prompt for clip 1\", ...]}. Return exactly the requested number of clips. "
        "Each clip is generated as its own separate H3 call, so write each prompt self-contained and do not rely on timestamps or other prompts. "
        "Each prompt must use exactly these sections: integrated_multimodal_description: [Shot 1] ..., "
        "overall_soundscape: ..., non_diegetic_music: .... Describe one continuous shot and one primary visible action per clip. "
        "Begin with visual style, requested aspect ratio, and composition, then concrete subject, setting, action progression, coherent camera move, light, and a final state. "
        "Keep character identity, clothing, important props, environment, and style consistent in every clip. Give each clip a distinct sequential story beat. "
        "Describe audible diegetic dialogue and synchronized effects in the first field; ambient and physical sounds in overall_soundscape; "
        "audience-only score in non_diegetic_music. Use N/A for score if requested. Use specific, filmable details, not adjective piles. "
        "Follow dialogue_style exactly: none means no speech; natural_dialogue means one short line with a stable speaker ID and <d>[English] ...</d> tags; voiceover means brief narration and closed lips on visible characters. "
        "Follow music_style exactly; none means write non_diegetic_music: N/A. Do not add unrequested on-screen text. Keep action plausible for the clip duration."
    )
    prompt = json.dumps({
        "niche": niche,
        "shared_continuity_and_style": style_notes or "Choose a coherent style and keep the same subject identity and setting throughout.",
        "creative_choices": creative_brief or {},
        "total_duration_seconds": duration_seconds,
        "clip_durations_seconds": lengths,
        "prompting_reference": "MiniMax H3 base T2VA prompting structure",
    }, ensure_ascii=False)

    def _generate():
        response = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
            contents=prompt,
            config={"system_instruction": system_instruction,
                    "response_mime_type": "application/json"},
        )
        payload = json.loads(response.text)
        clips = payload.get("clips") if isinstance(payload, dict) else None
        if not isinstance(clips, list) or len(clips) != count or any(not isinstance(item, str) or not item.strip() for item in clips):
            raise ValueError("Prompt writer returned an invalid clip list.")
        return [item.strip() for item in clips]

    try:
        return _run_with_timeout(_generate, timeout_seconds=60)
    except Exception:
        return fallback


def generate_platform_metadata(niche: str, prompt_used: str, platform: str) -> dict:
    platform_key = (platform or "youtube").lower()
    client = _get_client()
    if client is None:
        return _fallback_platform_metadata(niche, prompt_used, platform_key)

    if platform_key == "youtube":
        system_instruction = (
            "You create YouTube metadata for a short-form AI video. Return valid JSON with keys: title, description, hashtags. "
            "title must be <= 100 characters, include a hook, and stay on the actual content of the video. "
            "description must be a few sentences with a strong hook and an ending line of relevant hashtags, max 15 hashtags. "
            "Use the actual visual events described in the prompt, not just the niche."
        )
    else:
        system_instruction = (
            "You create TikTok metadata for a short-form AI video. Return valid JSON with keys: title, description, hashtags. "
            "The caption must be <= 2200 chars, the opening ~150 chars should serve as the hook, and the caption should include 3-8 integrated hashtags. "
            "Base the caption on what actually happens in the video, not the niche alone."
        )

    prompt = (
        f"Platform: {platform_key}\n"
        f"Niche: {niche}\n"
        f"Prompt used: {prompt_used}\n"
        "Return only JSON with title, description, hashtags."
    )

    def _generate():
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config={"system_instruction": system_instruction},
        )
        return response.text.strip()

    try:
        raw = _run_with_timeout(_generate, timeout_seconds=30)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.replace("```json", "").replace("```", "").strip()
        data = json.loads(cleaned)
        if isinstance(data, dict):
            result = {
                "title": str(data.get("title") or f"{niche.title()} short video"),
                "description": str(data.get("description") or ""),
                "hashtags": [str(tag).strip(" #") for tag in (data.get("hashtags") or []) if str(tag).strip()],
            }
            if platform_key == "youtube":
                result["title"] = result["title"][:100]
                if not result["description"]:
                    result["description"] = "Watch this cinematic vertical AI short unfold in real time. " + \
                        " ".join(f"#{tag}" for tag in result["hashtags"][:10])
            else:
                result["description"] = result["description"][:2200]
            return result
    except Exception:
        pass

    return _fallback_platform_metadata(niche, prompt_used, platform_key)


def _fallback_platform_metadata(niche: str, prompt_used: str, platform: str) -> dict:
    title = f"{niche.title()} AI vertical short"
    hashtags = ["ai", "cinematic", "shortvideo",
                niche.lower().replace(" ", "")[:12]]
    description = (
        "A sleek, cinematic vertical short built around the action in this scene. "
        f"{title} " + " ".join(f"#{tag}" for tag in hashtags[:10])
    )
    if platform == "tiktok":
        caption = (
            "This shot opens with a polished cinematic motion sequence and keeps the pacing tight from start to finish. "
            "The visuals feel premium, vertical, and high-contrast while the mood stays immersive and modern. "
            f"#{hashtags[0]} #{hashtags[1]} #{hashtags[2]}"
        )
        return {"title": title[:60], "description": caption[:2200], "hashtags": hashtags[:8]}
    return {"title": title[:100], "description": description[:500], "hashtags": hashtags[:10]}
