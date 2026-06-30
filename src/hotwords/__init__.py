"""热词管理模块。"""
from .service import HotwordService
from .types import (
    HotwordSet,
    HotwordValidationError,
    MAX_ACTIVE_SETS,
    MAX_WORD_LENGTH,
    MAX_WORDS_PER_SET,
    HARD_LIMIT_TOTAL_WORDS,
    generate_hotword_set_id,
    validate_active_sets,
    validate_hotword_set,
)
from .import_export import (
    HOTWORD_VERSION,
    export_hotword_sets,
    import_hotword_sets,
)

__all__ = [
    "HotwordService",
    "HotwordSet",
    "HotwordValidationError",
    "generate_hotword_set_id",
    "validate_hotword_set",
    "validate_active_sets",
    "export_hotword_sets",
    "import_hotword_sets",
    "MAX_WORDS_PER_SET",
    "MAX_WORD_LENGTH",
    "MAX_ACTIVE_SETS",
    "HARD_LIMIT_TOTAL_WORDS",
    "HOTWORD_VERSION",
]