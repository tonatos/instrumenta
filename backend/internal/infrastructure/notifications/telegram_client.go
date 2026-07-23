package notifications

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"strconv"
	"time"

	"github.com/tonatos/instrumenta/backend/internal/domain/notifications"
)

// TelegramClient sends messages and receives updates via Telegram Bot API.
type TelegramClient struct {
	botToken   string
	httpClient *http.Client
	apiBase    string // override for tests
}

func NewTelegramClient(botToken string) *TelegramClient {
	return &TelegramClient{
		botToken: botToken,
		httpClient: &http.Client{
			Timeout: 45 * time.Second,
		},
	}
}

// SetAPIBaseForTest overrides api.telegram.org (unit tests only).
func (t *TelegramClient) SetAPIBaseForTest(base string) {
	t.apiBase = base
}

func (t *TelegramClient) Configured() bool {
	return t.botToken != ""
}

func (t *TelegramClient) baseURL() string {
	if t.apiBase != "" {
		return t.apiBase
	}
	return "https://api.telegram.org/bot" + t.botToken
}

// SendToChat sends a message to a specific Telegram chat id (private chat = user id).
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
	resp, err := t.httpClient.Post(t.baseURL()+"/sendMessage", "application/json", bytes.NewReader(body))
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

// BotUser is a subset of Telegram User from getMe.
type BotUser struct {
	ID       int64  `json:"id"`
	IsBot    bool   `json:"is_bot"`
	Username string `json:"username"`
}

type apiResponse[T any] struct {
	OK          bool   `json:"ok"`
	Result      T      `json:"result"`
	Description string `json:"description"`
}

// GetMe returns bot identity (username for deep links).
func (t *TelegramClient) GetMe(ctx context.Context) (BotUser, error) {
	var out apiResponse[BotUser]
	if err := t.getJSON(ctx, "/getMe", nil, &out); err != nil {
		return BotUser{}, err
	}
	if !out.OK {
		return BotUser{}, fmt.Errorf("telegram getMe: %s", out.Description)
	}
	return out.Result, nil
}

// Update is a subset of Telegram Update used by the bot inbox.
type Update struct {
	UpdateID      int64          `json:"update_id"`
	Message       *IncomingMsg   `json:"message"`
	MyChatMember  *ChatMemberEvt `json:"my_chat_member"`
}

type IncomingMsg struct {
	Text string    `json:"text"`
	Chat Chat      `json:"chat"`
	From *MsgFrom  `json:"from"`
}

type Chat struct {
	ID   int64  `json:"id"`
	Type string `json:"type"`
}

type MsgFrom struct {
	ID        int64  `json:"id"`
	FirstName string `json:"first_name"`
	Username  string `json:"username"`
}

type ChatMemberEvt struct {
	Chat          Chat           `json:"chat"`
	From          MsgFrom        `json:"from"`
	NewChatMember chatMemberInfo `json:"new_chat_member"`
}

type chatMemberInfo struct {
	Status string `json:"status"`
}

// GetUpdates long-polls Bot API (timeout seconds).
func (t *TelegramClient) GetUpdates(ctx context.Context, offset int64, timeoutSec int) ([]Update, error) {
	q := url.Values{}
	if offset > 0 {
		q.Set("offset", strconv.FormatInt(offset, 10))
	}
	if timeoutSec > 0 {
		q.Set("timeout", strconv.Itoa(timeoutSec))
	}
	q.Set("allowed_updates", `["message","my_chat_member"]`)
	var out apiResponse[[]Update]
	if err := t.getJSON(ctx, "/getUpdates", q, &out); err != nil {
		return nil, err
	}
	if !out.OK {
		return nil, fmt.Errorf("telegram getUpdates: %s", out.Description)
	}
	return out.Result, nil
}

func (t *TelegramClient) getJSON(ctx context.Context, path string, q url.Values, dest any) error {
	u := t.baseURL() + path
	if len(q) > 0 {
		u += "?" + q.Encode()
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return err
	}
	resp, err := t.httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return err
	}
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("telegram %s: %s", path, resp.Status)
	}
	return json.Unmarshal(body, dest)
}

var _ notifications.TelegramNotifier = (*TelegramClient)(nil)
