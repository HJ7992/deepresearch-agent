"""Shared graph state definitions.

Design note (interview talking point): keep state granular instead of stuffing
everything into `messages`. Each field has one writer node, which makes
checkpointing, ablation experiments and debugging tractable. `notes` uses an
append-only reducer so parallel researchers can fan in without clobbering
each other.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class AgentState(TypedDict, total=False):
    question: str  # input: the research question
    sub_questions: list[str]  # planner output
    notes: Annotated[list[str], operator.add]  # researcher outputs (append-only)
    critique: str  # critic output
    revised: bool  # whether the writer has addressed a critique
    report: str  # writer output
