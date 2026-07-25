"""pokegen -- a norm-conformance engine for Pokemon records.

Decides what a *legal* Pokemon is and builds one that satisfies a wish, or
explains precisely why no legal route exists. Pure local computation:
no console access, no injection path, no network.
"""

from .generate import Result, Wish, generate, nearest_legal
from .legality import Violation, check, is_legal
from .model import Pokemon

__all__ = [
    "Pokemon", "Wish", "Result", "Violation",
    "generate", "nearest_legal", "check", "is_legal",
]
