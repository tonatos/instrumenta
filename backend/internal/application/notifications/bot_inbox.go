package notifications

import (
	"context"
	"log/slog"
	"strings"
	"time"

	appbilling "github.com/tonatos/bond-monitor/backend/internal/application/billing"
	domain "github.com/tonatos/bond-monitor/backend/internal/domain/notifications"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/notifications"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/persistence"
)

// BotInbox polls getUpdates and handles /start, /stop, and bot block.
type BotInbox struct {
	telegram *notifications.TelegramClient
	users    *persistence.UserRepository
	billing  *appbilling.Service
	logger   *slog.Logger
	offset   int64
}

func NewBotInbox(
	telegram *notifications.TelegramClient,
	users *persistence.UserRepository,
	billing *appbilling.Service,
	logger *slog.Logger,
) *BotInbox {
	if logger == nil {
		logger = slog.Default()
	}
	return &BotInbox{telegram: telegram, users: users, billing: billing, logger: logger}
}

// Run long-polls until ctx is cancelled. Safe to call once in a goroutine.
func (b *BotInbox) Run(ctx context.Context) {
	if b == nil || b.telegram == nil || !b.telegram.Configured() {
		return
	}
	for {
		if ctx.Err() != nil {
			return
		}
		updates, err := b.telegram.GetUpdates(ctx, b.offset, 25)
		if err != nil {
			if ctx.Err() != nil {
				return
			}
			b.logger.Warn("telegram getUpdates failed", "error", err)
			select {
			case <-ctx.Done():
				return
			case <-time.After(3 * time.Second):
			}
			continue
		}
		for _, u := range updates {
			b.offset = u.UpdateID + 1
			b.handleUpdate(ctx, u)
		}
	}
}

func (b *BotInbox) handleUpdate(ctx context.Context, u notifications.Update) {
	if u.MyChatMember != nil {
		b.handleChatMember(ctx, u.MyChatMember)
		return
	}
	if u.Message == nil || u.Message.Chat.Type != "private" {
		return
	}
	cmd, _ := domain.ParseBotCommand(u.Message.Text)
	chatID := u.Message.Chat.ID
	name := ""
	if u.Message.From != nil {
		name = strings.TrimSpace(u.Message.From.FirstName)
		if u.Message.From.ID != 0 {
			chatID = u.Message.From.ID
		}
	}
	switch cmd {
	case "/start":
		b.handleStart(ctx, chatID, name)
	case "/stop":
		b.handleStop(ctx, chatID)
	case "/help":
		_ = b.telegram.SendToChat(chatID, helpText())
	}
}

func (b *BotInbox) handleStart(ctx context.Context, telegramID int64, displayName string) {
	if b.billing != nil {
		status, err := b.billing.GetStatus(ctx, telegramID)
		if err != nil || !(status.HasActiveAccess || status.Complimentary) {
			_ = b.telegram.SendToChat(telegramID, needSubscriptionText())
			return
		}
	}
	if err := b.users.MarkBotConnected(ctx, telegramID, displayName, time.Now().UTC()); err != nil {
		b.logger.Warn("mark bot connected failed", "telegram_id", telegramID, "error", err)
		_ = b.telegram.SendToChat(telegramID, "Не удалось сохранить подключение. Попробуйте ещё раз.")
		return
	}
	_ = b.telegram.SendToChat(telegramID, connectedText())
}

func (b *BotInbox) handleStop(ctx context.Context, telegramID int64) {
	_ = b.users.MarkBotDisconnected(ctx, telegramID)
	_ = b.telegram.SendToChat(telegramID, "Уведомления отключены. Чтобы снова получать их — отправьте /start.")
}

func (b *BotInbox) handleChatMember(ctx context.Context, evt *notifications.ChatMemberEvt) {
	if evt == nil || evt.Chat.Type != "private" {
		return
	}
	status := evt.NewChatMember.Status
	if status == "kicked" || status == "left" {
		_ = b.users.MarkBotDisconnected(ctx, evt.Chat.ID)
	}
}

func needSubscriptionText() string {
	return "Чтобы подключить уведомления Instrumenta, нужна активная подписка Pro (или complimentary-доступ).\n\n" +
		"Оформите тариф в приложении: Личный кабинет → Тариф, затем снова нажмите Start / отправьте /start."
}

func connectedText() string {
	return "Готово. Бот подключён: будем писать о пут‑офертах и критических эскалациях риска по вашим trading-портфелям.\n\n" +
		"Отключить: /stop"
}

func helpText() string {
	return "Команды:\n/start — включить уведомления (нужна подписка Pro)\n/stop — отключить уведомления\n/help — эта справка"
}
