CREATIVE_OPTIONS = {
    "content_type": {
        "cinematic_story": "Cinematic mini story",
        "funny": "Funny / visual comedy",
        "educational": "Educational / explain a concept",
        "product_showcase": "Product showcase",
        "motivational": "Motivational transformation",
        "relaxing": "Relaxing / ambient",
        "satisfying_process": "Satisfying process",
        "travel": "Travel moment",
        "food": "Food / recipe",
        "nature": "Nature moment",
        "fashion": "Fashion / styling",
        "tutorial": "Quick tutorial",
    },
    "tone": {
        "cinematic": "Cinematic",
        "funny_playful": "Funny and playful",
        "heartwarming": "Heartwarming",
        "suspenseful": "Suspenseful",
        "inspiring": "Inspiring",
        "calming": "Calm",
        "bold_dramatic": "Bold and dramatic",
    },
    "visual_style": {
        "live_action": "Photoreal live action",
        "stylized_3d": "Stylized 3D animation",
        "anime": "Anime illustration",
        "stop_motion": "Stop motion",
        "documentary": "Natural documentary",
        "vintage_film": "Vintage film",
    },
    "camera_style": {
        "smooth_cinematic": "Smooth cinematic movement",
        "handheld_documentary": "Handheld documentary",
        "locked_off": "Stable locked camera",
        "dynamic_tracking": "Dynamic tracking shot",
        "macro_closeup": "Macro and close detail",
    },
    "music_style": {
        "cinematic": "Cinematic instrumental score",
        "upbeat_pop": "Upbeat pop instrumental",
        "playful_comedy": "Playful comic score",
        "ambient": "Soft ambient music",
        "electronic": "Electronic beat",
        "acoustic": "Acoustic instrumental",
        "none": "No background music",
    },
    "dialogue_style": {
        "none": "No dialogue",
        "natural_dialogue": "Brief natural dialogue",
        "voiceover": "Short voice-over narration",
    },
}


def normalize_creative_brief(form):
    brief = {}
    for field, choices in CREATIVE_OPTIONS.items():
        value = form.get(field, "")
        brief[field] = value if value in choices else next(iter(choices))
    return brief
