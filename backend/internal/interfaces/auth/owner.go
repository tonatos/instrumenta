package auth

import "context"

type ownerKey struct{}

// WithOwnerTelegramID attaches the acting tenant id to ctx (JWT user or DevUser).
func WithOwnerTelegramID(ctx context.Context, telegramID int64) context.Context {
	return context.WithValue(ctx, ownerKey{}, telegramID)
}

// OwnerTelegramID returns the acting tenant id from ctx.
func OwnerTelegramID(ctx context.Context) (int64, bool) {
	id, ok := ctx.Value(ownerKey{}).(int64)
	return id, ok && id != 0
}
