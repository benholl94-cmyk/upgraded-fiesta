pub fn channel_name() -> &'static str {
    "discord"
}

/// Loads this channel's bot token from `HM_DISCORD_BOT_TOKEN`.
pub fn bot_token() -> anyhow::Result<String> {
    hm_auth::load_bot_token(channel_name())
}
