#!/usr/bin/env bash
# Tests for scripts/validate_iphone_control_plane.sh
# Uses a minimal pure-bash harness: no external test framework required.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SCRIPT_UNDER_TEST="$REPO_ROOT/scripts/validate_iphone_control_plane.sh"

# ---------------------------------------------------------------------------
# Minimal test harness
# ---------------------------------------------------------------------------
PASS=0
FAIL=0
ERRORS=()

pass() { PASS=$((PASS + 1)); printf '  ok: %s\n' "$1"; }
fail_test() {
  FAIL=$((FAIL + 1))
  ERRORS+=("FAIL: $1")
  printf '  FAIL: %s\n' "$1"
}

assert_exit_zero() {
  local label="$1"; shift
  local output exit_code
  output=$("$@" 2>&1) && exit_code=0 || exit_code=$?
  if [[ $exit_code -eq 0 ]]; then
    pass "$label"
  else
    fail_test "$label (expected exit 0, got $exit_code; output: $output)"
  fi
}

assert_exit_nonzero() {
  local label="$1"; shift
  local output exit_code
  output=$("$@" 2>&1) && exit_code=0 || exit_code=$?
  if [[ $exit_code -ne 0 ]]; then
    pass "$label"
  else
    fail_test "$label (expected non-zero exit, got 0; output: $output)"
  fi
}

assert_stderr_contains() {
  local label="$1"
  local pattern="$2"; shift 2
  local stderr_output exit_code
  stderr_output=$("$@" 2>&1 >/dev/null) && exit_code=0 || exit_code=$?
  if echo "$stderr_output" | grep -qF "$pattern"; then
    pass "$label"
  else
    fail_test "$label (expected stderr to contain '$pattern'; got: $stderr_output)"
  fi
}

assert_stdout_contains() {
  local label="$1"
  local pattern="$2"; shift 2
  local stdout_output exit_code
  stdout_output=$("$@" 2>/dev/null) && exit_code=0 || exit_code=$?
  if echo "$stdout_output" | grep -qF "$pattern"; then
    pass "$label"
  else
    fail_test "$label (expected stdout to contain '$pattern'; got: $stdout_output)"
  fi
}

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

# Minimum valid README.md content
valid_readme() {
  cat <<'EOF'
# upgraded-fiesta

Stand der geprüften App-/Tool-Informationen: 2026-06-12

See [docs/iphone-local-dev-setup.md](docs/iphone-local-dev-setup.md) for the full setup guide.
EOF
}

# Minimum valid docs/iphone-local-dev-setup.md content
valid_setup_doc() {
  cat <<'EOF'
# iPhone Local Dev Setup

## 1. Zielbild
Placeholder.

## 2. Realistische Grenzen von iOS
Placeholder.

## 3. Empfohlene App-Rollen
Placeholder.

## 6. Git mit Working Copy einrichten
Placeholder.

## 7. a-Shell einrichten
Placeholder.

## 8. iSH einrichten
Placeholder.

## 10. Lokale Web-Entwicklung
Placeholder.

## 11. Internet-Grundlagen und Online-Arbeit
Placeholder.

## 13. Sicherheit
Placeholder.

## 14. Backup-Strategie
Placeholder.

## 16. Fehlerbehebung
Placeholder.

## 17. Minimal-Checkliste
Placeholder.

```sh
export DEV_HOST=127.0.0.1
export DEV_BIND=127.0.0.1
export NO_PROXY="localhost,127.0.0.1,::1,*.local"
```

Nutze `0.0.0.0` nur wenn du gezielt LAN-Zugriff benötigst.

Teile niemals `id_ed25519`, sondern nur `id_ed25519.pub`.

Führe unbekannte Shell-Skripte nicht blind mit `curl ... | sh` aus
EOF
}

# Create a temporary repo directory with the validation script installed and
# optional fixture files.  Returns the path in $TMPDIR_OUT.
setup_temp_repo() {
  local tmpdir
  tmpdir="$(mktemp -d)"
  mkdir -p "$tmpdir/scripts" "$tmpdir/docs"
  cp "$SCRIPT_UNDER_TEST" "$tmpdir/scripts/validate_iphone_control_plane.sh"
  chmod +x "$tmpdir/scripts/validate_iphone_control_plane.sh"
  printf '%s' "$tmpdir"
}

run_validation() {
  local tmpdir="$1"
  bash "$tmpdir/scripts/validate_iphone_control_plane.sh"
}

cleanup() { rm -rf "$1"; }

# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

echo "=== validate_iphone_control_plane.sh ==="

# ------------------------------------------------------------------
# T01: passes when all required files and content are present
# ------------------------------------------------------------------
t01_dir="$(setup_temp_repo)"
valid_readme > "$t01_dir/README.md"
valid_setup_doc > "$t01_dir/docs/iphone-local-dev-setup.md"
assert_exit_zero \
  "T01: exits 0 with fully valid fixture" \
  bash "$t01_dir/scripts/validate_iphone_control_plane.sh"
assert_stdout_contains \
  "T01: prints success banner" \
  "Static iPhone control-plane validation passed." \
  bash "$t01_dir/scripts/validate_iphone_control_plane.sh"
assert_stdout_contains \
  "T01: prints starting banner" \
  "Validating static iPhone control-plane..." \
  bash "$t01_dir/scripts/validate_iphone_control_plane.sh"
cleanup "$t01_dir"

# ------------------------------------------------------------------
# T02: fails when README.md is absent
# ------------------------------------------------------------------
t02_dir="$(setup_temp_repo)"
valid_setup_doc > "$t02_dir/docs/iphone-local-dev-setup.md"
# Do NOT create README.md
assert_exit_nonzero \
  "T02: exits non-zero when README.md is missing" \
  run_validation "$t02_dir"
assert_stderr_contains \
  "T02: stderr mentions missing file README.md" \
  "missing required file: README.md" \
  run_validation "$t02_dir"
cleanup "$t02_dir"

# ------------------------------------------------------------------
# T03: fails when docs/iphone-local-dev-setup.md is absent
# ------------------------------------------------------------------
t03_dir="$(setup_temp_repo)"
valid_readme > "$t03_dir/README.md"
# Do NOT create docs/iphone-local-dev-setup.md
assert_exit_nonzero \
  "T03: exits non-zero when docs/iphone-local-dev-setup.md is missing" \
  run_validation "$t03_dir"
assert_stderr_contains \
  "T03: stderr mentions missing docs file" \
  "missing required file: docs/iphone-local-dev-setup.md" \
  run_validation "$t03_dir"
cleanup "$t03_dir"

# ------------------------------------------------------------------
# T04: fails when README.md does not link to setup guide
# ------------------------------------------------------------------
t04_dir="$(setup_temp_repo)"
printf 'Stand der geprüften App-/Tool-Informationen: 2026-06-12\n' > "$t04_dir/README.md"
valid_setup_doc > "$t04_dir/docs/iphone-local-dev-setup.md"
assert_exit_nonzero \
  "T04: exits non-zero when README lacks link to setup guide" \
  run_validation "$t04_dir"
assert_stderr_contains \
  "T04: stderr mentions missing link" \
  "link to the full setup guide" \
  run_validation "$t04_dir"
cleanup "$t04_dir"

# ------------------------------------------------------------------
# T05: fails when README.md does not contain the review date
# ------------------------------------------------------------------
t05_dir="$(setup_temp_repo)"
printf 'See [docs/iphone-local-dev-setup.md](docs/iphone-local-dev-setup.md)\n' > "$t05_dir/README.md"
valid_setup_doc > "$t05_dir/docs/iphone-local-dev-setup.md"
assert_exit_nonzero \
  "T05: exits non-zero when README lacks review date" \
  run_validation "$t05_dir"
assert_stderr_contains \
  "T05: stderr mentions missing review date" \
  "review date" \
  run_validation "$t05_dir"
cleanup "$t05_dir"

# ------------------------------------------------------------------
# T06-T17: fails when each required section heading is missing
# ------------------------------------------------------------------
required_sections=(
  "## 1. Zielbild"
  "## 2. Realistische Grenzen von iOS"
  "## 3. Empfohlene App-Rollen"
  "## 6. Git mit Working Copy einrichten"
  "## 7. a-Shell einrichten"
  "## 8. iSH einrichten"
  "## 10. Lokale Web-Entwicklung"
  "## 11. Internet-Grundlagen und Online-Arbeit"
  "## 13. Sicherheit"
  "## 14. Backup-Strategie"
  "## 16. Fehlerbehebung"
  "## 17. Minimal-Checkliste"
)

tnum=6
for section in "${required_sections[@]}"; do
  tdir="$(setup_temp_repo)"
  valid_readme > "$tdir/README.md"
  # Write setup doc with this one section omitted
  valid_setup_doc | grep -vF "$section" > "$tdir/docs/iphone-local-dev-setup.md"
  assert_exit_nonzero \
    "T$(printf '%02d' $tnum): exits non-zero when section '$section' is missing" \
    run_validation "$tdir"
  assert_stderr_contains \
    "T$(printf '%02d' $tnum): stderr mentions control-plane section" \
    "control-plane section" \
    run_validation "$tdir"
  cleanup "$tdir"
  tnum=$((tnum + 1))
done

# ------------------------------------------------------------------
# T18: fails when export DEV_HOST=127.0.0.1 is missing
# ------------------------------------------------------------------
t18_dir="$(setup_temp_repo)"
valid_readme > "$t18_dir/README.md"
valid_setup_doc | grep -vF "export DEV_HOST=127.0.0.1" > "$t18_dir/docs/iphone-local-dev-setup.md"
assert_exit_nonzero \
  "T18: exits non-zero when DEV_HOST default is missing" \
  run_validation "$t18_dir"
assert_stderr_contains \
  "T18: stderr mentions private localhost default" \
  "private localhost default" \
  run_validation "$t18_dir"
cleanup "$t18_dir"

# ------------------------------------------------------------------
# T19: fails when export DEV_BIND=127.0.0.1 is missing
# ------------------------------------------------------------------
t19_dir="$(setup_temp_repo)"
valid_readme > "$t19_dir/README.md"
valid_setup_doc | grep -vF "export DEV_BIND=127.0.0.1" > "$t19_dir/docs/iphone-local-dev-setup.md"
assert_exit_nonzero \
  "T19: exits non-zero when DEV_BIND default is missing" \
  run_validation "$t19_dir"
assert_stderr_contains \
  "T19: stderr mentions private bind default" \
  "private bind default" \
  run_validation "$t19_dir"
cleanup "$t19_dir"

# ------------------------------------------------------------------
# T20: fails when NO_PROXY line is missing
# ------------------------------------------------------------------
t20_dir="$(setup_temp_repo)"
valid_readme > "$t20_dir/README.md"
valid_setup_doc | grep -vF 'NO_PROXY=' > "$t20_dir/docs/iphone-local-dev-setup.md"
assert_exit_nonzero \
  "T20: exits non-zero when NO_PROXY default is missing" \
  run_validation "$t20_dir"
assert_stderr_contains \
  "T20: stderr mentions local proxy bypass" \
  "local proxy bypass" \
  run_validation "$t20_dir"
cleanup "$t20_dir"

# ------------------------------------------------------------------
# T21: fails when explicit LAN exposure warning is missing
# ------------------------------------------------------------------
t21_dir="$(setup_temp_repo)"
valid_readme > "$t21_dir/README.md"
valid_setup_doc | grep -vF '0.0.0.0' > "$t21_dir/docs/iphone-local-dev-setup.md"
assert_exit_nonzero \
  "T21: exits non-zero when LAN exposure warning is missing" \
  run_validation "$t21_dir"
assert_stderr_contains \
  "T21: stderr mentions explicit LAN exposure warning" \
  "explicit LAN exposure warning" \
  run_validation "$t21_dir"
cleanup "$t21_dir"

# ------------------------------------------------------------------
# T22: fails when SSH secret handling warning is missing
# ------------------------------------------------------------------
t22_dir="$(setup_temp_repo)"
valid_readme > "$t22_dir/README.md"
valid_setup_doc | grep -vF 'id_ed25519' > "$t22_dir/docs/iphone-local-dev-setup.md"
assert_exit_nonzero \
  "T22: exits non-zero when SSH secret handling warning is missing" \
  run_validation "$t22_dir"
assert_stderr_contains \
  "T22: stderr mentions SSH secret handling warning" \
  "SSH secret handling warning" \
  run_validation "$t22_dir"
cleanup "$t22_dir"

# ------------------------------------------------------------------
# T23: fails when download safety warning is missing
# ------------------------------------------------------------------
t23_dir="$(setup_temp_repo)"
valid_readme > "$t23_dir/README.md"
valid_setup_doc | grep -vF 'curl ... | sh' > "$t23_dir/docs/iphone-local-dev-setup.md"
assert_exit_nonzero \
  "T23: exits non-zero when download safety warning is missing" \
  run_validation "$t23_dir"
assert_stderr_contains \
  "T23: stderr mentions download safety warning" \
  "download safety warning" \
  run_validation "$t23_dir"
cleanup "$t23_dir"

# ------------------------------------------------------------------
# T24: fails when disallowed pattern "curl -fsSL" is present
# ------------------------------------------------------------------
t24_dir="$(setup_temp_repo)"
valid_readme > "$t24_dir/README.md"
{ valid_setup_doc; printf '\ncurl -fsSL https://example.com | sh\n'; } \
  > "$t24_dir/docs/iphone-local-dev-setup.md"
assert_exit_nonzero \
  "T24: exits non-zero when 'curl -fsSL' is present" \
  run_validation "$t24_dir"
assert_stderr_contains \
  "T24: stderr mentions pipe-to-shell bootstrap pattern" \
  "pipe-to-shell bootstrap pattern" \
  run_validation "$t24_dir"
cleanup "$t24_dir"

# ------------------------------------------------------------------
# T25: fails when disallowed pattern "docker run" is present
# ------------------------------------------------------------------
t25_dir="$(setup_temp_repo)"
valid_readme > "$t25_dir/README.md"
{ valid_setup_doc; printf '\ndocker run -it ubuntu bash\n'; } \
  > "$t25_dir/docs/iphone-local-dev-setup.md"
assert_exit_nonzero \
  "T25: exits non-zero when 'docker run' is present" \
  run_validation "$t25_dir"
assert_stderr_contains \
  "T25: stderr mentions desktop/container assumption" \
  "desktop/container assumption" \
  run_validation "$t25_dir"
cleanup "$t25_dir"

# ------------------------------------------------------------------
# T26: fails when disallowed pattern "brew install" is present
# ------------------------------------------------------------------
t26_dir="$(setup_temp_repo)"
valid_readme > "$t26_dir/README.md"
{ valid_setup_doc; printf '\nbrew install node\n'; } \
  > "$t26_dir/docs/iphone-local-dev-setup.md"
assert_exit_nonzero \
  "T26: exits non-zero when 'brew install' is present" \
  run_validation "$t26_dir"
assert_stderr_contains \
  "T26: stderr mentions macOS desktop package-manager assumption" \
  "macOS desktop package-manager assumption" \
  run_validation "$t26_dir"
cleanup "$t26_dir"

# ------------------------------------------------------------------
# T27: fails when both required files are absent (README missing first)
# ------------------------------------------------------------------
t27_dir="$(setup_temp_repo)"
# No files at all
assert_exit_nonzero \
  "T27: exits non-zero when both required files are absent" \
  run_validation "$t27_dir"
cleanup "$t27_dir"

# ------------------------------------------------------------------
# T28: fail() writes to stderr, not stdout
# ------------------------------------------------------------------
t28_dir="$(setup_temp_repo)"
# No README to trigger failure
stdout_out="$(bash "$t28_dir/scripts/validate_iphone_control_plane.sh" 2>/dev/null)" || true
assert_exit_nonzero \
  "T28: fails when README.md absent (sanity)" \
  run_validation "$t28_dir"
if [[ -z "$stdout_out" ]] || ! echo "$stdout_out" | grep -qF "Validation failed"; then
  pass "T28: fail() does not write 'Validation failed' to stdout"
else
  fail_test "T28: 'Validation failed' leaked into stdout"
fi
cleanup "$t28_dir"

# ------------------------------------------------------------------
# T29: regression – both rejected text and required text checks run
#      (doc has brew install AND is otherwise valid — reject fires)
# ------------------------------------------------------------------
t29_dir="$(setup_temp_repo)"
valid_readme > "$t29_dir/README.md"
{ valid_setup_doc; printf '\nbrew install ruby\n'; } \
  > "$t29_dir/docs/iphone-local-dev-setup.md"
assert_exit_nonzero \
  "T29: regression – reject_text fires even when require_text all pass" \
  run_validation "$t29_dir"
cleanup "$t29_dir"

# ------------------------------------------------------------------
# T30: boundary – empty docs file causes all require_text checks to fail
# ------------------------------------------------------------------
t30_dir="$(setup_temp_repo)"
valid_readme > "$t30_dir/README.md"
printf '' > "$t30_dir/docs/iphone-local-dev-setup.md"
assert_exit_nonzero \
  "T30: exits non-zero with empty docs/iphone-local-dev-setup.md" \
  run_validation "$t30_dir"
cleanup "$t30_dir"

# ------------------------------------------------------------------
# T31: boundary – empty README.md causes require_text to fail
# ------------------------------------------------------------------
t31_dir="$(setup_temp_repo)"
printf '' > "$t31_dir/README.md"
valid_setup_doc > "$t31_dir/docs/iphone-local-dev-setup.md"
assert_exit_nonzero \
  "T31: exits non-zero with empty README.md" \
  run_validation "$t31_dir"
cleanup "$t31_dir"

# ------------------------------------------------------------------
# T32: whitespace-only README fails require_text (not same as empty)
# ------------------------------------------------------------------
t32_dir="$(setup_temp_repo)"
printf '   \n\t\n   \n' > "$t32_dir/README.md"
valid_setup_doc > "$t32_dir/docs/iphone-local-dev-setup.md"
assert_exit_nonzero \
  "T32: exits non-zero with whitespace-only README.md" \
  run_validation "$t32_dir"
cleanup "$t32_dir"

# ------------------------------------------------------------------
# T33: a directory in place of README.md causes require_file to fail
#      ([[ -f path ]] is false for directories)
# ------------------------------------------------------------------
t33_dir="$(setup_temp_repo)"
mkdir -p "$t33_dir/README.md"
valid_setup_doc > "$t33_dir/docs/iphone-local-dev-setup.md"
assert_exit_nonzero \
  "T33: exits non-zero when README.md is a directory, not a regular file" \
  run_validation "$t33_dir"
assert_stderr_contains \
  "T33: stderr mentions missing required file" \
  "missing required file: README.md" \
  run_validation "$t33_dir"
cleanup "$t33_dir"

# ------------------------------------------------------------------
# T34: fail() always prefixes the message with "Validation failed:"
# ------------------------------------------------------------------
t34_dir="$(setup_temp_repo)"
# Trigger failure by omitting README
assert_stderr_contains \
  "T34: stderr starts with 'Validation failed:' prefix" \
  "Validation failed:" \
  run_validation "$t34_dir"
cleanup "$t34_dir"

# ------------------------------------------------------------------
# T35: "curl -fsSL" alone (not piped to sh) still triggers reject_text
# ------------------------------------------------------------------
t35_dir="$(setup_temp_repo)"
valid_readme > "$t35_dir/README.md"
{ valid_setup_doc; printf '\ncurl -fsSL https://example.com/install.sh\n'; } \
  > "$t35_dir/docs/iphone-local-dev-setup.md"
assert_exit_nonzero \
  "T35: exits non-zero when 'curl -fsSL' appears without pipe-to-shell" \
  run_validation "$t35_dir"
assert_stderr_contains \
  "T35: stderr mentions pipe-to-shell bootstrap pattern" \
  "pipe-to-shell bootstrap pattern" \
  run_validation "$t35_dir"
cleanup "$t35_dir"

# ------------------------------------------------------------------
# T36: partial NO_PROXY without surrounding quotes does not satisfy
#      the exact-string check (fixed-strings match requires full literal)
# ------------------------------------------------------------------
t36_dir="$(setup_temp_repo)"
valid_readme > "$t36_dir/README.md"
# Replace the exact NO_PROXY line with a version lacking the surrounding quotes
valid_setup_doc \
  | sed 's|export NO_PROXY="localhost,127.0.0.1,::1,\*.local"|export NO_PROXY=localhost,127.0.0.1,::1,*.local|' \
  > "$t36_dir/docs/iphone-local-dev-setup.md"
assert_exit_nonzero \
  "T36: exits non-zero when NO_PROXY line is missing surrounding quotes" \
  run_validation "$t36_dir"
assert_stderr_contains \
  "T36: stderr mentions local proxy bypass" \
  "local proxy bypass" \
  run_validation "$t36_dir"
cleanup "$t36_dir"

# ------------------------------------------------------------------
# T37: require_text error message includes the filename
# ------------------------------------------------------------------
t37_dir="$(setup_temp_repo)"
valid_readme > "$t37_dir/README.md"
printf '' > "$t37_dir/docs/iphone-local-dev-setup.md"
assert_stderr_contains \
  "T37: stderr includes the docs filename when require_text fails" \
  "docs/iphone-local-dev-setup.md" \
  run_validation "$t37_dir"
cleanup "$t37_dir"

# ------------------------------------------------------------------
# T38: reject_text error message includes the filename and disallowed pattern
# ------------------------------------------------------------------
t38_dir="$(setup_temp_repo)"
valid_readme > "$t38_dir/README.md"
{ valid_setup_doc; printf '\ndocker run alpine echo hi\n'; } \
  > "$t38_dir/docs/iphone-local-dev-setup.md"
assert_stderr_contains \
  "T38: stderr includes the docs filename when reject_text fires" \
  "docs/iphone-local-dev-setup.md" \
  run_validation "$t38_dir"
assert_stderr_contains \
  "T38: stderr mentions the disallowed pattern 'docker run'" \
  "docker run" \
  run_validation "$t38_dir"
cleanup "$t38_dir"

# ------------------------------------------------------------------
# T39: all three reject patterns checked independently – "brew install"
#      alone in an otherwise valid doc still triggers rejection
# ------------------------------------------------------------------
t39_dir="$(setup_temp_repo)"
valid_readme > "$t39_dir/README.md"
{ valid_setup_doc; printf '\nbrew install python3\n'; } \
  > "$t39_dir/docs/iphone-local-dev-setup.md"
assert_exit_nonzero \
  "T39: boundary – exits non-zero for 'brew install python3' variation" \
  run_validation "$t39_dir"
cleanup "$t39_dir"

# ------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------

echo "Results: $PASS passed, $FAIL failed"
for err in "${ERRORS[@]}"; do
  echo "  $err"
done

[[ $FAIL -eq 0 ]] || exit 1
