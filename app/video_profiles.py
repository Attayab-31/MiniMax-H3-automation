"""Input constraints for the MiniMax H3 Kaggle notebook."""

MAX_DURATION_SECONDS = 60
MIN_CLIP_SECONDS = 5
MAX_CLIP_SECONDS = 15
MAX_CLIPS_PER_JOB = 6
MAX_PIXELS = 736 * 416


def validate_video_profile(width: int | None, height: int | None, duration_seconds: float, clip_seconds: float) -> str | None:
    if not 5 <= duration_seconds <= MAX_DURATION_SECONDS:
        return "Total duration must be between 5 and 60 seconds."
    if not MIN_CLIP_SECONDS <= clip_seconds <= MAX_CLIP_SECONDS:
        return "Each H3 clip must be between 5 and 15 seconds."
    if duration_seconds > clip_seconds * MAX_CLIPS_PER_JOB:
        return "A Kaggle job can contain at most six clips. Increase clip length or reduce total duration."
    if width is None or height is None:
        return "Enter both output dimensions."
    if width < 128 or height < 128 or width % 32 or height % 32:
        return "Width and height must be at least 128 pixels and divisible by 32."
    if width * height > MAX_PIXELS:
        return "Custom resolution exceeds the notebook's Kaggle preview budget (736x416 pixels)."
    return None
