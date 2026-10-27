"""Base class for the pieces of a scenario the entrypoint runs alongside the stage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Context:
    """What a component gets at setup: the open stage and the scenario configuration."""

    stage: Any  # pxr.Usd.Stage; typed loosely so this module imports before Kit starts
    cfg: dict


class Component:
    """A unit of scenario logic.

    setup() runs once the stage is open and before the timeline plays; update()
    runs on the main thread once per app update, so it may change the stage and
    the physics state; shutdown() runs before the app closes.
    """

    def setup(self, ctx: Context) -> None:
        """Prepare the component for the open stage."""

    def update(self, dt: float) -> None:
        """Advance by one app update of dt sim seconds."""

    def shutdown(self) -> None:
        """Release what setup() acquired."""
