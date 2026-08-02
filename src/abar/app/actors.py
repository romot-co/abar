"""Authenticated actor passed across application boundaries."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class Actor:
    id: str
    role: Literal["human", "agent"]

    def require_human(self) -> None:
        if self.role != "human":
            raise PermissionError("human authority is required")
