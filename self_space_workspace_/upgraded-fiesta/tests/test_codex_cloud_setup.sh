#!/usr/bin/env bash
# Tests for scripts/codex_cloud_setup.sh
# Uses a minimal pure-bash harness: no external test framework required.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SETUP_SCRIPT="$REPO_ROOT/scripts/codex_cloud_setup.sh"
VALIDATE_SCRIPT="$REPO_ROOT/scripts/validate_iphone_control_plane.sh"

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

assert_stdout_not_contains() {
  local label="$1"
  local pattern="$2"; shift 2
  local stdout_output exit_code
  stdout_output=$("$@" 2>/dev/null) && exit_code=0 || exit_code=$?
  if ! echo "$stdout_output" | grep -qF "$pattern"; then
    pass "$label"
  else
    fail_test "$label (expected stdout NOT to contain '$pattern'; got: $stdout_output)"
  fi
}

# ---------------------------------------------------------------------------
# Fixture helpers (mirrors test_validate_iphone_control_plane.sh)
# ---------------------------------------------------------------------------

valid_readme() {
  cat <<'EOF'
# upgraded-fiesta

Stand der geprüften App-/Tool-Informationen: 2026-06-12

See [docs/iphone-local-dev-setup.md](docs/iphone-local-dev-setup.md) for the full setup guide.
EOF
}

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

# Create a temp repo dir with both scripts installed.
setup_temp_repo() {
  local tmpdir
  tmpdir="$(mktemp -d)"
  mkdir -p "$tmpdir/scripts" "$tmpdir/docs"
  cp "$SETUP_SCRIPT"    "$tmpdir/scripts/codex_cloud_setup.sh"
  cp "$VALIDATE_SCRIPT" "$tmpdir/scripts/validate_iphone_control_plane.sh"
  chmod +x "$tmpdir/scripts/codex_cloud_setup.sh"
  chmod +x "$tmpdir/scripts/validate_iphone_control_plane.sh"
  printf '%s' "$tmpdir"
}

cleanup() { rm -rf "$1"; }

run_setup() {
  local tmpdir="$1"
  bash "$tmpdir/scripts/codex_cloud_setup.sh"
}

# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

echo "=== codex_cloud_setup.sh ==="

# ------------------------------------------------------------------
# S01: exits 0 when all required files and content are valid
# ------------------------------------------------------------------
s01_dir="$(setup_temp_repo)"
valid_readme > "$s01_dir/README.md"
valid_setup_doc > "$s01_dir/docs/iphone-local-dev-setup.md"
assert_exit_zero \
  "S01: exits 0 with fully valid fixture" \
  run_setup "$s01_dir"
cleanup "$s01_dir"

# ------------------------------------------------------------------
# S02: prints project banner to stdout
# ------------------------------------------------------------------
s02_dir="$(setup_temp_repo)"
valid_readme > "$s02_dir/README.md"
valid_setup_doc > "$s02_dir/docs/iphone-local-dev-setup.md"
assert_stdout_contains \
  "S02: stdout contains 'Codex cloud setup for upgraded-fiesta'" \
  "Codex cloud setup for upgraded-fiesta" \
  run_setup "$s02_dir"
cleanup "$s02_dir"

# ------------------------------------------------------------------
# S03: prints the repository path
# ------------------------------------------------------------------
s03_dir="$(setup_temp_repo)"
valid_readme > "$s03_dir/README.md"
valid_setup_doc > "$s03_dir/docs/iphone-local-dev-setup.md"
assert_stdout_contains \
  "S03: stdout contains 'Repository:'" \
  "Repository:" \
  run_setup "$s03_dir"
cleanup "$s03_dir"

# ------------------------------------------------------------------
# S04: prints success message after validation passes
# ------------------------------------------------------------------
s04_dir="$(setup_temp_repo)"
valid_readme > "$s04_dir/README.md"
valid_setup_doc > "$s04_dir/docs/iphone-local-dev-setup.md"
assert_stdout_contains \
  "S04: stdout contains no-dependency success message" \
  "No dependency installation required. Static iPhone control-plane validation passed." \
  run_setup "$s04_dir"
cleanup "$s04_dir"

# ------------------------------------------------------------------
# S05: also prints validate_iphone_control_plane.sh success banner
# ------------------------------------------------------------------
s05_dir="$(setup_temp_repo)"
valid_readme > "$s05_dir/README.md"
valid_setup_doc > "$s05_dir/docs/iphone-local-dev-setup.md"
assert_stdout_contains \
  "S05: stdout contains validation sub-script success banner" \
  "Static iPhone control-plane validation passed." \
  run_setup "$s05_dir"
cleanup "$s05_dir"

# ------------------------------------------------------------------
# S06: exits non-zero when README.md is missing (delegates to validate script)
# ------------------------------------------------------------------
s06_dir="$(setup_temp_repo)"
valid_setup_doc > "$s06_dir/docs/iphone-local-dev-setup.md"
# No README.md
assert_exit_nonzero \
  "S06: exits non-zero when README.md is absent" \
  run_setup "$s06_dir"
cleanup "$s06_dir"

# ------------------------------------------------------------------
# S07: exits non-zero when docs/iphone-local-dev-setup.md is missing
# ------------------------------------------------------------------
s07_dir="$(setup_temp_repo)"
valid_readme > "$s07_dir/README.md"
# No docs file
assert_exit_nonzero \
  "S07: exits non-zero when docs/iphone-local-dev-setup.md is absent" \
  run_setup "$s07_dir"
cleanup "$s07_dir"

# ------------------------------------------------------------------
# S08: does NOT print success message when validation fails
# ------------------------------------------------------------------
s08_dir="$(setup_temp_repo)"
# No fixture files at all
stdout_out="$(bash "$s08_dir/scripts/codex_cloud_setup.sh" 2>/dev/null)" || true
if ! echo "$stdout_out" | grep -qF "No dependency installation required."; then
  pass "S08: success message is suppressed when validation fails"
else
  fail_test "S08: success message should not appear when validation fails"
fi
cleanup "$s08_dir"

# ------------------------------------------------------------------
# S09: exits non-zero when docs file contains disallowed 'brew install'
# ------------------------------------------------------------------
s09_dir="$(setup_temp_repo)"
valid_readme > "$s09_dir/README.md"
{ valid_setup_doc; printf '\nbrew install node\n'; } \
  > "$s09_dir/docs/iphone-local-dev-setup.md"
assert_exit_nonzero \
  "S09: exits non-zero when docs contain disallowed 'brew install'" \
  run_setup "$s09_dir"
cleanup "$s09_dir"

# ------------------------------------------------------------------
# S10: repository path in output matches the temp dir's resolved path
# ------------------------------------------------------------------
s10_dir="$(setup_temp_repo)"
valid_readme > "$s10_dir/README.md"
valid_setup_doc > "$s10_dir/docs/iphone-local-dev-setup.md"
# Resolve symlinks to compare accurately
resolved_dir="$(cd "$s10_dir" && pwd -P)"
stdout_out="$(bash "$s10_dir/scripts/codex_cloud_setup.sh" 2>/dev/null)"
if echo "$stdout_out" | grep -qF "Repository: $resolved_dir"; then
  pass "S10: output includes correct resolved repository path"
else
  fail_test "S10: expected 'Repository: $resolved_dir' in output; got: $stdout_out"
fi
cleanup "$s10_dir"

# ------------------------------------------------------------------
# S11: regression – both scripts must be present in temp repo
#      (if validate script is missing, setup script fails)
# ------------------------------------------------------------------
s11_dir="$(setup_temp_repo)"
valid_readme > "$s11_dir/README.md"
valid_setup_doc > "$s11_dir/docs/iphone-local-dev-setup.md"
rm "$s11_dir/scripts/validate_iphone_control_plane.sh"
assert_exit_nonzero \
  "S11: regression – exits non-zero when validate script is absent" \
  run_setup "$s11_dir"
cleanup "$s11_dir"

# ------------------------------------------------------------------
# S12: boundary – empty README causes setup to fail
# ------------------------------------------------------------------
s12_dir="$(setup_temp_repo)"
printf '' > "$s12_dir/README.md"
valid_setup_doc > "$s12_dir/docs/iphone-local-dev-setup.md"
assert_exit_nonzero \
  "S12: boundary – exits non-zero with empty README.md" \
  run_setup "$s12_dir"
cleanup "$s12_dir"

# ------------------------------------------------------------------
# S13: exits non-zero when docs file contains disallowed 'docker run'
# ------------------------------------------------------------------
s13_dir="$(setup_temp_repo)"
valid_readme > "$s13_dir/README.md"
{ valid_setup_doc; printf '\ndocker run -it ubuntu bash\n'; } \
  > "$s13_dir/docs/iphone-local-dev-setup.md"
assert_exit_nonzero \
  "S13: exits non-zero when docs contain disallowed 'docker run'" \
  run_setup "$s13_dir"
cleanup "$s13_dir"

# ------------------------------------------------------------------
# S14: exits non-zero when docs file contains disallowed 'curl -fsSL'
# ------------------------------------------------------------------
s14_dir="$(setup_temp_repo)"
valid_readme > "$s14_dir/README.md"
{ valid_setup_doc; printf '\ncurl -fsSL https://example.com | sh\n'; } \
  > "$s14_dir/docs/iphone-local-dev-setup.md"
assert_exit_nonzero \
  "S14: exits non-zero when docs contain disallowed 'curl -fsSL'" \
  run_setup "$s14_dir"
cleanup "$s14_dir"

# ------------------------------------------------------------------
# S15: setup script propagates validate script stderr to caller's stderr
# ------------------------------------------------------------------
s15_dir="$(setup_temp_repo)"
# No README to trigger a validation failure with a stderr message
stderr_out="$(bash "$s15_dir/scripts/codex_cloud_setup.sh" 2>&1 >/dev/null)" || true
if echo "$stderr_out" | grep -qF "Validation failed:"; then
  pass "S15: setup script propagates validate script stderr"
else
  fail_test "S15: expected 'Validation failed:' on stderr; got: $stderr_out"
fi
cleanup "$s15_dir"

# ------------------------------------------------------------------
# S16: output ordering – banner line appears before repository line
# ------------------------------------------------------------------
s16_dir="$(setup_temp_repo)"
valid_readme > "$s16_dir/README.md"
valid_setup_doc > "$s16_dir/docs/iphone-local-dev-setup.md"
stdout_out="$(bash "$s16_dir/scripts/codex_cloud_setup.sh" 2>/dev/null)"
banner_line="$(echo "$stdout_out" | grep -n 'Codex cloud setup for upgraded-fiesta' | head -1 | cut -d: -f1)"
repo_line="$(echo "$stdout_out" | grep -n 'Repository:' | head -1 | cut -d: -f1)"
if [[ -n "$banner_line" && -n "$repo_line" && "$banner_line" -lt "$repo_line" ]]; then
  pass "S16: banner line appears before repository line in output"
else
  fail_test "S16: expected banner before repository line; banner=$banner_line repo=$repo_line"
fi
cleanup "$s16_dir"

# ------------------------------------------------------------------
# S17: final success message appears after validation banner in output
# ------------------------------------------------------------------
s17_dir="$(setup_temp_repo)"
valid_readme > "$s17_dir/README.md"
valid_setup_doc > "$s17_dir/docs/iphone-local-dev-setup.md"
stdout_out="$(bash "$s17_dir/scripts/codex_cloud_setup.sh" 2>/dev/null)"
validate_banner_line="$(echo "$stdout_out" | grep -n 'Static iPhone control-plane validation passed.' | head -1 | cut -d: -f1)"
final_msg_line="$(echo "$stdout_out" | grep -n 'No dependency installation required.' | head -1 | cut -d: -f1)"
if [[ -n "$validate_banner_line" && -n "$final_msg_line" && "$validate_banner_line" -lt "$final_msg_line" ]]; then
  pass "S17: validate success banner appears before final success message"
else
  fail_test "S17: expected validate banner before final message; validate=$validate_banner_line final=$final_msg_line"
fi
cleanup "$s17_dir"

# ------------------------------------------------------------------
# S18: validate script is not executable if chmod is absent — setup
#      still fails gracefully via bash invocation (regression guard)
#      Verify: setup script invokes validate with 'bash', not as exec.
# ------------------------------------------------------------------
s18_dir="$(setup_temp_repo)"
valid_readme > "$s18_dir/README.md"
valid_setup_doc > "$s18_dir/docs/iphone-local-dev-setup.md"
chmod -x "$s18_dir/scripts/validate_iphone_control_plane.sh"
# codex_cloud_setup.sh calls "scripts/validate_iphone_control_plane.sh" directly (not bash)
# so if it's not executable, it should fail
assert_exit_nonzero \
  "S18: regression – exits non-zero when validate script is not executable" \
  run_setup "$s18_dir"
cleanup "$s18_dir"

# ------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------
echo ""
echo "Results: $PASS passed, $FAIL failed"
for err in "${ERRORS[@]}"; do
  echo "  $err"
done

[[ $FAIL -eq 0 ]] || exit 1