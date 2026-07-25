"""Species reference data for the legality engine.

This is a *curated subset*, not a complete dex dump. PKHeX ships several
megabytes of binary tables extracted from the games; reproducing that here
would be neither honest nor maintainable. What is here is hand-entered for a
set of commonly requested Gen-9 species and is enough to exercise every rule
in `legality.py`.

Extend it by adding entries -- the rule engine reads this table and nothing
else, so a new species needs no code changes.

Fields
------
gender_ratio  Female share in eighths: 0 = always male, 4 = 50/50,
              8 = always female, -1 = genderless.
abilities     (slot1, slot2, hidden). slot2 may be None.
learn_level   {move: earliest level it can be known}. Level 0 = known from
              hatch/capture at any level (evolution/relearner moves included).
tm_moves      Moves obtainable from a TM in Scarlet/Violet.
egg_moves     Moves only obtainable via breeding or the SV Mirror Herb.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Species:
    dex: int
    name: str
    base_stats: tuple[int, int, int, int, int, int]  # HP Atk Def SpA SpD Spe
    abilities: tuple[str, str | None, str | None]
    gender_ratio: int
    egg_groups: tuple[str, ...]
    learn_level: dict[str, int] = field(default_factory=dict)
    tm_moves: frozenset[str] = frozenset()
    egg_moves: frozenset[str] = frozenset()

    @property
    def is_genderless(self) -> bool:
        return self.gender_ratio < 0

    @property
    def can_breed(self) -> bool:
        return "Undiscovered" not in self.egg_groups

    def legal_abilities(self) -> tuple[str, ...]:
        return tuple(a for a in self.abilities if a)

    @property
    def hidden_ability(self) -> str | None:
        return self.abilities[2]


SPECIES: dict[str, Species] = {
    "Garchomp": Species(
        dex=445,
        name="Garchomp",
        base_stats=(108, 130, 95, 80, 85, 102),
        abilities=("Sand Veil", None, "Rough Skin"),
        gender_ratio=4,
        egg_groups=("Monster", "Dragon"),
        learn_level={
            "Tackle": 0, "Sand Attack": 0, "Dragon Rush": 0, "Sandstorm": 0,
            "Take Down": 0, "Slash": 0, "Dragon Claw": 48, "Dig": 0,
            "Crunch": 0, "Dual Chop": 0, "Earthquake": 55, "Swords Dance": 0,
        },
        tm_moves=frozenset({
            "Earthquake", "Stone Edge", "Swords Dance", "Substitute",
            "Protect", "Rest", "Fire Fang", "Poison Jab", "Iron Head",
            "Scale Shot", "Dragon Claw", "Rock Slide", "Sandstorm",
        }),
        egg_moves=frozenset({"Outrage", "Iron Tail", "Double-Edge", "Scary Face"}),
    ),
    "Dragapult": Species(
        dex=887,
        name="Dragapult",
        base_stats=(88, 120, 75, 100, 75, 142),
        abilities=("Clear Body", "Infiltrator", "Cursed Body"),
        gender_ratio=4,
        egg_groups=("Amorphous", "Dragon"),
        learn_level={
            "Astonish": 0, "Bite": 0, "Quick Attack": 0, "Dragon Darts": 60,
            "Phantom Force": 0, "Double Hit": 0, "Dragon Dance": 0,
            "U-turn": 0, "Last Resort": 0,
        },
        tm_moves=frozenset({
            "Dragon Dance", "Substitute", "Protect", "Rest", "U-turn",
            "Shadow Ball", "Fire Blast", "Thunderbolt", "Draco Meteor",
            "Will-O-Wisp", "Sucker Punch", "Tera Blast",
        }),
        egg_moves=frozenset({"Sucker Punch", "Endeavor", "Curse"}),
    ),
    "Tyranitar": Species(
        dex=248,
        name="Tyranitar",
        base_stats=(100, 134, 110, 95, 100, 61),
        abilities=("Sand Stream", None, "Unnerve"),
        gender_ratio=4,
        egg_groups=("Monster",),
        learn_level={
            "Bite": 0, "Rock Slide": 0, "Crunch": 0, "Screech": 0,
            "Thrash": 0, "Scary Face": 0, "Payback": 0, "Hyper Beam": 75,
            "Stone Edge": 0, "Sandstorm": 0,
        },
        tm_moves=frozenset({
            "Earthquake", "Stone Edge", "Substitute", "Protect", "Rest",
            "Ice Punch", "Fire Punch", "Thunder Punch", "Dragon Dance",
            "Iron Head", "Rock Slide", "Sandstorm", "Tera Blast",
        }),
        egg_moves=frozenset({"Dragon Dance", "Stealth Rock", "Curse", "Iron Defense"}),
    ),
    "Baxcalibur": Species(
        dex=998,
        name="Baxcalibur",
        base_stats=(115, 145, 92, 75, 86, 87),
        abilities=("Thermal Exchange", None, "Ice Body"),
        gender_ratio=4,
        egg_groups=("Monster", "Dragon"),
        learn_level={
            "Tackle": 0, "Icicle Spear": 0, "Bite": 0, "Dragon Claw": 0,
            "Ice Shard": 0, "Glaive Rush": 62, "Scary Face": 0,
            "Crunch": 0, "Swords Dance": 0,
        },
        tm_moves=frozenset({
            "Earthquake", "Substitute", "Protect", "Rest", "Swords Dance",
            "Ice Spinner", "Dragon Claw", "Iron Head", "Low Kick",
            "Icicle Crash", "Tera Blast",
        }),
        egg_moves=frozenset({"Dragon Dance", "Curse", "Avalanche"}),
    ),
    "Annihilape": Species(
        dex=979,
        name="Annihilape",
        base_stats=(110, 115, 80, 50, 90, 90),
        abilities=("Vital Spirit", "Inner Focus", "Defiant"),
        gender_ratio=4,
        egg_groups=("Field", "Human-Like"),
        learn_level={
            "Rage Fist": 35, "Screech": 0, "Cross Chop": 0, "Thrash": 0,
            "Outrage": 0, "Final Gambit": 0, "Bulk Up": 0, "Shadow Claw": 0,
        },
        tm_moves=frozenset({
            "Bulk Up", "Substitute", "Protect", "Rest", "Drain Punch",
            "Earthquake", "Taunt", "U-turn", "Close Combat", "Tera Blast",
        }),
        egg_moves=frozenset({"Encore", "Counter", "Night Slash"}),
    ),
    "Gholdengo": Species(
        dex=1000,
        name="Gholdengo",
        base_stats=(87, 60, 95, 133, 91, 84),
        abilities=("Good as Gold", None, None),
        gender_ratio=-1,
        egg_groups=("Undiscovered",),
        learn_level={
            "Make It Rain": 0, "Shadow Ball": 0, "Recover": 0,
            "Nasty Plot": 0, "Astonish": 0, "Night Shade": 0,
        },
        tm_moves=frozenset({
            "Nasty Plot", "Substitute", "Protect", "Rest", "Shadow Ball",
            "Thunderbolt", "Focus Blast", "Dazzling Gleam", "Tera Blast",
        }),
        egg_moves=frozenset(),
    ),
    "Flutter Mane": Species(
        dex=987,
        name="Flutter Mane",
        base_stats=(55, 55, 55, 135, 135, 135),
        abilities=("Protosynthesis", None, None),
        gender_ratio=-1,
        egg_groups=("Undiscovered",),
        learn_level={
            "Astonish": 0, "Moonblast": 0, "Shadow Ball": 0, "Mystical Fire": 0,
            "Power Gem": 0, "Perish Song": 0, "Calm Mind": 0,
        },
        tm_moves=frozenset({
            "Calm Mind", "Substitute", "Protect", "Rest", "Shadow Ball",
            "Dazzling Gleam", "Thunderbolt", "Icy Wind", "Tera Blast",
        }),
        egg_moves=frozenset(),
    ),
    "Iron Bundle": Species(
        dex=991,
        name="Iron Bundle",
        base_stats=(56, 80, 114, 124, 60, 136),
        abilities=("Quark Drive", None, None),
        gender_ratio=-1,
        egg_groups=("Undiscovered",),
        learn_level={
            "Freeze-Dry": 0, "Hydro Pump": 0, "Icy Wind": 0,
            "Whirlpool": 0, "Helping Hand": 0, "Encore": 0,
        },
        tm_moves=frozenset({
            "Substitute", "Protect", "Rest", "Ice Beam", "Hydro Pump",
            "Flip Turn", "Icy Wind", "Encore", "Tera Blast",
        }),
        egg_moves=frozenset(),
    ),
    "Lucario": Species(
        dex=448,
        name="Lucario",
        base_stats=(70, 110, 70, 115, 70, 90),
        abilities=("Steadfast", "Inner Focus", "Justified"),
        gender_ratio=1,
        egg_groups=("Field", "Human-Like"),
        learn_level={
            "Aura Sphere": 0, "Close Combat": 0, "Metal Claw": 0,
            "Bone Rush": 0, "Quick Attack": 0, "Swords Dance": 0,
            "Extreme Speed": 0, "Meteor Mash": 0,
        },
        tm_moves=frozenset({
            "Swords Dance", "Substitute", "Protect", "Rest", "Close Combat",
            "Drain Punch", "Iron Head", "Nasty Plot", "Earthquake", "Tera Blast",
        }),
        egg_moves=frozenset({"Blaze Kick", "Bullet Punch", "Sky Uppercut", "Feint"}),
    ),
    "Gengar": Species(
        dex=94,
        name="Gengar",
        base_stats=(60, 65, 60, 130, 75, 110),
        abilities=("Cursed Body", None, None),
        gender_ratio=4,
        egg_groups=("Amorphous",),
        learn_level={
            "Shadow Ball": 0, "Hex": 0, "Lick": 0, "Curse": 0,
            "Dark Pulse": 0, "Sludge Wave": 0, "Destiny Bond": 0,
        },
        tm_moves=frozenset({
            "Nasty Plot", "Substitute", "Protect", "Rest", "Shadow Ball",
            "Thunderbolt", "Sludge Bomb", "Dazzling Gleam", "Tera Blast",
        }),
        egg_moves=frozenset({"Clear Smog", "Perish Song", "Haze"}),
    ),
    "Ditto": Species(
        dex=132,
        name="Ditto",
        base_stats=(48, 48, 48, 48, 48, 48),
        abilities=("Limber", None, "Imposter"),
        gender_ratio=-1,
        egg_groups=("Ditto",),
        learn_level={"Transform": 0},
        tm_moves=frozenset(),
        egg_moves=frozenset(),
    ),
}


# Nature -> (boosted stat index, lowered stat index). None = neutral.
# Stat indices follow base_stats order minus HP: 1=Atk 2=Def 3=SpA 4=SpD 5=Spe
NATURES: dict[str, tuple[int, int] | None] = {
    "Hardy": None, "Docile": None, "Serious": None, "Bashful": None, "Quirky": None,
    "Lonely": (1, 2), "Brave": (1, 5), "Adamant": (1, 3), "Naughty": (1, 4),
    "Bold": (2, 1), "Relaxed": (2, 5), "Impish": (2, 3), "Lax": (2, 4),
    "Timid": (5, 1), "Hasty": (5, 2), "Jolly": (5, 3), "Naive": (5, 4),
    "Modest": (3, 1), "Mild": (3, 2), "Quiet": (3, 5), "Rash": (3, 4),
    "Calm": (4, 1), "Gentle": (4, 2), "Sassy": (4, 5), "Careful": (4, 3),
}

TERA_TYPES = (
    "Normal", "Fire", "Water", "Electric", "Grass", "Ice", "Fighting",
    "Poison", "Ground", "Flying", "Psychic", "Bug", "Rock", "Ghost",
    "Dragon", "Dark", "Steel", "Fairy", "Stellar",
)
