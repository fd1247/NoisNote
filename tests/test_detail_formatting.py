from __future__ import annotations

from src.ui.detail.formatting import elide_metadata_value


def test_elide_metadata_value_keeps_short_values_and_falls_back_for_empty_values() -> None:
    assert elide_metadata_value("short value") == "short value"
    assert elide_metadata_value("") == "--"


def test_elide_metadata_value_truncates_long_values_with_ascii_ellipsis() -> None:
    value = "x" * 60

    assert elide_metadata_value(value) == ("x" * 48) + "..."
