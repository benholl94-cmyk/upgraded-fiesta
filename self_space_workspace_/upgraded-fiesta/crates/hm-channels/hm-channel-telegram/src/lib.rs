pub fn channel_name() -> &'static str {
    "telegram"
}

/// Loads this channel's bot token from `HM_TELEGRAM_BOT_TOKEN`.
pub fn bot_token() -> anyhow::Result<String> {
    hm_auth::load_bot_token(channel_name())
}
