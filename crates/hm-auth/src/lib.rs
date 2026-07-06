use std::env;

pub const NAME: &str = "auth";

/// Loads and validates a bot token for `channel` from `HM_<CHANNEL>_BOT_TOKEN`.
/// Never commit real tokens -- set them as an env var / platform secret only.
/// Returns a clear error (never the token itself) when the variable is
/// missing, empty, or contains whitespace, which is almost always a
/// copy-paste mistake.
pub fn load_bot_token(channel: &str) -> anyhow::Result<String> {
    let var_name = format!("HM_{}_BOT_TOKEN", channel.to_ascii_uppercase());
    let token = env::var(&var_name).map_err(|_| anyhow::anyhow!("{var_name} is not set"))?;
    let trimmed = token.trim();
    if trimmed.is_empty() {
        anyhow::bail!("{var_name} is set but empty");
    }
    if trimmed.chars().any(char::is_whitespace) {
        anyhow::bail!("{var_name} contains whitespace -- check for a copy-paste error");
    }
    Ok(trimmed.to_string())
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
}
