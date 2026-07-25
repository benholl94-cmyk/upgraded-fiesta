"""The Pokemon record and the wish that asks for one."""

from __future__ import annotations

from dataclasses import dataclass, field

from .species import NATURES, SPECIES

STAT_NAMES = ("HP", "Atk", "Def", "SpA", "SpD", "Spe")

EV_MAX_PER_STAT = 252
EV_MAX_TOTAL = 510
IV_MAX = 31
LEVEL_MAX = 100
NICKNAME_MAX = 12


@dataclass(frozen=True)
class Pokemon:
    """A concrete, fully specified Pokemon record."""

    species: str
    level: int
    nature: str
    ability: str
    ivs: tuple[int, int, int, int, int, int]
    evs: tuple[int, int, int, int, int, int]
    moves: tuple[str, ...]
    ball: str
    tera_type: str
    met_location: str
    met_level: int
    encounter_id: str
    shiny: bool = False
    gender: str | None = None          # "M", "F" or None for genderless
    ot_name: str = "MUNIN"
    tid: int = 0
    sid: int = 0
    language: str = "GER"
    nickname: str | None = None

    def stats(self) -> tuple[int, ...]:
        """Final stats at the current level (Gen 3+ formula)."""
        sp = SPECIES[self.species]
        out = []
        for i in range(6):
            base, iv, ev = sp.base_stats[i], self.ivs[i], self.evs[i]
            core = ((2 * base + iv + ev // 4) * self.level) // 100
            if i == 0:
                out.append(core + self.level + 10)
            else:
                mod = NATURES.get(self.nature)
                mult = 1.0
                if mod:
                    if mod[0] == i:
                        mult = 1.1
                    elif mod[1] == i:
                        mult = 0.9
                out.append(int((core + 5) * mult))
        return tuple(out)

    def summary(self) -> str:
        sp = SPECIES[self.species]
        lines = [
            f"{self.nickname or self.species}"
            f"{'' if self.gender is None else f' ({self.gender})'}"
            f"{' *shiny*' if self.shiny else ''}  Lv.{self.level}",
            f"  Nature   {self.nature}",
            f"  Ability  {self.ability}"
            f"{'  [Hidden]' if self.ability == sp.hidden_ability else ''}",
            f"  Tera     {self.tera_type}",
            f"  Ball     {self.ball}",
            "  IVs      " + " / ".join(f"{n} {v}" for n, v in zip(STAT_NAMES, self.ivs)),
            "  EVs      " + (" / ".join(f"{n} {v}" for n, v in zip(STAT_NAMES, self.evs) if v)
                             or "keine"),
            f"  Stats    " + " / ".join(f"{n} {v}" for n, v in zip(STAT_NAMES, self.stats())),
            f"  Moves    " + ", ".join(self.moves),
            f"  Met      {self.met_location} @ Lv.{self.met_level}",
            f"  Source   {self.encounter_id}",
        ]
        return "\n".join(lines)


@dataclass(frozen=True)
class Wish:
    """What the user asks for. Every field except `species` is optional --
    unset fields are filled by the generator with whatever the chosen
    encounter allows."""

    species: str
    nature: str | None = None
    ability: str | None = None
    ivs: tuple[int, int, int, int, int, int] | None = None
    evs: tuple[int, int, int, int, int, int] | None = None
    moves: tuple[str, ...] = ()
    ball: str | None = None
    tera_type: str | None = None
    shiny: bool = False
    level: int | None = None
    gender: str | None = None
    game: str = "Both"
    ot_name: str = "MUNIN"
    tid: int = 0
    sid: int = 0
    nickname: str | None = None
    preferred_method: str | None = None
    _unused: tuple[()] = field(default=(), repr=False)
