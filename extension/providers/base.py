from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


@dataclass(frozen=True, slots=True)
class PlanRequest:
    prompt: str
    scene_context: Mapping[str, Any]
    response_schema: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class PlanResponse:
    response_id: str
    model: str
    plan: Mapping[str, Any]
    request_id: str = ""
    usage: TokenUsage = TokenUsage()


class Provider(Protocol):
    def create_plan(self, request: PlanRequest) -> PlanResponse:
        """Create a validated operation plan without changing the Blender scene."""
