package notifications

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	appbilling "github.com/tonatos/instrumenta/backend/internal/application/billing"
	"github.com/tonatos/instrumenta/backend/internal/domain/billing"
	infranotify "github.com/tonatos/instrumenta/backend/internal/infrastructure/notifications"
	"github.com/tonatos/instrumenta/backend/internal/infrastructure/persistence"
	"github.com/tonatos/instrumenta/backend/internal/infrastructure/yookassa"
)

type memBillingStore struct {
	mu   sync.Mutex
	subs map[int64]*billing.Subscription
}

func (m *memBillingStore) ListCurrentPlanVersions(context.Context) ([]billing.PlanVersion, error) {
	return nil, nil
}
func (m *memBillingStore) GetPlanVersionByID(context.Context, string) (*billing.PlanVersion, error) {
	return nil, nil
}
func (m *memBillingStore) GetCurrentPlanByPeriod(context.Context, billing.Period) (*billing.PlanVersion, error) {
	return nil, nil
}
func (m *memBillingStore) GetSubscriptionByOwner(_ context.Context, owner int64) (*billing.Subscription, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.subs[owner], nil
}
func (m *memBillingStore) SaveSubscription(context.Context, billing.Subscription) (billing.Subscription, error) {
	return billing.Subscription{}, nil
}
func (m *memBillingStore) ListSubscriptionsDueForRenew(context.Context, time.Time) ([]billing.Subscription, error) {
	return nil, nil
}
func (m *memBillingStore) CreatePayment(context.Context, billing.Payment) (billing.Payment, error) {
	return billing.Payment{}, nil
}
func (m *memBillingStore) UpdatePayment(context.Context, billing.Payment) error { return nil }
func (m *memBillingStore) GetPaymentByID(context.Context, string) (*billing.Payment, error) {
	return nil, nil
}
func (m *memBillingStore) GetPaymentByYooKassaID(context.Context, string) (*billing.Payment, error) {
	return nil, nil
}
func (m *memBillingStore) GetPaymentByIdempotencyKey(context.Context, string) (*billing.Payment, error) {
	return nil, nil
}
func (m *memBillingStore) AddLedgerEntry(context.Context, billing.LedgerEntry) (billing.LedgerEntry, error) {
	return billing.LedgerEntry{}, nil
}
func (m *memBillingStore) ListLedger(context.Context, int64, int) ([]billing.LedgerEntry, error) {
	return nil, nil
}

func openNotifyTestDB(t *testing.T) (*persistence.DB, *persistence.UserRepository) {
	t.Helper()
	dir := t.TempDir()
	db, err := persistence.Open("sqlite://" + filepath.Join(dir, "t.db"))
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	t.Cleanup(func() { _ = db.Close() })
	if err := persistence.ApplyMigrations(db.DB, "sqlite", ""); err != nil {
		t.Fatalf("migrate: %v", err)
	}
	if err := persistence.EnsureUsersNotifySchema(context.Background(), db.DB); err != nil {
		t.Fatalf("schema: %v", err)
	}
	return db, persistence.NewUserRepository(db)
}

func TestSubscriptionTelegramGate(t *testing.T) {
	_, users := openNotifyTestDB(t)
	store := &memBillingStore{subs: map[int64]*billing.Subscription{}}
	billingSvc := appbilling.NewService(store, yookassa.DisabledGateway{}, []int64{7}, "")
	gate := &SubscriptionTelegramGate{Users: users, Billing: billingSvc}
	ctx := context.Background()

	if gate.CanReceiveTelegram(ctx, 7) {
		t.Fatal("complimentary without /start must be denied")
	}
	_ = users.MarkBotConnected(ctx, 7, "Comp", time.Now().UTC())
	if !gate.CanReceiveTelegram(ctx, 7) {
		t.Fatal("complimentary + connected must be allowed")
	}

	now := time.Now().UTC()
	store.subs[8] = &billing.Subscription{
		OwnerTelegramID: 8, Status: billing.StatusActive,
		Features: billing.PaidFeaturesV1(),
		CurrentPeriodStart: now.Add(-time.Hour), CurrentPeriodEnd: now.Add(24 * time.Hour),
	}
	_ = users.MarkBotConnected(ctx, 8, "Sub", now)
	if !gate.CanReceiveTelegram(ctx, 8) {
		t.Fatal("subscriber + connected must be allowed")
	}

	_ = users.MarkBotConnected(ctx, 9, "NoSub", now)
	if gate.CanReceiveTelegram(ctx, 9) {
		t.Fatal("connected without subscription must be denied")
	}
}

func TestBotInbox_StartRequiresSubscription(t *testing.T) {
	_, users := openNotifyTestDB(t)
	store := &memBillingStore{subs: map[int64]*billing.Subscription{}}
	billingSvc := appbilling.NewService(store, yookassa.DisabledGateway{}, nil, "")

	var sent []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.HasSuffix(r.URL.Path, "/sendMessage"):
			var body map[string]any
			_ = json.NewDecoder(r.Body).Decode(&body)
			sent = append(sent, body["text"].(string))
			_ = json.NewEncoder(w).Encode(map[string]any{"ok": true, "result": map[string]any{}})
		default:
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(srv.Close)

	tg := infranotify.NewTelegramClient("test-token", "")
	tg.SetAPIBaseForTest(srv.URL)
	inbox := NewBotInbox(tg, users, billingSvc, nil, 0)

	inbox.handleStart(context.Background(), 11, "NoSub")
	connected, _ := users.IsBotConnected(context.Background(), 11)
	if connected {
		t.Fatal("must not connect without subscription")
	}
	if len(sent) != 1 || !strings.Contains(sent[0], "подписк") {
		t.Fatalf("expected subscription message, got %#v", sent)
	}

	now := time.Now().UTC()
	store.subs[11] = &billing.Subscription{
		OwnerTelegramID: 11, Status: billing.StatusActive,
		Features: billing.PaidFeaturesV1(),
		CurrentPeriodStart: now.Add(-time.Hour), CurrentPeriodEnd: now.Add(24 * time.Hour),
	}
	inbox.handleStart(context.Background(), 11, "Sub")
	connected, _ = users.IsBotConnected(context.Background(), 11)
	if !connected {
		t.Fatal("expected connected after /start with subscription")
	}
}

func TestBotInbox_SupportRelay(t *testing.T) {
	_, users := openNotifyTestDB(t)
	billingSvc := appbilling.NewService(&memBillingStore{subs: map[int64]*billing.Subscription{}}, yookassa.DisabledGateway{}, nil, "")

	const supportChat int64 = -1001
	type sentMsg struct {
		chatID int64
		text   string
	}
	var sent []sentMsg
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.HasSuffix(r.URL.Path, "/sendMessage"):
			var body map[string]any
			_ = json.NewDecoder(r.Body).Decode(&body)
			chatID, _ := body["chat_id"].(float64)
			sent = append(sent, sentMsg{chatID: int64(chatID), text: body["text"].(string)})
			_ = json.NewEncoder(w).Encode(map[string]any{"ok": true, "result": map[string]any{}})
		default:
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(srv.Close)

	tg := infranotify.NewTelegramClient("test-token", "")
	tg.SetAPIBaseForTest(srv.URL)
	inbox := NewBotInbox(tg, users, billingSvc, nil, supportChat)

	inbox.handleUpdate(context.Background(), infranotify.Update{
		Message: &infranotify.IncomingMsg{
			Text: "Помогите с оплатой",
			Chat: infranotify.Chat{ID: 42, Type: "private"},
			From: &infranotify.MsgFrom{ID: 42, Username: "bob"},
		},
	})
	if len(sent) != 2 {
		t.Fatalf("want relay+ack, got %#v", sent)
	}
	if sent[0].chatID != supportChat || !strings.Contains(sent[0].text, "Support tg_id=42") {
		t.Fatalf("relay to group: %#v", sent[0])
	}
	if sent[1].chatID != 42 || !strings.Contains(sent[1].text, "отправлено") {
		t.Fatalf("ack to user: %#v", sent[1])
	}

	relayed := sent[0].text
	sent = nil
	inbox.handleUpdate(context.Background(), infranotify.Update{
		Message: &infranotify.IncomingMsg{
			Text: "Проверьте ЮKassa",
			Chat: infranotify.Chat{ID: supportChat, Type: "group"},
			From: &infranotify.MsgFrom{ID: 99, FirstName: "Op"},
			ReplyToMessage: &infranotify.IncomingMsg{
				Text: relayed,
				Chat: infranotify.Chat{ID: supportChat, Type: "group"},
			},
		},
	})
	if len(sent) != 1 || sent[0].chatID != 42 || sent[0].text != "Проверьте ЮKassa" {
		t.Fatalf("reply to user: %#v", sent)
	}
}

func TestBotInbox_SupportDisabledAndCommands(t *testing.T) {
	_, users := openNotifyTestDB(t)
	billingSvc := appbilling.NewService(&memBillingStore{subs: map[int64]*billing.Subscription{}}, yookassa.DisabledGateway{}, nil, "")

	var sent []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.HasSuffix(r.URL.Path, "/sendMessage"):
			var body map[string]any
			_ = json.NewDecoder(r.Body).Decode(&body)
			sent = append(sent, body["text"].(string))
			_ = json.NewEncoder(w).Encode(map[string]any{"ok": true, "result": map[string]any{}})
		default:
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(srv.Close)

	tg := infranotify.NewTelegramClient("test-token", "")
	tg.SetAPIBaseForTest(srv.URL)
	inbox := NewBotInbox(tg, users, billingSvc, nil, 0)

	inbox.handleUpdate(context.Background(), infranotify.Update{
		Message: &infranotify.IncomingMsg{
			Text: "hello support",
			Chat: infranotify.Chat{ID: 7, Type: "private"},
			From: &infranotify.MsgFrom{ID: 7},
		},
	})
	if len(sent) != 1 || !strings.Contains(sent[0], "недоступна") {
		t.Fatalf("disabled support: %#v", sent)
	}

	sent = nil
	inbox.handleUpdate(context.Background(), infranotify.Update{
		Message: &infranotify.IncomingMsg{
			Text: "/help",
			Chat: infranotify.Chat{ID: 7, Type: "private"},
			From: &infranotify.MsgFrom{ID: 7},
		},
	})
	if len(sent) != 1 || !strings.Contains(sent[0], "/support") {
		t.Fatalf("help: %#v", sent)
	}

	sent = nil
	inbox.handleUpdate(context.Background(), infranotify.Update{
		Message: &infranotify.IncomingMsg{
			Text: "/start support",
			Chat: infranotify.Chat{ID: 7, Type: "private"},
			From: &infranotify.MsgFrom{ID: 7},
		},
	})
	connected, _ := users.IsBotConnected(context.Background(), 7)
	if connected {
		t.Fatal("/start support must not connect notifications")
	}
	if len(sent) != 1 || !strings.Contains(sent[0], "поддержк") {
		t.Fatalf("start support intro: %#v", sent)
	}
}
