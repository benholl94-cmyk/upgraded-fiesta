"""Encounter table -- the allowlist the generator selects from.

This is the file that makes the whole thing work. The generator NEVER invents
an encounter; it only ever picks one row from here and then applies the
constraints that row permits. Same property as `hm-tool-exec`'s operation
allowlist: the request selects among fixed entries, it never builds one.

If a wish cannot be satisfied by any row here, the correct answer is "this
Pokemon cannot exist legitimately", not "widen the table".

Accuracy note
-------------
Values are hand-entered for Scarlet/Violet from commonly documented mechanics.
The IV floors encode the usual Tera Raid progression (3* -> 2, 4* -> 3,
5* -> 4, 6* -> 5 guaranteed 31s) and the 3-guaranteed floor on Paradox and
box legendaries. Treat this table as a seed to verify against the real
tables, not as an authority -- it is small enough to audit by eye, which is
the point.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Method(str, Enum):
    WILD = "wild"
    TERA_RAID = "tera-raid"
    STATIC = "static"
    EGG = "egg"
    EVOLUTION = "evolution"


# Every ball obtainable in Scarlet/Violet by normal play.
STANDARD_BALLS = frozenset({
    "Poke Ball", "Great Ball", "Ultra Ball", "Premier Ball", "Heal Ball",
    "Net Ball", "Nest Ball", "Dive Ball", "Dusk Ball", "Timer Ball",
    "Quick Ball", "Repeat Ball", "Luxury Ball", "Level Ball", "Lure Ball",
    "Moon Ball", "Friend Ball", "Love Ball", "Fast Ball", "Heavy Ball",
})

# The Master Ball exists in SV but is disabled inside Tera Raid Battles.
WILD_BALLS = STANDARD_BALLS | {"Master Ball"}
RAID_BALLS = STANDARD_BALLS
# An egg inherits the mother's ball; Master and Cherish can never be inherited.
EGG_BALLS = STANDARD_BALLS


@dataclass(frozen=True)
class Encounter:
    id: str
    species: str
    method: Method
    game: str                      # "Scarlet", "Violet" or "Both"
    location: str
    level_min: int
    level_max: int
    ball_pool: frozenset[str]
    min_perfect_ivs: int = 0
    shiny_allowed: bool = True
    allow_hidden_ability: bool = False
    allow_egg_moves: bool = False  # eggs, or SV Mirror Herb on a bred parent
    forced_tera_type: str | None = None
    note: str = ""


ENCOUNTERS: tuple[Encounter, ...] = (
    # --- Garchomp -------------------------------------------------------
    Encounter(
        id="garchomp-wild-southprovince",
        species="Garchomp", method=Method.WILD, game="Both",
        location="South Province (Area Six)", level_min=52, level_max=56,
        ball_pool=WILD_BALLS,
    ),
    Encounter(
        id="garchomp-raid5",
        species="Garchomp", method=Method.TERA_RAID, game="Both",
        location="Tera Raid Den", level_min=75, level_max=75,
        ball_pool=RAID_BALLS, min_perfect_ivs=4, allow_hidden_ability=True,
    ),
    Encounter(
        id="garchomp-egg",
        species="Garchomp", method=Method.EGG, game="Both",
        location="Picnic", level_min=1, level_max=1,
        ball_pool=EGG_BALLS, allow_hidden_ability=True, allow_egg_moves=True,
        note="Hatched as Gible; met level 1, met location Picnic.",
    ),

    # --- Dragapult ------------------------------------------------------
    Encounter(
        id="dragapult-raid6",
        species="Dragapult", method=Method.TERA_RAID, game="Both",
        location="Tera Raid Den", level_min=75, level_max=75,
        ball_pool=RAID_BALLS, min_perfect_ivs=5, allow_hidden_ability=True,
    ),
    Encounter(
        id="dragapult-egg",
        species="Dragapult", method=Method.EGG, game="Both",
        location="Picnic", level_min=1, level_max=1,
        ball_pool=EGG_BALLS, allow_hidden_ability=True, allow_egg_moves=True,
        note="Hatched as Dreepy.",
    ),

    # --- Tyranitar ------------------------------------------------------
    Encounter(
        id="tyranitar-raid5",
        species="Tyranitar", method=Method.TERA_RAID, game="Both",
        location="Tera Raid Den", level_min=75, level_max=75,
        ball_pool=RAID_BALLS, min_perfect_ivs=4, allow_hidden_ability=True,
    ),
    Encounter(
        id="tyranitar-egg",
        species="Tyranitar", method=Method.EGG, game="Both",
        location="Picnic", level_min=1, level_max=1,
        ball_pool=EGG_BALLS, allow_hidden_ability=True, allow_egg_moves=True,
        note="Hatched as Larvitar.",
    ),

    # --- Baxcalibur -----------------------------------------------------
    Encounter(
        id="baxcalibur-raid6",
        species="Baxcalibur", method=Method.TERA_RAID, game="Both",
        location="Tera Raid Den", level_min=75, level_max=75,
        ball_pool=RAID_BALLS, min_perfect_ivs=5, allow_hidden_ability=True,
    ),
    Encounter(
        id="baxcalibur-egg",
        species="Baxcalibur", method=Method.EGG, game="Both",
        location="Picnic", level_min=1, level_max=1,
        ball_pool=EGG_BALLS, allow_hidden_ability=True, allow_egg_moves=True,
        note="Hatched as Frigibax.",
    ),

    # --- Annihilape -----------------------------------------------------
    Encounter(
        id="annihilape-egg",
        species="Annihilape", method=Method.EGG, game="Both",
        location="Picnic", level_min=1, level_max=1,
        ball_pool=EGG_BALLS, allow_hidden_ability=True, allow_egg_moves=True,
        note="Hatched as Mankey; evolves via Rage Fist x20 as Primeape.",
    ),

    # --- Gholdengo ------------------------------------------------------
    Encounter(
        id="gholdengo-evolution",
        species="Gholdengo", method=Method.EVOLUTION, game="Both",
        location="Paldea (Gimmighoul)", level_min=1, level_max=100,
        ball_pool=WILD_BALLS,
        note="Evolved from Gimmighoul with 999 Gimmighoul Coins. "
             "Met data is the Gimmighoul's, so any standard ball is fine.",
    ),

    # --- Paradox: shiny-locked, 3 guaranteed perfect IVs ----------------
    Encounter(
        id="flutter-mane-areazero",
        species="Flutter Mane", method=Method.STATIC, game="Scarlet",
        location="Area Zero", level_min=55, level_max=60,
        ball_pool=WILD_BALLS, min_perfect_ivs=3, shiny_allowed=False,
        note="Ancient Paradox form -- Scarlet only, shiny-locked.",
    ),
    Encounter(
        id="iron-bundle-areazero",
        species="Iron Bundle", method=Method.STATIC, game="Violet",
        location="Area Zero", level_min=55, level_max=60,
        ball_pool=WILD_BALLS, min_perfect_ivs=3, shiny_allowed=False,
        note="Future Paradox form -- Violet only, shiny-locked.",
    ),

    # --- Lucario / Gengar / Ditto ---------------------------------------
    Encounter(
        id="lucario-wild-glaseado",
        species="Lucario", method=Method.WILD, game="Both",
        location="Glaseado Mountain", level_min=40, level_max=48,
        ball_pool=WILD_BALLS,
    ),
    Encounter(
        id="lucario-egg",
        species="Lucario", method=Method.EGG, game="Both",
        location="Picnic", level_min=1, level_max=1,
        ball_pool=EGG_BALLS, allow_hidden_ability=True, allow_egg_moves=True,
        note="Hatched as Riolu.",
    ),
    Encounter(
        id="gengar-raid5",
        species="Gengar", method=Method.TERA_RAID, game="Both",
        location="Tera Raid Den", level_min=75, level_max=75,
        ball_pool=RAID_BALLS, min_perfect_ivs=4,
    ),
    Encounter(
        id="ditto-wild-westprovince",
        species="Ditto", method=Method.WILD, game="Both",
        location="West Province (Area One)", level_min=28, level_max=34,
        ball_pool=WILD_BALLS,
    ),
)


def for_species(name: str) -> tuple[Encounter, ...]:
    return tuple(e for e in ENCOUNTERS if e.species == name)


def by_id(encounter_id: str) -> Encounter | None:
    for e in ENCOUNTERS:
        if e.id == encounter_id:
            return e
    return None
