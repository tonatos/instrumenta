package notifications

import (
	"context"
	"log/slog"
	"strings"
	"sync"
	"time"

	appbilling "github.com/tonatos/instrumenta/backend/internal/application/billing"
	domain "github.com/tonatos/instrumenta/backend/internal/domain/notifications"
	"github.com/tonatos/instrumenta/backend/internal/infrastructure/notifications"
	"github.com/tonatos/instrumenta/backend/internal/infrastructure/persistence"
)

const supportRateLimitPerHour = 10

// BotInbox polls getUpdates and handles /start, /stop, support relay, and bot block.
type BotInbox struct {
	telegram       *notifications.TelegramClient
	users          *persistence.UserRepository
	billing        *appbilling.Service
	logger         *slog.Logger
	supportChatID  int64
	offset         int64
	rateMu         sync.Mutex
	rateBuckets    map[int64][]time.Time
}

func NewBotInbox(
	telegram *notifications.TelegramClient,
	users *persistence.UserRepository,
	billing *appbilling.Service,
	logger *slog.Logger,
	supportChatID int64,
) *BotInbox {
	if logger == nil {
		logger = slog.Default()
	}
	return &BotInbox{
		telegram:      telegram,
		users:         users,
		billing:       billing,
		logger:        logger,
		supportChatID: supportChatID,
		rateBuckets:   make(map[int64][]time.Time),
	}
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
	if u.Message == nil {
		return
	}
	msg := u.Message
	if b.supportChatID != 0 && msg.Chat.ID == b.supportChatID {
		b.handleSupportReply(msg)
		return
	}
	if msg.Chat.Type != "private" {
		return
	}
	cmd, args := domain.ParseBotCommand(msg.Text)
	chatID := msg.Chat.ID
	name := ""
	username := ""
	if msg.From != nil {
		name = strings.TrimSpace(msg.From.FirstName)
		username = strings.TrimSpace(msg.From.Username)
		if msg.From.ID != 0 {
			chatID = msg.From.ID
		}
	}
	switch cmd {
	case "/start":
		if strings.EqualFold(strings.TrimSpace(args), "support") {
			_ = b.telegram.SendToChat(chatID, supportIntroText())
			return
		}
		b.handleStart(ctx, chatID, name)
	case "/stop":
		b.handleStop(ctx, chatID)
	case "/help":
		_ = b.telegram.SendToChat(chatID, helpText())
	case "/support":
		_ = b.telegram.SendToChat(chatID, supportIntroText())
	default:
		b.handleSupportFromUser(ctx, chatID, username, msg.Text)
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

func (b *BotInbox) handleSupportFromUser(ctx context.Context, telegramID int64, username, text string) {
	text = strings.TrimSpace(text)
	if text == "" {
		_ = b.telegram.SendToChat(telegramID, "Пока принимаем только текст. Напишите сообщение — ответим здесь.")
		return
	}
	if b.supportChatID == 0 {
		_ = b.telegram.SendToChat(telegramID, "Поддержка временно недоступна. Попробуйте позже или напишите на почту из оферты.")
		return
	}
	if !b.allowSupportMessage(telegramID) {
		_ = b.telegram.SendToChat(telegramID, "Слишком много сообщений. Подождите немного и напишите снова.")
		return
	}
	plan := "free"
	if b.billing != nil {
		if status, err := b.billing.GetStatus(ctx, telegramID); err == nil {
			if status.Complimentary {
				plan = "complimentary"
			} else if status.HasActiveAccess {
				plan = "Pro"
			}
		}
	}
	payload := domain.FormatSupportRelayMessage(telegramID, username, plan, text)
	if !b.telegram.SendToChat(b.supportChatID, payload) {
		_ = b.telegram.SendToChat(telegramID, "Не удалось отправить сообщение в поддержку. Попробуйте ещё раз.")
		return
	}
	_ = b.telegram.SendToChat(telegramID, "Сообщение отправлено в поддержку. Ответим в этом чате.")
}

func (b *BotInbox) handleSupportReply(msg *notifications.IncomingMsg) {
	if msg == nil || msg.ReplyToMessage == nil {
		return
	}
	text := strings.TrimSpace(msg.Text)
	if text == "" {
		return
	}
	userID, ok := domain.ParseSupportTgID(msg.ReplyToMessage.Text)
	if !ok {
		return
	}
	_ = b.telegram.SendToChat(userID, text)
}

func (b *BotInbox) allowSupportMessage(telegramID int64) bool {
	now := time.Now().UTC()
	cutoff := now.Add(-time.Hour)
	b.rateMu.Lock()
	defer b.rateMu.Unlock()
	prev := b.rateBuckets[telegramID]
	kept := prev[:0]
	for _, ts := range prev {
		if ts.After(cutoff) {
			kept = append(kept, ts)
		}
	}
	if len(kept) >= supportRateLimitPerHour {
		b.rateBuckets[telegramID] = kept
		return false
	}
	b.rateBuckets[telegramID] = append(kept, now)
	return true
}

func needSubscriptionText() string {
	return "Чтобы подключить уведомления Instrumenta, нужна активная подписка Pro (или complimentary-доступ).\n\n" +
		"Оформите тариф в приложении: Личный кабинет → Тариф, затем снова нажмите Start / отправьте /start.\n\n" +
		"Вопрос по оплате или сервису — /support (подписка не нужна)."
}

func connectedText() string {
	return "Готово. Бот подключён: будем писать о пут‑офертах и критических эскалациях риска по вашим trading-портфелям.\n\n" +
		"Отключить: /stop\nПоддержка: /support"
}

func supportIntroText() string {
	return "Напишите сообщение — передадим в поддержку и ответим в этом чате.\n\nПока принимаем только текст."
}

func helpText() string {
	return "Команды:\n" +
		"/start — включить уведомления (нужна подписка Pro)\n" +
		"/stop — отключить уведомления\n" +
		"/support — написать в поддержку\n" +
		"/help — эта справка"
}
