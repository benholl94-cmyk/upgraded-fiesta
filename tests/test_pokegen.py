"""Tests for the pokegen norm-conformance engine.

The important cases here are the *negative* ones: a legality engine that only
ever says "legal" is worse than none at all, so most of these assert that a
specific impossible record is caught and named.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from pokegen import Pokemon, Wish, check, generate, is_legal, nearest_legal  # noqa: E402
from pokegen.legality import move_source  # noqa: E402

PERFECT = (31, 31, 31, 31, 31, 31)
NO_EVS = (0, 0, 0, 0, 0, 0)


def rules(mon: Pokemon) -> set[str]:
    return {v.rule for v in check(mon)}


# --------------------------------------------------------------------------
# generation
# --------------------------------------------------------------------------

def test_generated_pokemon_is_legal_by_its_own_validator():
    res = generate(Wish(species="Garchomp", nature="Jolly"))
    assert res.ok and res.exact
    assert is_legal(res.pokemon)


def test_generator_never_invents_an_encounter():
    res = generate(Wish(species="Garchomp"))
    from pokegen.encounters import by_id
    assert by_id(res.pokemon.encounter_id) is not None


def test_unknown_species_is_rejected():
    res = generate(Wish(species="Missingno"))
    assert not res.ok


def test_hidden_ability_routes_to_an_encounter_that_allows_it():
    res = generate(Wish(species="Garchomp", ability="Rough Skin"))
    assert res.ok
    from pokegen.encounters import by_id
    assert by_id(res.pokemon.encounter_id).allow_hidden_ability


def test_egg_move_forces_an_egg_encounter():
    res = generate(Wish(species="Tyranitar", moves=("Curse",)))
    assert res.ok
    assert res.pokemon.encounter_id == "tyranitar-egg"


def test_egg_move_from_raid_is_impossible():
    res = generate(Wish(species="Tyranitar", moves=("Curse",), preferred_method="tera-raid"))
    assert not res.ok
    assert any("Ei-Attacke" in reason for _, reason in res.rejections)


def test_move_the_species_can_never_learn_is_impossible():
    res = generate(Wish(species="Garchomp", moves=("Moonblast",)))
    assert not res.ok


def test_version_exclusive_respects_game():
    assert generate(Wish(species="Iron Bundle", game="Violet")).ok
    assert not generate(Wish(species="Iron Bundle", game="Scarlet")).ok


# --------------------------------------------------------------------------
# the shiny-lock relaxation must never be silent
# --------------------------------------------------------------------------

def test_shiny_locked_wish_fails_exactly():
    res = generate(Wish(species="Flutter Mane", shiny=True))
    assert not res.ok
    assert any("shiny-locked" in reason for _, reason in res.rejections)


def test_nearest_legal_reports_what_it_gave_up():
    res = nearest_legal(Wish(species="Flutter Mane", shiny=True))
    assert res.ok               # a Pokemon came back ...
    assert not res.exact        # ... but it is NOT what was asked for
    assert res.dropped == ("shiny",)
    assert res.pokemon.shiny is False
    assert "ACHTUNG" in res.explain()


def test_nearest_legal_leaves_satisfiable_shiny_wishes_exact():
    res = nearest_legal(Wish(species="Garchomp", shiny=True))
    assert res.exact and res.pokemon.shiny


# --------------------------------------------------------------------------
# the validator, rule by rule
# --------------------------------------------------------------------------

def base_mon(**over) -> Pokemon:
    kw = dict(
        species="Garchomp", level=100, nature="Jolly", ability="Sand Veil",
        ivs=PERFECT, evs=NO_EVS, moves=("Earthquake",), ball="Poke Ball",
        tera_type="Normal", met_location="Picnic", met_level=1,
        encounter_id="garchomp-egg", gender="M",
    )
    kw.update(over)
    return Pokemon(**kw)


def test_baseline_is_legal():
    assert is_legal(base_mon())


@pytest.mark.parametrize("over, rule", [
    ({"evs": (252, 252, 252, 0, 0, 0)}, "ev-total"),
    ({"evs": (255, 0, 0, 0, 0, 0)}, "ev-range"),
    ({"ivs": (32, 31, 31, 31, 31, 31)}, "iv-range"),
    ({"ability": "Levitate"}, "ability-not-in-species"),
    ({"ball": "Cherish Ball"}, "ball-not-in-pool"),
    ({"met_level": 50}, "met-level-range"),
    ({"moves": ("Moonblast",)}, "move-not-learnable"),
    ({"moves": ("Earthquake", "Earthquake")}, "move-duplicate"),
    ({"moves": ()}, "move-count"),
    ({"tera_type": "Plasma"}, "unknown-tera"),
    ({"nature": "Grumpy"}, "unknown-nature"),
    ({"tid": 70000}, "tid-range"),
    ({"nickname": "VielZuLangerName"}, "nickname-length"),
    ({"met_location": "Nirgendwo"}, "met-location"),
])
def test_violation_is_detected(over, rule):
    assert rule in rules(base_mon(**over))


def test_hidden_ability_from_wrong_source_is_caught():
    mon = base_mon(ability="Rough Skin", encounter_id="garchomp-wild-southprovince",
                   met_location="South Province (Area Six)", met_level=52)
    assert "hidden-ability-source" in rules(mon)


def test_shiny_on_locked_encounter_is_fatal():
    mon = Pokemon(
        species="Flutter Mane", level=100, nature="Timid", ability="Protosynthesis",
        ivs=PERFECT, evs=NO_EVS, moves=("Moonblast",), ball="Poke Ball",
        tera_type="Fairy", met_location="Area Zero", met_level=55,
        encounter_id="flutter-mane-areazero", shiny=True, gender=None,
    )
    violations = check(mon)
    assert any(v.rule == "shiny-locked" and v.fatal for v in violations)


def test_genderless_species_cannot_have_a_gender():
    mon = Pokemon(
        species="Flutter Mane", level=100, nature="Timid", ability="Protosynthesis",
        ivs=PERFECT, evs=NO_EVS, moves=("Moonblast",), ball="Poke Ball",
        tera_type="Fairy", met_location="Area Zero", met_level=55,
        encounter_id="flutter-mane-areazero", gender="F",
    )
    assert "gender-impossible" in rules(mon)


def test_raid_iv_floor_is_enforced():
    mon = Pokemon(
        species="Gengar", level=100, nature="Timid", ability="Cursed Body",
        ivs=(31, 0, 0, 31, 0, 31), evs=NO_EVS, moves=("Shadow Ball",),
        ball="Poke Ball", tera_type="Ghost", met_location="Tera Raid Den",
        met_level=75, encounter_id="gengar-raid5", gender="M",
    )
    assert "iv-floor" in rules(mon)          # 5* guarantees 4 perfect IVs, this has 3


def test_species_mismatch_against_encounter():
    assert "species-mismatch" in rules(base_mon(species="Gengar"))


def test_master_ball_legal_in_wild_but_not_in_raid():
    wild = base_mon(ball="Master Ball", encounter_id="garchomp-wild-southprovince",
                    met_location="South Province (Area Six)", met_level=52)
    assert "ball-not-in-pool" not in rules(wild)
    raid = base_mon(ball="Master Ball", encounter_id="garchomp-raid5",
                    met_location="Tera Raid Den", met_level=75)
    assert "ball-not-in-pool" in rules(raid)


# --------------------------------------------------------------------------
# move sourcing and stats
# --------------------------------------------------------------------------

def test_move_source_distinguishes_routes():
    # Earthquake is BOTH a level-55 move and a TM; level-up is checked first
    # and either answer would be correct in game.
    assert move_source("Garchomp", "Earthquake", 100, False) == "level-up"
    assert move_source("Garchomp", "Stone Edge", 100, False) == "TM"   # TM only
    assert move_source("Garchomp", "Outrage", 100, True) == "egg-move"
    assert move_source("Garchomp", "Outrage", 100, False) is None
    assert move_source("Garchomp", "Moonblast", 100, True) is None


def test_tm_moves_have_no_level_requirement():
    # A TM can be applied at any level, so a low-level mon may know it.
    assert move_source("Garchomp", "Stone Edge", 1, False) == "TM"


def test_level_up_move_below_its_level_is_not_known_yet():
    assert move_source("Baxcalibur", "Glaive Rush", 30, False) is None
    assert move_source("Baxcalibur", "Glaive Rush", 62, False) == "level-up"


def test_stat_formula_matches_known_values():
    mon = base_mon(nature="Adamant", evs=(0, 252, 0, 0, 4, 252))
    hp, atk, _, _, _, spe = mon.stats()
    assert hp == 357          # 108 base, 31 IV, 0 EV, Lv100
    assert atk == 394         # 130 base, 31 IV, 252 EV, Adamant +10%
    assert spe == 303         # 102 base, 31 IV, 252 EV, neutral


def test_neutral_nature_has_no_multiplier():
    a = base_mon(nature="Hardy").stats()
    b = base_mon(nature="Serious").stats()
    assert a == b
