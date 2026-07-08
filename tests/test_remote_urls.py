from __future__ import annotations

from src.utils.remote_urls import canonicalize_video_url


def test_canonicalize_video_url_strips_userinfo_from_video_hosts() -> None:
    assert (
        canonicalize_video_url(
            "https://user:secret@www.bilibili.com/video/BV1d6KS6SEwU/?spm_id_from=333.1007"
        )
        == "https://www.bilibili.com/video/BV1d6KS6SEwU"
    )
    assert (
        canonicalize_video_url("https://user:secret@www.youtube.com/watch?v=qWFo8GKXHq8&si=shared")
        == "https://www.youtube.com/watch?v=qWFo8GKXHq8"
    )


def test_canonicalize_video_url_does_not_treat_suffix_lookalike_hosts_as_video_hosts() -> None:
    raw_url = "https://fakebilibili.com/video/BV1d6KS6SEwU/?spm_id_from=333.1007"

    assert canonicalize_video_url(raw_url) == raw_url
