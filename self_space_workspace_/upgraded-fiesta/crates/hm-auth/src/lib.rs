use std::env;

pub const NAME: &str = "auth";

/// Env var holding the gateway owner's bearer token (see [`load_owner_token`]).
pub const OWNER_TOKEN_VAR: &str = "HM_OWNER_TOKEN";

/// Explicit opt-out for running the gateway with no owner authentication at
/// all. Requires "true" exactly -- never inferred from an empty/missing
/// [`OWNER_TOKEN_VAR`], so a deployment can't end up open by accident.
pub const ALLOW_NO_AUTH_VAR: &str = "HM_GATEWAY_ALLOW_NO_AUTH";

fn load_and_validate(var_name: &str) -> anyhow::Result<String> {
    let token = env::var(var_name).map_err(|_| anyhow::anyhow!("{var_name} is not set"))?;
    let trimmed = token.trim();
    if trimmed.is_empty() {
        anyhow::bail!("{var_name} is set but empty");
    }
    if trimmed.chars().any(char::is_whitespace) {
        anyhow::bail!("{var_name} contains whitespace -- check for a copy-paste error");
    }
    Ok(trimmed.to_string())
}

/// Loads and validates a bot token for `channel` from `HM_<CHANNEL>_BOT_TOKEN`.
/// Never commit real tokens -- set them as an env var / platform secret only.
/// Returns a clear error (never the token itself) when the variable is
/// missing, empty, or contains whitespace, which is almost always a
/// copy-paste mistake.
pub fn load_bot_token(channel: &str) -> anyhow::Result<String> {
    load_and_validate(&format!("HM_{}_BOT_TOKEN", channel.to_ascii_uppercase()))
}

/// Loads and validates the gateway owner's bearer token from
/// [`OWNER_TOKEN_VAR`]. Same validation rules as [`load_bot_token`].
pub fn load_owner_token() -> anyhow::Result<String> {
    load_and_validate(OWNER_TOKEN_VAR)
}

/// Constant-time equality check for two tokens, so a wrong guess can't be
/// narrowed down by measuring how long the comparison took. Still compares
/// lengths first (this alone leaks nothing secret -- token length isn't the
/// secret part), then every byte of the shorter buffer regardless of an
/// early mismatch.
pub fn tokens_match(provided: &str, expected: &str) -> bool {
    if provided.len() != expected.len() {
        return false;
    }
    let mut diff: u8 = 0;
    for (a, b) in provided.bytes().zip(expected.bytes()) {
        diff |= a ^ b;
    }
    diff == 0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn missing_var_errors() {
        env::remove_var("HM_TESTCHAN_MISSING_BOT_TOKEN");
        assert!(load_bot_token("testchan_missing").is_err());
    }

    #[test]
    fn empty_var_errors() {
        env::set_var("HM_TESTCHAN_EMPTY_BOT_TOKEN", "   ");
        assert!(load_bot_token("testchan_empty").is_err());
        env::remove_var("HM_TESTCHAN_EMPTY_BOT_TOKEN");
    }

    #[test]
    fn whitespace_inside_token_errors() {
        env::set_var("HM_TESTCHAN_WS_BOT_TOKEN", "abc 123");
        assert!(load_bot_token("testchan_ws").is_err());
        env::remove_var("HM_TESTCHAN_WS_BOT_TOKEN");
    }

    #[test]
    fn valid_token_ok() {
        env::set_var("HM_TESTCHAN_OK_BOT_TOKEN", "abc123");
        assert_eq!(load_bot_token("testchan_ok").unwrap(), "abc123");
        env::remove_var("HM_TESTCHAN_OK_BOT_TOKEN");
    }

    // Both assertions share the same process-global env var, so they must run
    // sequentially within one test function rather than as separate #[test]s
    // (which the harness would otherwise run concurrently and race).
    #[test]
    fn owner_token_missing_then_valid() {
        env::remove_var(OWNER_TOKEN_VAR);
        assert!(load_owner_token().is_err());

        env::set_var(OWNER_TOKEN_VAR, "owner-secret-123");
        assert_eq!(load_owner_token().unwrap(), "owner-secret-123");
        env::remove_var(OWNER_TOKEN_VAR);
    }

    #[test]
    fn tokens_match_same_length_same_bytes() {
        assert!(tokens_match("same-secret", "same-secret"));
    }

    #[test]
    fn tokens_match_rejects_wrong_value() {
        assert!(!tokens_match("guess", "secret-actual"));
    }

    #[test]
    fn tokens_match_rejects_different_length() {
        assert!(!tokens_match("short", "much-longer-secret"));
    }

    #[test]
    fn tokens_match_rejects_empty_against_nonempty() {
        assert!(!tokens_match("", "secret"));
    }
}
