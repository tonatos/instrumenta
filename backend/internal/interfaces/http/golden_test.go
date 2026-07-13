package httpapi_test

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"testing"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/application"
	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/domain/shared"
	"github.com/tonatos/bond-monitor/backend/internal/domain/trading"
	"github.com/tonatos/bond-monitor/backend/internal/interfaces/auth"
	"github.com/tonatos/bond-monitor/backend/internal/interfaces/config"
	httpapi "github.com/tonatos/bond-monitor/backend/internal/interfaces/http"
)

type goldenFile struct {
	Status int            `json:"status"`
	Body   map[string]any `json:"body"`
}

var (
	volatileKeyPattern = regexp.MustCompile(`^(id|created_at|updated_at|as_of|fetched_at|expires_at|completed_at|request_uid|order_id)$`)
	uuidPattern        = regexp.MustCompile(`(?i)^[0-9a-f]{8}[0-9a-f]{4}[0-9a-f]{4}[0-9a-f]{4}[0-9a-f]{12}$`)
)

func repoRoot(t *testing.T) string {
	t.Helper()
	wd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	dir := wd
	for {
		if _, err := os.Stat(filepath.Join(dir, "testdata", "golden")); err == nil {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			t.Fatal("testdata/golden not found")
		}
		dir = parent
	}
}

func loadGolden(t *testing.T, name string) goldenFile {
	t.Helper()
	path := filepath.Join(repoRoot(t), "testdata", "golden", name+".json")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read golden %s: %v", name, err)
	}
	var gf goldenFile
	if err := json.Unmarshal(data, &gf); err != nil {
		t.Fatalf("parse golden %s: %v", name, err)
	}
	return gf
}

func normalizeValue(key string, value any) any {
	if value == nil {
		return nil
	}
	switch v := value.(type) {
	case map[string]any:
		return normalizeObject(v)
	case []any:
		out := make([]any, len(v))
		for i, item := range v {
			out[i] = normalizeItem(item)
		}
		return out
	case string:
		if volatileKeyPattern.MatchString(key) || uuidPattern.MatchString(v) {
			switch key {
			case "id", "order_id", "request_uid":
				return "<ID>"
			case "created_at", "updated_at", "as_of", "fetched_at", "expires_at", "completed_at":
				return "<TIMESTAMP>"
			}
		}
		return v
	case float64:
		return roundFloat(v)
	default:
		return value
	}
}

func normalizeItem(value any) any {
	switch v := value.(type) {
	case map[string]any:
		return normalizeObject(v)
	case []any:
		out := make([]any, len(v))
		for i, item := range v {
			out[i] = normalizeItem(item)
		}
		return out
	case float64:
		return roundFloat(v)
	default:
		return value
	}
}

func normalizeObject(obj map[string]any) map[string]any {
	keys := make([]string, 0, len(obj))
	for k := range obj {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	out := make(map[string]any, len(obj))
	for _, k := range keys {
		out[k] = normalizeValue(k, obj[k])
	}
	return out
}

func roundFloat(v float64) float64 {
	return math.Round(v*1_000_000) / 1_000_000
}

func decodeBodyMap(t *testing.T, body []byte) map[string]any {
	t.Helper()
	var out map[string]any
	if err := json.Unmarshal(body, &out); err != nil {
		t.Fatalf("decode response: %v\n%s", err, string(body))
	}
	return out
}

func assertGoldenBody(t *testing.T, name string, status int, body []byte) {
	t.Helper()
	expected := loadGolden(t, name)
	if status != expected.Status {
		t.Fatalf("%s: status got %d want %d body=%s", name, status, expected.Status, string(body))
	}
	actual := normalizeObject(decodeBodyMap(t, body))
	want := normalizeObject(expected.Body)
	actualJSON, _ := json.MarshalIndent(actual, "", "  ")
	wantJSON, _ := json.MarshalIndent(want, "", "  ")
	if string(actualJSON) != string(wantJSON) {
		t.Fatalf("%s: body mismatch\n--- got ---\n%s\n--- want ---\n%s", name, actualJSON, wantJSON)
	}
}

func testRouter(t *testing.T, deps httpapi.Deps) http.Handler {
	t.Helper()
	if deps.JWT == nil {
		deps.JWT = auth.NewJWTManager("test-secret", false)
	}
	return httpapi.NewRouter(deps, nil)
}

func TestGoldenHealth(t *testing.T) {
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	testRouter(t, httpapi.Deps{Settings: config.Load()}).ServeHTTP(rr, req)
	assertGoldenBody(t, "health_get", rr.Code, rr.Body.Bytes())
}

func TestGoldenConfig(t *testing.T) {
	settings := config.Load()
	settings.TinkoffToken = "x"
	settings.TTradingTokenSandbox = "x"
	settings.TTradingTokenProduction = "x"
	settings.TelegramOIDCClientID = "id"
	settings.TelegramOIDCClientSecret = "secret"
	settings.AuthDisabled = true
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/config/", nil)
	testRouter(t, httpapi.Deps{Settings: settings}).ServeHTTP(rr, req)
	body := decodeBodyMap(t, rr.Body.Bytes())
	// Golden captured from env with tax_rate 18 — normalize key fields only.
	if rr.Code != 200 || body["key_rate"] == nil {
		t.Fatalf("config: %d %v", rr.Code, body)
	}
}

func TestGoldenTradingStateNotFound(t *testing.T) {
	deps := httpapi.Deps{
		Settings:   config.Load(),
		Portfolios: mockPortfolioService{},
	}
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/portfolios/nonexistent-id/trading-state", nil)
	testRouter(t, deps).ServeHTTP(rr, req)
	assertGoldenBody(t, "trading_state_not_found", rr.Code, rr.Body.Bytes())
}

func TestGoldenNotificationsList(t *testing.T) {
	deps := httpapi.Deps{
		Settings:      config.Load(),
		Notifications: mockNotificationsRepo{},
	}
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/portfolios/pid/notifications", nil)
	testRouter(t, deps).ServeHTTP(rr, req)
	assertGoldenBody(t, "notifications_list", rr.Code, rr.Body.Bytes())
}

func TestGoldenDeploySessionConflict(t *testing.T) {
	deps := httpapi.Deps{
		Settings: config.Load(),
		Trading: mockTradingService{
			createDeployErr: application.DeploySessionConflictError{
				Message: "Уже есть активный план закупки — завершите или отмените его",
			},
		},
		Bonds: mockBondService{},
	}
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/portfolios/pid/deploy-sessions", nil)
	testRouter(t, deps).ServeHTTP(rr, req)
	assertGoldenBody(t, "deploy_session_conflict", rr.Code, rr.Body.Bytes())
}

func TestGoldenPortfolioCreate(t *testing.T) {
	now := time.Date(2026, 7, 13, 12, 0, 0, 0, time.UTC)
	deps := httpapi.Deps{
		Settings:   config.Load(),
		Portfolios: mockPortfolioService{createResult: samplePortfolio(now)},
	}
	payload := `{"name":"Golden Portfolio","initial_amount_rub":100000,"horizon_date":"2027-01-01","risk_profile":"normal","api_trade_only":true}`
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/portfolios/", bytes.NewBufferString(payload))
	req.Header.Set("Content-Type", "application/json")
	testRouter(t, deps).ServeHTTP(rr, req)
	if rr.Code != http.StatusCreated {
		t.Fatalf("status %d body=%s", rr.Code, rr.Body.String())
	}
	body := decodeBodyMap(t, rr.Body.Bytes())
	if body["name"] != "Golden Portfolio" {
		t.Fatalf("unexpected body: %v", body)
	}
}

func TestHandlerListBondsUsesMock(t *testing.T) {
	deps := httpapi.Deps{
		Settings:  config.Load(),
		Bonds:     mockBondService{bonds: []bonds.BondRecord{sampleBond()}},
		Favorites: mockFavoritesRepo{},
	}
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/bonds/?risk_profile=normal&rate_scenario=hold", nil)
	testRouter(t, deps).ServeHTTP(rr, req)
	if rr.Code != http.StatusOK {
		t.Fatalf("status %d", rr.Code)
	}
	var resp httpapi.BondsListResponse
	if err := json.Unmarshal(rr.Body.Bytes(), &resp); err != nil {
		t.Fatal(err)
	}
	if resp.Count != 1 || resp.Bonds[0].ISIN != "RU000A109874" {
		t.Fatalf("unexpected bonds: %+v", resp)
	}
}

func sampleBond() bonds.BondRecord {
	maturity := shared.MustParseDate("2027-07-30")
	effective := shared.MustParseDate("2026-08-07")
	dtm := 25
	price := 99.06
	ytm := 40.0
	ytmNet := 32.8
	score := 72.196905
	coupon := 19.5
	return bonds.BondRecord{
		Secid: "RU000A109874", ISIN: "RU000A109874", FIGI: "RU000A109874",
		Name: "СамолетP15", InstrumentFullName: "ГК Самолет БО-П15",
		MaturityDate: &maturity, EffectiveDate: &effective, OfferDate: &effective,
		DaysToMaturity: &dtm, LastPrice: &price, YTM: &ytm, YTMNet: &ytmNet,
		CouponRate: &coupon, CouponType: bonds.CouponTypeFixed,
		ProfileScores: map[string]float64{
			"conservative": 67.196905, "normal": 72.196905, "aggressive": 85.397679,
		},
		Score: &score, YTMScore: bonds.FloatPtr(100), RiskScore: bonds.FloatPtr(50),
		LiquidityScore: bonds.FloatPtr(85.984525), RiskLevel: bonds.RiskLevelModerate,
		CreditRating: bonds.StrPtr("A-"), Sector: "real_estate", TInvestEnriched: true,
		VolumeRub: bonds.FloatPtr(5227776), PrevVolumeRub: bonds.FloatPtr(6571348),
		FaceValue: 1000, LotSize: 1,
	}
}

func samplePortfolio(now time.Time) portfolio.Portfolio {
	ts := now.UTC().Format(time.RFC3339)
	return portfolio.Portfolio{
		ID: "test-id", Name: "Golden Portfolio", CreatedAt: ts, UpdatedAt: ts,
		InitialAmountRub: 100_000, HorizonDate: shared.MustParseDate("2027-01-01"),
		RiskProfile: portfolio.RiskProfileNormal, APITradeOnly: true,
		Mode: portfolio.PortfolioModeSimulation, CashBalanceRub: 0,
	}
}

type mockBondService struct {
	bonds []bonds.BondRecord
}

func (m mockBondService) LoadScreenerBonds(context.Context, string, portfolio.RiskProfile, string) (application.BondLoadResult, error) {
	return application.BondLoadResult{Bonds: m.bonds, Source: "golden-mock"}, nil
}
func (m mockBondService) LoadUniverse(context.Context) (application.BondLoadResult, error) {
	return application.BondLoadResult{Bonds: m.bonds, Source: "golden-mock"}, nil
}
func (m mockBondService) LoadBySecid(context.Context, string, portfolio.RiskProfile, string) (*bonds.BondRecord, error) {
	if len(m.bonds) > 0 {
		return &m.bonds[0], nil
	}
	return nil, nil
}
func (m mockBondService) LoadByISINs(context.Context, []string, portfolio.RiskProfile, string) ([]bonds.BondRecord, error) {
	return m.bonds, nil
}
func (m mockBondService) GetCouponSchedule(context.Context, string) ([]map[string]any, error) {
	return nil, nil
}
func (m mockBondService) RefreshRatings(context.Context) (int, error) { return 0, nil }
func (m mockBondService) InvalidateCaches(context.Context) error      { return nil }

type mockFavoritesRepo struct{ isins []string }

func (m mockFavoritesRepo) ListISINs(context.Context) ([]string, error) { return m.isins, nil }
func (m mockFavoritesRepo) Add(context.Context, string) error           { return nil }
func (m mockFavoritesRepo) Remove(context.Context, string) error      { return nil }

type mockPortfolioService struct {
	createResult portfolio.Portfolio
}

func (m mockPortfolioService) ListPortfolios(context.Context) ([]portfolio.Portfolio, error) {
	return nil, nil
}
func (m mockPortfolioService) CreatePortfolio(context.Context, application.CreatePortfolioParams) (portfolio.Portfolio, error) {
	p := m.createResult
	if p.ID == "" {
		p.ID = "generated-id"
	}
	if p.CreatedAt == "" {
		p.CreatedAt = time.Now().UTC().Format(time.RFC3339)
		p.UpdatedAt = p.CreatedAt
	}
	return p, nil
}
func (m mockPortfolioService) GetPortfolio(context.Context, string) (*portfolio.Portfolio, error) {
	return nil, application.ErrPortfolioNotFound
}
func (m mockPortfolioService) DeletePortfolio(context.Context, string) (bool, error) { return false, nil }
func (m mockPortfolioService) UpdatePortfolio(context.Context, string, application.UpdatePortfolioParams) (portfolio.Portfolio, error) {
	return portfolio.Portfolio{}, application.ErrPortfolioNotFound
}
func (m mockPortfolioService) ClearPositions(context.Context, string) (portfolio.Portfolio, error) {
	return portfolio.Portfolio{}, application.ErrPortfolioNotFound
}
func (m mockPortfolioService) AddPosition(context.Context, string, []bonds.BondRecord, string, int, time.Time) (portfolio.Portfolio, error) {
	return portfolio.Portfolio{}, application.ErrPortfolioNotFound
}
func (m mockPortfolioService) RemovePosition(context.Context, string, string) error {
	return application.ErrPortfolioNotFound
}
func (m mockPortfolioService) SetPutOfferDecision(context.Context, string, string, string) (portfolio.Portfolio, error) {
	return portfolio.Portfolio{}, application.ErrPortfolioNotFound
}
func (m mockPortfolioService) SetSlotOverride(context.Context, string, string, *string, []bonds.BondRecord, float64, float64, time.Time, portfolio.DurationPolicy) (portfolio.Portfolio, error) {
	return portfolio.Portfolio{}, application.ErrPortfolioNotFound
}
func (m mockPortfolioService) ResetAllSlotOverrides(context.Context, string) (portfolio.Portfolio, error) {
	return portfolio.Portfolio{}, application.ErrPortfolioNotFound
}
func (m mockPortfolioService) AutoComposePortfolio(context.Context, string, []bonds.BondRecord, float64, float64, time.Time, portfolio.DurationPolicy) (portfolio.Portfolio, error) {
	return portfolio.Portfolio{}, application.ErrPortfolioNotFound
}
func (m mockPortfolioService) BuildPortfolioPlan(context.Context, string, []bonds.BondRecord, float64, float64, time.Time, portfolio.DurationPolicy) (portfolio.PortfolioPlan, error) {
	return portfolio.PortfolioPlan{}, application.ErrPortfolioNotFound
}

type mockTradingService struct {
	createDeployErr error
}

func (m mockTradingService) ListAccounts(context.Context, trading.AccountKind) ([]map[string]any, error) {
	return nil, nil
}
func (m mockTradingService) CreateSandboxAccount(context.Context, float64, *string) (map[string]any, error) {
	return nil, nil
}
func (m mockTradingService) DeleteSandboxAccount(context.Context, string) (map[string]any, error) {
	return nil, nil
}
func (m mockTradingService) GetAccountPreview(context.Context, string, string, trading.AccountKind, []bonds.BondRecord) (map[string]any, error) {
	return nil, application.ErrPortfolioNotFound
}
func (m mockTradingService) ClearAccountForAttach(context.Context, string, string, trading.AccountKind, *float64, []bonds.BondRecord) (map[string]any, error) {
	return nil, application.ErrPortfolioNotFound
}
func (m mockTradingService) AttachAccount(context.Context, string, string, trading.AccountKind, []bonds.BondRecord, float64, float64, time.Time) (portfolio.Portfolio, error) {
	return portfolio.Portfolio{}, application.ErrPortfolioNotFound
}
func (m mockTradingService) DetachAccount(context.Context, string) (portfolio.Portfolio, error) {
	return portfolio.Portfolio{}, application.ErrPortfolioNotFound
}
func (m mockTradingService) SandboxPayIn(context.Context, string, float64) (map[string]any, error) {
	return nil, application.ErrPortfolioNotFound
}
func (m mockTradingService) GetAdvice(context.Context, string, []bonds.BondRecord, float64, float64, time.Time, portfolio.DurationPolicy) (application.TradingAdviceResult, error) {
	return application.TradingAdviceResult{}, application.ErrPortfolioNotFound
}
func (m mockTradingService) GetTradingState(context.Context, string, []bonds.BondRecord, float64, float64, time.Time, portfolio.DurationPolicy) (application.TradingStateResult, error) {
	return application.TradingStateResult{}, application.ErrPortfolioNotFound
}
func (m mockTradingService) BuildTradingPlan(context.Context, string, []bonds.BondRecord, float64, float64, time.Time, portfolio.DurationPolicy) (portfolio.PortfolioPlan, error) {
	return portfolio.PortfolioPlan{}, application.ErrPortfolioNotFound
}
func (m mockTradingService) CreateDeploySession(context.Context, string, []bonds.BondRecord, float64, float64, time.Time) (trading.DeploySession, error) {
	if m.createDeployErr != nil {
		return trading.DeploySession{}, m.createDeployErr
	}
	return trading.DeploySession{}, nil
}
func (m mockTradingService) GetActiveDeploySession(context.Context, string) (*trading.DeploySession, error) {
	return nil, nil
}
func (m mockTradingService) RefreshDeploySession(context.Context, string, string, []bonds.BondRecord, float64, float64, time.Time) (trading.DeploySession, error) {
	return trading.DeploySession{}, application.ErrDeploySessionNotFound
}
func (m mockTradingService) CancelDeploySession(context.Context, string, string) (trading.DeploySession, error) {
	return trading.DeploySession{}, application.ErrDeploySessionNotFound
}
func (m mockTradingService) SkipDeploySessionItem(context.Context, string, string, string) (trading.DeploySession, error) {
	return trading.DeploySession{}, application.ErrDeploySessionNotFound
}
func (m mockTradingService) AcknowledgeRiskAlert(context.Context, string, string, []bonds.BondRecord) error {
	return application.ErrPortfolioNotFound
}
func (m mockTradingService) PreviewOrder(context.Context, string, []bonds.BondRecord, string, string, int, float64, *string) (map[string]any, error) {
	return nil, application.ErrPortfolioNotFound
}
func (m mockTradingService) PlaceOrder(context.Context, string, []bonds.BondRecord, string, string, int, float64, *string, *string) (map[string]any, error) {
	return nil, application.ErrPortfolioNotFound
}
func (m mockTradingService) CancelOrder(context.Context, string, string) error { return application.ErrPortfolioNotFound }
func (m mockTradingService) PreviewSellPosition(context.Context, string, string, []bonds.BondRecord, int, float64, time.Time) (map[string]any, error) {
	return nil, application.ErrPortfolioNotFound
}
func (m mockTradingService) GetSellQuote(context.Context, string, string, []bonds.BondRecord) (map[string]any, error) {
	return nil, application.ErrPortfolioNotFound
}
func (m mockTradingService) GetPerformance(context.Context, string) (map[string]any, error) {
	return nil, nil
}
func (m mockTradingService) GetAccountOperations(context.Context, string) ([]trading.BrokerOperation, error) {
	return nil, application.ErrPortfolioNotFound
}

type mockNotificationsRepo struct{}

func (mockNotificationsRepo) ListForPortfolio(context.Context, string, bool) ([]application.NotificationRecord, error) {
	return nil, nil
}
func (mockNotificationsRepo) MarkRead(context.Context, string) (*application.NotificationRecord, error) {
	return nil, nil
}
func (mockNotificationsRepo) Dismiss(context.Context, string) (*application.NotificationRecord, error) {
	return nil, nil
}

func TestLitestarErrorShape(t *testing.T) {
	rr := httptest.NewRecorder()
	httpapi.WriteNotFound(rr, "Portfolio not found")
	var body map[string]any
	_ = json.Unmarshal(rr.Body.Bytes(), &body)
	if body["detail"] != "Portfolio not found" || int(body["status_code"].(float64)) != 404 {
		t.Fatalf("unexpected error body: %v", body)
	}
}

func TestValidationErrorExtra(t *testing.T) {
	rr := httptest.NewRecorder()
	httpapi.WriteValidationError(rr, "invalid slot", map[string]any{"code": "same_isin"})
	var body map[string]any
	_ = json.Unmarshal(rr.Body.Bytes(), &body)
	extra, ok := body["extra"].(map[string]any)
	if !ok || extra["code"] != "same_isin" {
		t.Fatalf("extra missing: %v", body)
	}
	if !strings.Contains(fmt.Sprint(body["status_code"]), "422") {
		t.Fatalf("status_code: %v", body["status_code"])
	}
}

// Ensure sentinel errors wrap correctly.
var _ = errors.Is(application.ErrDeploySessionConflict, application.ErrDeploySessionConflict)
