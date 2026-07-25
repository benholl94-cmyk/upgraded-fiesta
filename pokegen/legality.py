"""The rule engine: given a concrete Pokemon, list every reason it could not
have come out of the game.

`check()` returns an empty tuple for a record that is consistent with its
declared encounter. Every violation carries the rule name, so callers can
distinguish "this is fixable" (EV spread) from "this can never be legal"
(shiny-locked species).

This is the defensive half of the package too: run it on a Pokemon somebody
traded you and it tells you whether it was genned.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import encounters as enc
from .model import (
    EV_MAX_PER_STAT,
    EV_MAX_TOTAL,
    IV_MAX,
    LEVEL_MAX,
    NICKNAME_MAX,
    STAT_NAMES,
    Pokemon,
)
from .species import NATURES, SPECIES, TERA_TYPES

# A violation the game engine itself could never produce, no matter the route.
FATAL_RULES = frozenset({
    "unknown-species", "unknown-encounter", "species-mismatch",
    "shiny-locked", "ability-not-in-species", "gender-impossible",
    "move-not-learnable",
})


@dataclass(frozen=True)
class Violation:
    rule: str
    detail: str

    @property
    def fatal(self) -> bool:
        return self.rule in FATAL_RULES

    def __str__(self) -> str:
        mark = "FATAL" if self.fatal else "fix"
        return f"[{mark}] {self.rule}: {self.detail}"


def move_source(species_name: str, move: str, level: int, allow_egg: bool) -> str | None:
    """Return how `move` could be known, or None if it could not be."""
    sp = SPECIES[species_name]
    lvl = sp.learn_level.get(move)
    if lvl is not None and lvl <= level:
        return "level-up" if lvl else "relearner"
    if move in sp.tm_moves:
        return "TM"
    if move in sp.egg_moves and allow_egg:
        return "egg-move"
    return None


def check(mon: Pokemon) -> tuple[Violation, ...]:
    out: list[Violation] = []
    add = lambda r, d: out.append(Violation(r, d))  # noqa: E731

    sp = SPECIES.get(mon.species)
    if sp is None:
        return (Violation("unknown-species", f"{mon.species!r} is not in the species table"),)

    e = enc.by_id(mon.encounter_id)
    if e is None:
        return (Violation("unknown-encounter", f"no encounter with id {mon.encounter_id!r}"),)
    if e.species != mon.species:
        add("species-mismatch", f"encounter {e.id} yields {e.species}, not {mon.species}")
        return tuple(out)

    # --- level / met data ------------------------------------------------
    if not 1 <= mon.level <= LEVEL_MAX:
        add("level-range", f"level {mon.level} outside 1..{LEVEL_MAX}")
    if mon.met_level > mon.level:
        add("met-level", f"met at Lv.{mon.met_level} but is only Lv.{mon.level}")
    if not e.level_min <= mon.met_level <= e.level_max:
        add("met-level-range",
            f"{e.id} yields Lv.{e.level_min}-{e.level_max}, met level is {mon.met_level}")
    if mon.met_location != e.location:
        add("met-location", f"{e.id} is at {e.location!r}, record says {mon.met_location!r}")

    # --- ball -------------------------------------------------------------
    if mon.ball not in e.ball_pool:
        add("ball-not-in-pool", f"{mon.ball} not obtainable via {e.method.value} ({e.id})")

    # --- shiny ------------------------------------------------------------
    if mon.shiny and not e.shiny_allowed:
        add("shiny-locked", f"{mon.species} from {e.id} can never be shiny")

    # --- IVs --------------------------------------------------------------
    for name, iv in zip(STAT_NAMES, mon.ivs):
        if not 0 <= iv <= IV_MAX:
            add("iv-range", f"{name} IV {iv} outside 0..{IV_MAX}")
    perfect = sum(1 for iv in mon.ivs if iv == IV_MAX)
    if perfect < e.min_perfect_ivs:
        add("iv-floor",
            f"{e.id} guarantees {e.min_perfect_ivs} perfect IVs, record has {perfect}")

    # --- EVs --------------------------------------------------------------
    for name, ev in zip(STAT_NAMES, mon.evs):
        if not 0 <= ev <= EV_MAX_PER_STAT:
            add("ev-range", f"{name} EV {ev} outside 0..{EV_MAX_PER_STAT}")
    if sum(mon.evs) > EV_MAX_TOTAL:
        add("ev-total", f"EV total {sum(mon.evs)} exceeds {EV_MAX_TOTAL}")

    # --- nature / ability / gender ---------------------------------------
    if mon.nature not in NATURES:
        add("unknown-nature", f"{mon.nature!r} is not a nature")
    if mon.ability not in sp.legal_abilities():
        add("ability-not-in-species",
            f"{mon.species} cannot have {mon.ability!r}; legal: {', '.join(sp.legal_abilities())}")
    elif mon.ability == sp.hidden_ability and not e.allow_hidden_ability:
        add("hidden-ability-source",
            f"{e.id} cannot yield the hidden ability {mon.ability!r}")

    if sp.is_genderless and mon.gender is not None:
        add("gender-impossible", f"{mon.species} is genderless but record says {mon.gender!r}")
    elif not sp.is_genderless:
        if mon.gender not in ("M", "F"):
            add("gender-missing", f"{mon.species} has a gender; record says {mon.gender!r}")
        elif sp.gender_ratio == 0 and mon.gender == "F":
            add("gender-impossible", f"{mon.species} is always male")
        elif sp.gender_ratio == 8 and mon.gender == "M":
            add("gender-impossible", f"{mon.species} is always female")

    # --- tera -------------------------------------------------------------
    if mon.tera_type not in TERA_TYPES:
        add("unknown-tera", f"{mon.tera_type!r} is not a Tera type")
    elif e.forced_tera_type and mon.tera_type != e.forced_tera_type:
        add("tera-forced", f"{e.id} always yields Tera {e.forced_tera_type}")

    # --- moves ------------------------------------------------------------
    if not 1 <= len(mon.moves) <= 4:
        add("move-count", f"{len(mon.moves)} moves; must be 1..4")
    if len(set(mon.moves)) != len(mon.moves):
        add("move-duplicate", "the same move appears twice")
    for mv in mon.moves:
        src = move_source(mon.species, mv, mon.level, e.allow_egg_moves)
        if src is None:
            if mv in sp.egg_moves:
                add("move-needs-egg",
                    f"{mv!r} is an egg move; {e.id} cannot provide it "
                    f"(breed it, or use a Mirror Herb picnic)")
            else:
                add("move-not-learnable", f"{mon.species} can never learn {mv!r}")

    # --- trainer data -----------------------------------------------------
    if not 0 <= mon.tid <= 65535:
        add("tid-range", f"TID {mon.tid} outside 0..65535")
    if not 0 <= mon.sid <= 65535:
        add("sid-range", f"SID {mon.sid} outside 0..65535")
    if mon.nickname and len(mon.nickname) > NICKNAME_MAX:
        add("nickname-length", f"nickname is {len(mon.nickname)} chars; max {NICKNAME_MAX}")

    return tuple(out)


def is_legal(mon: Pokemon) -> bool:
    return not check(mon)
