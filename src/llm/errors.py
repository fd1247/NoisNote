"""LLM 错误到用户提示文案的映射。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SummaryFailure:
    """总结失败的稳定分类结果。"""

    code: str
    message: str


def classify_summary_failure(error: str) -> SummaryFailure:
    """把底层 LLM 异常映射为稳定、可操作的用户提示。"""
    value = (error or "").lower()
    if (
        "api key" in value
        or "unauthorized" in value
        or "authentication" in value
        or "401" in value
        or "403" in value
    ):
        return SummaryFailure("LLM-001", "总结失败：API Key 无效或未配置，请在设置中检查 LLM 配置。")
    if "timeout" in value or "超时" in value:
        return SummaryFailure("LLM-002", "总结失败：网络超时，请检查网络后重试。")
    if "status" in value or "http" in value or "api" in value or "bad request" in value or "client error" in value:
        return SummaryFailure("LLM-003", "总结失败：LLM API 返回错误，请检查模型名、Base URL 和服务状态。")
    return SummaryFailure("LLM-004", f"总结失败：{error}")


def summary_failure_message(error: str) -> str:
    return classify_summary_failure(error).message


def summary_failure_code(error: str) -> str:
    return classify_summary_failure(error).code
