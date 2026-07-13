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
	botToken string
	chatID   int64
}

func NewTelegramClient(botToken string, chatID int64) *TelegramClient {
	return &TelegramClient{botToken: botToken, chatID: chatID}
}

func (t *TelegramClient) Configured() bool {
	return t.botToken != "" && t.chatID != 0
}

func (t *TelegramClient) SendMessage(text string) bool {
	if !t.Configured() {
		log.Println("Telegram notifier is not configured")
		return false
	}
	body, _ := json.Marshal(map[string]any{
		"chat_id":                  t.chatID,
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

// noop for compile-time check of http client timeout usage
var _ = time.Second
