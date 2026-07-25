"""pokegen CLI -- local, offline, stdlib-only.

Sends nothing anywhere: it computes a record and prints it. There is no
console/injection path and no network call in this package, so the
disclose-and-consent gate `ghm_core` uses for its network subcommands does
not apply here.

    python3 -m pokegen gen Garchomp --nature Jolly --shiny --ball "Dusk Ball"
    python3 -m pokegen gen "Flutter Mane" --shiny
    python3 -m pokegen check record.json
    python3 -m pokegen list
"""

from __future__ import annotations

import argparse
import json
import sys

from . import encounters as enc
from .generate import Wish, nearest_legal
from .legality import check
from .model import Pokemon
from .species import NATURES, SPECIES

STAT_ORDER = "HP/Atk/Def/SpA/SpD/Spe"


def _parse_spread(text: str, what: str) -> tuple[int, ...]:
    parts = [p for p in text.replace("/", " ").split() if p]
    if len(parts) != 6:
        raise argparse.ArgumentTypeError(f"{what} braucht 6 Werte ({STAT_ORDER})")
    try:
        return tuple(int(p) for p in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{what}: {exc}") from exc


def cmd_gen(a: argparse.Namespace) -> int:
    wish = Wish(
        species=a.species,
        nature=a.nature,
        ability=a.ability,
        ivs=_parse_spread(a.ivs, "--ivs") if a.ivs else None,
        evs=_parse_spread(a.evs, "--evs") if a.evs else None,
        moves=tuple(a.move or ()),
        ball=a.ball,
        tera_type=a.tera,
        shiny=a.shiny,
        level=a.level,
        gender=a.gender,
        game=a.game,
        ot_name=a.ot,
        tid=a.tid,
        sid=a.sid,
        nickname=a.nickname,
        preferred_method=a.method,
    )
    res = nearest_legal(wish)
    if a.json:
        payload = {
            "ok": res.ok,
            "exact": res.exact,
            "dropped": list(res.dropped),
            "encounter_id": res.encounter_id,
            "rejections": [{"encounter": e, "reason": r} for e, r in res.rejections],
            "pokemon": res.pokemon.__dict__ if res.ok else None,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    else:
        print(res.explain())
    # 0 = wish met exactly, 1 = met only after dropping something, 2 = impossible
    if not res.ok:
        return 2
    return 0 if res.exact else 1


def cmd_check(a: argparse.Namespace) -> int:
    raw = json.loads(sys.stdin.read() if a.path == "-" else open(a.path, encoding="utf-8").read())
    for key in ("ivs", "evs", "moves"):
        if key in raw and isinstance(raw[key], list):
            raw[key] = tuple(raw[key])
    mon = Pokemon(**raw)
    violations = check(mon)
    if not violations:
        print("LEGAL — konsistent mit " + mon.encounter_id)
        return 0
    print(f"ILLEGAL — {len(violations)} Regelverstoß/-verstöße:")
    for v in violations:
        print("  " + str(v))
    return 1


def cmd_list(a: argparse.Namespace) -> int:
    if a.what in ("species", "all"):
        print("Spezies:")
        for name, sp in sorted(SPECIES.items()):
            ab = ", ".join(sp.legal_abilities())
            print(f"  #{sp.dex:<4} {name:<14} {ab}")
    if a.what in ("encounters", "all"):
        print("\nEncounter:")
        for e in enc.ENCOUNTERS:
            flags = []
            if not e.shiny_allowed:
                flags.append("shiny-locked")
            if e.min_perfect_ivs:
                flags.append(f"{e.min_perfect_ivs}x31")
            if e.allow_hidden_ability:
                flags.append("HA")
            if e.allow_egg_moves:
                flags.append("egg-moves")
            print(f"  {e.id:<32} {e.species:<14} {e.method.value:<10} "
                  f"Lv.{e.level_min}-{e.level_max}  {' '.join(flags)}")
    if a.what == "natures":
        print(" ".join(sorted(NATURES)))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pokegen", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("gen", help="Wunsch -> normkonformer Datensatz")
    g.add_argument("species")
    g.add_argument("--nature")
    g.add_argument("--ability")
    g.add_argument("--ivs", help=f"6 Werte, {STAT_ORDER}")
    g.add_argument("--evs", help=f"6 Werte, {STAT_ORDER}")
    g.add_argument("--move", action="append", help="wiederholbar, max 4")
    g.add_argument("--ball")
    g.add_argument("--tera")
    g.add_argument("--shiny", action="store_true")
    g.add_argument("--level", type=int)
    g.add_argument("--gender", choices=("M", "F"))
    g.add_argument("--game", default="Both", choices=("Both", "Scarlet", "Violet"))
    g.add_argument("--method", choices=("wild", "tera-raid", "static", "egg", "evolution"))
    g.add_argument("--ot", default="MUNIN")
    g.add_argument("--tid", type=int, default=0)
    g.add_argument("--sid", type=int, default=0)
    g.add_argument("--nickname")
    g.add_argument("--json", action="store_true")
    g.set_defaults(func=cmd_gen)

    c = sub.add_parser("check", help="JSON-Datensatz auf Legalität prüfen ('-' = stdin)")
    c.add_argument("path")
    c.set_defaults(func=cmd_check)

    ls = sub.add_parser("list", help="Tabellen anzeigen")
    ls.add_argument("what", nargs="?", default="all",
                    choices=("all", "species", "encounters", "natures"))
    ls.set_defaults(func=cmd_list)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
