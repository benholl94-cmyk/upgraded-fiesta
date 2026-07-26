"""Tests für die Schlüssel-Selbstversorgung.

Der wichtigste Block sind die RFC-5869-Testvektoren: eine selbstgebaute
Schlüsselableitung, die *plausibel* aussieht, aber falsch rechnet, ist
gefährlicher als gar keine. Die Vektoren belegen, dass diese ~10 Zeilen
tatsächlich HKDF sind und nicht etwas, das nur so heisst.

Der zweite Block prüft die Sicherheitseigenschaften, auf die sich der Ansatz
stützt: Ableitung ist deterministisch, Trennung zwischen Diensten ist echt,
Rotation ändert den Wert, und nichts Geheimes verlässt je den Speicher.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

_SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "hugin_keyring.py"
_spec = importlib.util.spec_from_file_location("hugin_keyring", _SCRIPT)
kr = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = kr
_spec.loader.exec_module(kr)


# --------------------------------------------------------------------------
# RFC 5869 — die Ableitung wird nachgerechnet, nicht geglaubt
# --------------------------------------------------------------------------

def test_rfc5869_case_1_sha256():
    """RFC 5869, Appendix A.1 — Basisfall mit Salt und Info."""
    okm = kr.hkdf(
        seed=bytes.fromhex("0b" * 22),
        salt=bytes.fromhex("000102030405060708090a0b0c"),
        info=bytes.fromhex("f0f1f2f3f4f5f6f7f8f9"),
        length=42,
    )
    assert okm.hex() == (
        "3cb25f25faacd57a90434f64d0362f2a"
        "2d2d0a90cf1a5a4c5db02d56ecc4c5bf"
        "34007208d5b887185865"
    )


def test_rfc5869_case_2_longer_inputs():
    """RFC 5869, Appendix A.2 — lange Eingaben, mehrere Expand-Runden."""
    okm = kr.hkdf(
        seed=bytes.fromhex("".join(f"{i:02x}" for i in range(80))),
        salt=bytes.fromhex("".join(f"{i:02x}" for i in range(0x60, 0x60 + 80))),
        info=bytes.fromhex("".join(f"{i:02x}" for i in range(0xb0, 0xb0 + 80))),
        length=82,
    )
    assert okm.hex() == (
        "b11e398dc80327a1c8e7f78c596a4934"
        "4f012eda2d4efad8a050cc4c19afa97c"
        "59045a99cac7827271cb41c65e590e09"
        "da3275600c2f09b8367793a9aca3db71"
        "cc30c58179ec3e87c14c01d5c1f3434f"
        "1d87"
    )


def test_rfc5869_case_3_empty_salt_and_info():
    """RFC 5869, Appendix A.3 — leerer Salt muss auf einen Null-Block fallen."""
    okm = kr.hkdf(seed=bytes.fromhex("0b" * 22), salt=b"", info=b"", length=42)
    assert okm.hex() == (
        "8da4e775a563c18f715f802a063c5a31"
        "b8a11f5c5ee1879ec3454e5f3c738d2d"
        "9d201395faa4b61a96c8"
    )


@pytest.mark.parametrize("length", [0, -1, 255 * 32 + 1])
def test_hkdf_rejects_impossible_lengths(length):
    with pytest.raises(ValueError):
        kr.hkdf(b"seed", info=b"x", length=length)


def test_str_and_bytes_info_agree():
    assert kr.hkdf(b"seed", "abc") == kr.hkdf(b"seed", b"abc")


# --------------------------------------------------------------------------
# Die Eigenschaften, auf die sich der Ansatz stützt
# --------------------------------------------------------------------------

SEED_A = bytes(range(32))
SEED_B = bytes(range(1, 33))


def test_derivation_is_deterministic():
    """Kern des Ansatzes: ein Backup des Seed genügt, weil sich jeder
    Schlüssel exakt reproduzieren lässt."""
    a = kr.derive(SEED_A, "HM_OWNER_TOKEN", 1)
    b = kr.derive(SEED_A, "HM_OWNER_TOKEN", 1)
    assert a == b and len(a) > 40


def test_different_seeds_give_different_keys():
    assert kr.derive(SEED_A, "HM_OWNER_TOKEN", 1) != kr.derive(SEED_B, "HM_OWNER_TOKEN", 1)


def test_services_are_cryptographically_separated():
    """Ein geleakter Dienstschlüssel darf keinen anderen preisgeben."""
    keys = {s.env: kr.derive(SEED_A, s.env, 1) for s in kr.SELF_ISSUED}
    assert len(set(keys.values())) == len(keys)


def test_rotation_changes_the_key():
    assert kr.derive(SEED_A, "HM_OWNER_TOKEN", 1) != kr.derive(SEED_A, "HM_OWNER_TOKEN", 2)


def test_old_version_stays_reproducible_for_grace_period():
    """Ohne das reisst bei jeder Rotation ein laufender Dienst ab."""
    v1 = kr.derive(SEED_A, "HM_OWNER_TOKEN", 1)
    kr.derive(SEED_A, "HM_OWNER_TOKEN", 2)
    assert kr.derive(SEED_A, "HM_OWNER_TOKEN", 1) == v1


def test_key_carries_an_identifying_prefix():
    val = kr.derive(SEED_A, "HM_OWNER_TOKEN", 3)
    assert val.startswith("hmo_3_")


def test_fingerprint_hides_the_value():
    val = kr.derive(SEED_A, "HM_OWNER_TOKEN", 1)
    fp = kr.fingerprint(val)
    assert len(fp) == 12 and fp not in val and val not in fp


# --------------------------------------------------------------------------
# Die Schlüsselkarte
# --------------------------------------------------------------------------

def test_every_key_is_classified():
    for spec in kr.KEYS:
        assert spec.env and spec.purpose
        if spec.self_issued:
            assert spec.prefix, f"{spec.env} braucht ein Präfix"
        else:
            assert spec.provider_url or spec.note, \
                f"{spec.env} ist providergebunden und braucht eine Bezugsquelle"


def test_provider_keys_are_never_derivable():
    """Die entscheidende Trennung: für einen fremden Dienst wäre ein selbst
    gewürfelter Wert schlicht ungültig — er darf gar nicht erst entstehen."""
    provider = [s for s in kr.KEYS if not s.self_issued]
    assert provider, "die Karte sollte Provider-Keys enthalten"
    for spec in provider:
        assert spec not in kr.SELF_ISSUED
        assert spec.prefix == ""


def test_known_provider_keys_are_marked_as_such():
    for env in ("HUGIN_OPENAI_KEY", "HUGIN_GEMINI_KEY", "HM_TELEGRAM_BOT_TOKEN",
                "HM_SLACK_BOT_TOKEN", "HM_DISCORD_BOT_TOKEN"):
        assert kr.BY_ENV[env].self_issued is False


def test_whatsapp_verify_token_is_self_issued():
    """Sonderfall mit Begründung in der Karte: Meta vergleicht nur, was du
    dort einträgst — der Wert stammt also von dir."""
    spec = kr.BY_ENV["HM_WHATSAPP_VERIFY_TOKEN"]
    assert spec.self_issued and spec.note


def test_owner_token_is_self_issued():
    assert kr.BY_ENV["HM_OWNER_TOKEN"].self_issued


# --------------------------------------------------------------------------
# Ablage: nichts Geheimes darf in die Nähe des Index kommen
# --------------------------------------------------------------------------

def test_keyring_lives_outside_the_repo_by_default(monkeypatch):
    monkeypatch.delenv("HUGIN_KEYRING_HOME", raising=False)
    importlib.reload(kr) if False else None      # Default steht im Modul
    assert not str(kr.HOME_DIR).startswith(str(kr.REPO)), \
        "Der Keyring darf nicht im Arbeitsverzeichnis liegen"


def test_gitignore_covers_the_keyring_directory():
    gi = (kr.REPO / ".gitignore").read_text(encoding="utf-8")
    assert ".hugin/" in gi, "Schutz falls HUGIN_KEYRING_HOME ins Repo zeigt"


def test_init_writes_seed_with_owner_only_permissions(tmp_path, monkeypatch):
    monkeypatch.setattr(kr, "HOME_DIR", tmp_path / "ring")
    monkeypatch.setattr(kr, "SEED_FILE", tmp_path / "ring" / "master.seed")
    monkeypatch.setattr(kr, "STATE_FILE", tmp_path / "ring" / "keyring.json")
    monkeypatch.setattr(kr, "AUDIT_FILE", tmp_path / "ring" / "audit.jsonl")

    assert kr.main(["init"]) == 0
    import stat as _stat
    mode = _stat.S_IMODE(kr.SEED_FILE.stat().st_mode)
    assert mode == 0o600, f"Seed ist {mode:o}"
    assert _stat.S_IMODE(kr.STATE_FILE.stat().st_mode) == 0o600


def test_init_refuses_to_clobber_an_existing_seed(tmp_path, monkeypatch):
    """Ein zweites init ohne Warnung würde alle Schlüssel unbrauchbar machen."""
    monkeypatch.setattr(kr, "HOME_DIR", tmp_path / "ring")
    monkeypatch.setattr(kr, "SEED_FILE", tmp_path / "ring" / "master.seed")
    monkeypatch.setattr(kr, "STATE_FILE", tmp_path / "ring" / "keyring.json")
    monkeypatch.setattr(kr, "AUDIT_FILE", tmp_path / "ring" / "audit.jsonl")

    assert kr.main(["init"]) == 0
    first = kr.SEED_FILE.read_text()
    assert kr.main(["init"]) == 2                  # laut verweigert
    assert kr.SEED_FILE.read_text() == first       # unverändert
    assert kr.main(["init", "--force"]) == 2       # --force allein reicht nicht
    assert kr.SEED_FILE.read_text() == first


def test_state_file_never_contains_a_derived_key(tmp_path, monkeypatch):
    """Der Zustand hält nur Versionen — die Schlüssel selbst existieren nur
    im Speicher und in der Shell."""
    monkeypatch.setattr(kr, "HOME_DIR", tmp_path / "ring")
    monkeypatch.setattr(kr, "SEED_FILE", tmp_path / "ring" / "master.seed")
    monkeypatch.setattr(kr, "STATE_FILE", tmp_path / "ring" / "keyring.json")
    monkeypatch.setattr(kr, "AUDIT_FILE", tmp_path / "ring" / "audit.jsonl")

    kr.main(["init"])
    seed = kr.read_seed()
    body = kr.STATE_FILE.read_text(encoding="utf-8")
    for spec in kr.SELF_ISSUED:
        assert kr.derive(seed, spec.env, 1) not in body


def test_audit_log_records_fingerprints_not_values(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(kr, "HOME_DIR", tmp_path / "ring")
    monkeypatch.setattr(kr, "SEED_FILE", tmp_path / "ring" / "master.seed")
    monkeypatch.setattr(kr, "STATE_FILE", tmp_path / "ring" / "keyring.json")
    monkeypatch.setattr(kr, "AUDIT_FILE", tmp_path / "ring" / "audit.jsonl")

    kr.main(["init"])
    kr.main(["show", "HM_OWNER_TOKEN"])
    capsys.readouterr()
    seed = kr.read_seed()
    log = kr.AUDIT_FILE.read_text(encoding="utf-8")
    assert kr.derive(seed, "HM_OWNER_TOKEN", 1) not in log
    assert "fingerprint" in log


def test_show_hides_the_value_without_reveal(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(kr, "HOME_DIR", tmp_path / "ring")
    monkeypatch.setattr(kr, "SEED_FILE", tmp_path / "ring" / "master.seed")
    monkeypatch.setattr(kr, "STATE_FILE", tmp_path / "ring" / "keyring.json")
    monkeypatch.setattr(kr, "AUDIT_FILE", tmp_path / "ring" / "audit.jsonl")

    kr.main(["init"])
    capsys.readouterr()
    kr.main(["show", "HM_OWNER_TOKEN"])
    out = capsys.readouterr().out
    seed = kr.read_seed()
    assert kr.derive(seed, "HM_OWNER_TOKEN", 1) not in out
    assert "fp=" in out


def test_show_refuses_provider_keys(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(kr, "SEED_FILE", tmp_path / "master.seed")
    assert kr.main(["show", "HUGIN_OPENAI_KEY"]) == 1
    assert "providergebunden" in capsys.readouterr().out


def test_rotate_refuses_provider_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(kr, "SEED_FILE", tmp_path / "master.seed")
    assert kr.main(["rotate", "HUGIN_OPENAI_KEY", "--yes"]) == 2


def test_rotate_requires_consent(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(kr, "HOME_DIR", tmp_path / "ring")
    monkeypatch.setattr(kr, "SEED_FILE", tmp_path / "ring" / "master.seed")
    monkeypatch.setattr(kr, "STATE_FILE", tmp_path / "ring" / "keyring.json")
    monkeypatch.setattr(kr, "AUDIT_FILE", tmp_path / "ring" / "audit.jsonl")

    kr.main(["init"])
    assert kr.main(["rotate", "HM_OWNER_TOKEN"]) == 2
    assert kr.Keyring.load().version("HM_OWNER_TOKEN") == 1     # nichts passiert
    assert kr.main(["rotate", "HM_OWNER_TOKEN", "--yes"]) == 0
    ring = kr.Keyring.load()
    assert ring.version("HM_OWNER_TOKEN") == 2
    assert 1 in ring.grace["HM_OWNER_TOKEN"]


def test_env_emits_one_export_per_self_issued_key(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(kr, "HOME_DIR", tmp_path / "ring")
    monkeypatch.setattr(kr, "SEED_FILE", tmp_path / "ring" / "master.seed")
    monkeypatch.setattr(kr, "STATE_FILE", tmp_path / "ring" / "keyring.json")
    monkeypatch.setattr(kr, "AUDIT_FILE", tmp_path / "ring" / "audit.jsonl")

    kr.main(["init"])
    capsys.readouterr()
    kr.main(["env", "--quiet"])
    lines = [l for l in capsys.readouterr().out.splitlines() if l.startswith("export ")]
    assert len(lines) == len(kr.SELF_ISSUED)
    assert not any(s.env in "\n".join(lines) for s in kr.KEYS if not s.self_issued)


def test_env_without_seed_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr(kr, "SEED_FILE", tmp_path / "nichts.seed")
    assert kr.main(["env"]) == 2
