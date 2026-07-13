package auth

// User is an authenticated Telegram user stored in JWT.
type User struct {
	TelegramID  int64
	DisplayName string
}

// TelegramUser is returned from Telegram OIDC token exchange.
type TelegramUser struct {
	TelegramID  int64
	DisplayName string
	Username    string
}
