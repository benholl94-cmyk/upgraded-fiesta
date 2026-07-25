"""Wish -> concrete legal Pokemon, or a precise explanation of why not.

The generator picks an encounter from `encounters.ENCOUNTERS` that can satisfy
every hard constraint in the wish, then fills the unspecified fields with
values that encounter permits. It never relaxes a rule to make a wish fit --
if nothing in the table works, it reports which constraint killed each
candidate, which is the answer to "why is my wish not norm-conformant?".
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from . import encounters as enc
from .legality import check
from .model import Pokemon, Wish
from .species import SPECIES

DEFAULT_NATURE = "Hardy"
DEFAULT_BALL = "Poke Ball"
DEFAULT_TERA = "Normal"
DEFAULT_LEVEL = 100


@dataclass(frozen=True)
class Result:
    pokemon: Pokemon | None
    encounter_id: str | None
    rejections: tuple[tuple[str, str], ...] = ()   # (encounter_id, reason)
    dropped: tuple[str, ...] = ()                  # wish fields that had to be given up

    @property
    def ok(self) -> bool:
        return self.pokemon is not None

    @property
    def exact(self) -> bool:
        """True only if the wish was satisfied without dropping anything."""
        return self.ok and not self.dropped

    def explain(self) -> str:
        if self.ok:
            head = []
            if self.dropped:
                head = ["ACHTUNG — Wunsch nicht exakt erfüllbar, aufgegeben: "
                        + ", ".join(self.dropped), ""]
            return "\n".join(head) + self.pokemon.summary()
        lines = ["Kein normkonformer Weg zu diesem Wunsch.", ""]
        if not self.rejections:
            lines.append("  Für diese Spezies existiert kein Encounter in der Tabelle.")
        for eid, reason in self.rejections:
            lines.append(f"  {eid}: {reason}")
        return "\n".join(lines)


def _rejection(w: Wish, e: enc.Encounter) -> str | None:
    """Why this encounter cannot serve the wish -- None if it can."""
    sp = SPECIES[w.species]

    if w.game != "Both" and e.game not in ("Both", w.game):
        return f"nur in {e.game}, angefragt wurde {w.game}"
    if w.preferred_method and e.method.value != w.preferred_method:
        return f"Methode ist {e.method.value}, angefragt wurde {w.preferred_method}"
    if w.shiny and not e.shiny_allowed:
        return "shiny-locked — dieses Pokémon kann aus dieser Quelle nie schillernd sein"
    if w.ability and w.ability == sp.hidden_ability and not e.allow_hidden_ability:
        return f"kann die versteckte Fähigkeit {w.ability!r} nicht liefern"
    if w.ball and w.ball not in e.ball_pool:
        return f"{w.ball} ist über {e.method.value} nicht erhältlich"
    needed_eggs = [m for m in w.moves if m in sp.egg_moves and m not in sp.tm_moves
                   and m not in sp.learn_level]
    if needed_eggs and not e.allow_egg_moves:
        return f"kann Ei-Attacke(n) {', '.join(needed_eggs)} nicht liefern"
    if w.level is not None and w.level < e.level_min:
        return f"Fundlevel ist mindestens {e.level_min}, gewünscht ist Lv.{w.level}"
    unknown = [m for m in w.moves
               if m not in sp.tm_moves and m not in sp.learn_level and m not in sp.egg_moves]
    if unknown:
        return f"{w.species} lernt {', '.join(unknown)} nie"
    return None


def _fill_moves(w: Wish, e: enc.Encounter, level: int) -> tuple[str, ...]:
    sp = SPECIES[w.species]
    moves = list(dict.fromkeys(w.moves))[:4]
    if len(moves) < 4:
        by_level = sorted(sp.learn_level.items(), key=lambda kv: -kv[1])
        # Strongest level-up moves first, then TMs, and only then the level-0
        # starter filler (Tackle & co) that nobody actually wants on a set.
        pool = [m for m, lv in by_level if 0 < lv <= level]
        pool += sorted(sp.tm_moves)
        pool += [m for m, lv in by_level if lv == 0]
        for m in pool:
            if len(moves) == 4:
                break
            if m not in moves:
                moves.append(m)
    return tuple(moves) or ("Tackle",)


def _default_gender(w: Wish) -> str | None:
    sp = SPECIES[w.species]
    if sp.is_genderless:
        return None
    if w.gender in ("M", "F"):
        return w.gender
    if sp.gender_ratio == 0:
        return "M"
    if sp.gender_ratio == 8:
        return "F"
    return "M"


def generate(w: Wish) -> Result:
    if w.species not in SPECIES:
        return Result(None, None, (("-", f"{w.species!r} ist nicht in der Spezies-Tabelle"),))

    candidates = enc.for_species(w.species)
    if not candidates:
        return Result(None, None, ())

    rejections: list[tuple[str, str]] = []
    # Prefer eggs when egg moves are wanted, else the least restrictive source.
    ordered = sorted(candidates, key=lambda e: (not e.allow_egg_moves, e.min_perfect_ivs))

    for e in ordered:
        why = _rejection(w, e)
        if why:
            rejections.append((e.id, why))
            continue

        level = w.level if w.level is not None else max(DEFAULT_LEVEL, e.level_min)
        met_level = min(max(e.level_min, 1), e.level_max)
        sp = SPECIES[w.species]

        mon = Pokemon(
            species=w.species,
            level=level,
            nature=w.nature or DEFAULT_NATURE,
            ability=w.ability or sp.abilities[0],
            ivs=w.ivs or (31, 31, 31, 31, 31, 31),
            evs=w.evs or (0, 0, 0, 0, 0, 0),
            moves=_fill_moves(w, e, level),
            ball=w.ball or DEFAULT_BALL,
            tera_type=w.tera_type or e.forced_tera_type or DEFAULT_TERA,
            met_location=e.location,
            met_level=met_level,
            encounter_id=e.id,
            shiny=w.shiny,
            gender=_default_gender(w),
            ot_name=w.ot_name,
            tid=w.tid,
            sid=w.sid,
            nickname=w.nickname,
        )

        violations = check(mon)
        if not violations:
            return Result(mon, e.id, tuple(rejections))
        rejections.append((e.id, "; ".join(v.detail for v in violations)))

    return Result(None, None, tuple(rejections))


def nearest_legal(w: Wish) -> Result:
    """If the wish fails, retry once with the shiny flag dropped -- by far the
    most common single reason a wish is impossible.

    The relaxation is always reported in `Result.dropped`; callers must not
    treat a relaxed result as an exact match (see `Result.exact`).
    """
    res = generate(w)
    if res.ok or not w.shiny:
        return res
    relaxed = generate(replace(w, shiny=False))
    if relaxed.ok:
        return Result(relaxed.pokemon, relaxed.encounter_id,
                      res.rejections, dropped=("shiny",))
    return res
