package notifications

import (
	"strings"
)

// ParseBotCommand extracts "/start" from "/start@BotName args".
func ParseBotCommand(text string) (cmd string, args string) {
	text = strings.TrimSpace(text)
	if text == "" {
		return "", ""
	}
	parts := strings.SplitN(text, " ", 2)
	raw := parts[0]
	if len(parts) == 2 {
		args = strings.TrimSpace(parts[1])
	}
	if i := strings.IndexByte(raw, '@'); i >= 0 {
		raw = raw[:i]
	}
	return strings.ToLower(raw), args
}

// BotDeepLink builds https://t.me/<username> for the Start button.
func BotDeepLink(username string) string {
	username = strings.TrimPrefix(strings.TrimSpace(username), "@")
	if username == "" {
		return ""
	}
	return "https://t.me/" + username
}
