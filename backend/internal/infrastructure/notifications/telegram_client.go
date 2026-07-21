package notifications

import (
	"bytes"
	"encoding/json"
	"log"
	"net/http"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/notifications"
)

// TelegramClient sends messages via Telegram Bot API.
type TelegramClient struct {
	botToken       string
	fallbackChatID int64
}

func NewTelegramClient(botToken string, fallbackChatID int64) *TelegramClient {
	return &TelegramClient{botToken: botToken, fallbackChatID: fallbackChatID}
}

func (t *TelegramClient) Configured() bool {
	return t.botToken != ""
}

// SendMessage sends to the legacy fallback chat id (if configured).
func (t *TelegramClient) SendMessage(text string) bool {
	if t.fallbackChatID == 0 {
		log.Println("Telegram fallback chat id is not configured")
		return false
	}
	return t.SendToChat(t.fallbackChatID, text)
}

// SendToChat sends a message to a specific Telegram chat id.
func (t *TelegramClient) SendToChat(chatID int64, text string) bool {
	if !t.Configured() || chatID == 0 {
		log.Println("Telegram notifier is not configured")
		return false
	}
	body, _ := json.Marshal(map[string]any{
		"chat_id":                  chatID,
		"text":                     text,
		"disable_web_page_preview": true,
	})
	url := "https://api.telegram.org/bot" + t.botToken + "/sendMessage"
	resp, err := http.Post(url, "application/json", bytes.NewReader(body))
	if err != nil {
		log.Printf("Telegram send failed: %v", err)
		return false
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		log.Printf("Telegram send failed: %s", resp.Status)
		return false
	}
	return true
}

var _ notifications.TelegramNotifier = (*TelegramClient)(nil)

var _ = time.Second
