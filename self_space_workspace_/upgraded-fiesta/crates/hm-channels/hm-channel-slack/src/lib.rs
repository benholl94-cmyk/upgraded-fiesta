pub fn channel_name() -> &'static str {
    "slack"
}

/// Loads this channel's bot token from `HM_SLACK_BOT_TOKEN`.
pub fn bot_token() -> anyhow::Result<String> {
    hm_auth::load_bot_token(channel_name())
}
