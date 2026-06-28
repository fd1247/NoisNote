"""Qwen3-ASR GGUF 文本清理工具。"""


def _strip_hotword_prompt_leak(text: str, hotwords: list[str]) -> str:
    return _strip_trailing_hotword_prompt(_strip_leading_hotword_prompt(text, hotwords), hotwords)


def _strip_leading_hotword_prompt(text: str, hotwords: list[str]) -> str:
    marker = "请优先准确识别以下热词："
    cleaned = text.lstrip()
    clean_hotwords = sorted({word.strip() for word in hotwords if word.strip()}, key=len, reverse=True)
    if not clean_hotwords:
        return cleaned

    def strip_hotword_list(value: str, start: int, has_marker: bool) -> tuple[str, bool]:
        pos = start
        consumed_count = 0
        while pos < len(value):
            while pos < len(value) and value[pos] in " \t\r\n、,，;；":
                pos += 1
            matched = False
            for word in clean_hotwords:
                if value.startswith(word, pos):
                    pos += len(word)
                    consumed_count += 1
                    matched = True
                    break
            if not matched:
                break
        should_strip = consumed_count > 0 if has_marker else consumed_count >= 2
        return (value[pos:].lstrip(), True) if should_strip else (value, False)

    while True:
        has_marker = cleaned.startswith(marker)
        start = len(marker) if has_marker else 0
        cleaned, changed = strip_hotword_list(cleaned, start, has_marker)
        if not changed:
            return cleaned


def _strip_trailing_hotword_prompt(text: str, hotwords: list[str]) -> str:
    marker = "请优先准确识别以下热词："
    cleaned = text.rstrip()
    clean_hotwords = [word.strip() for word in hotwords if word.strip()]
    if not clean_hotwords:
        return cleaned

    while True:
        marker_pos = cleaned.rfind(marker)
        if marker_pos < 0:
            return cleaned
        tail = cleaned[marker_pos + len(marker):]
        matched_count = sum(1 for word in clean_hotwords if word in tail)
        if matched_count < 2:
            return cleaned
        cleaned = cleaned[:marker_pos].rstrip(" \t\r\n，,。.;；、")


def _round_seconds(value: float | None) -> float | None:
    if value is None:
        return None
    return round(max(0.0, float(value)), 3)
