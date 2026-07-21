package application

import (
	"context"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/domain/trading"
)

// BondLoadResult is the result of loading bonds from cache or upstream.
type BondLoadResult struct {
	Bonds  []bonds.BondRecord
	Source string
}

// BondListLoadResult is a paginated screener response.
type BondListLoadResult struct {
	Bonds    []bonds.BondRecord
	Total    int
	Page     int
	PageSize int
	Source   string
}

// BondService loads and scores bonds.
type BondService interface {
	ListBonds(ctx context.Context, query bonds.BondListQuery, riskProfile portfolio.RiskProfile, rateScenario string) (BondListLoadResult, error)
	LoadUniverse(ctx context.Context) (BondLoadResult, error)
	LoadBySecid(ctx context.Context, secid string, riskProfile portfolio.RiskProfile, rateScenario string) (*bonds.BondRecord, error)
	LoadByISINs(ctx context.Context, isins []string, riskProfile portfolio.RiskProfile, rateScenario string) ([]bonds.BondRecord, error)
	GetCouponSchedule(ctx context.Context, figi string) ([]map[string]any, error)
	RefreshRatings(ctx context.Context) (int, error)
	InvalidateCaches(ctx context.Context) error
}

// FavoritesRepository persists favorite ISINs.
type FavoritesRepository interface {
	ListISINs(ctx context.Context) ([]string, error)
	Add(ctx context.Context, isin string) error
	Remove(ctx context.Context, isin string) error
}

// CreatePortfolioParams is input for portfolio creation.
type CreatePortfolioParams struct {
	Name                     string
	InitialAmountRub         float64
	HorizonDate              time.Time
	RiskProfile              portfolio.RiskProfile
	APITradeOnly             bool
	TurboEntryEnabled        bool
	MaxWeightedDurationYears *float64
	TargetDurationYears      *float64
}

// UpdatePortfolioParams is partial portfolio update.
type UpdatePortfolioParams struct {
	Name                     *string
	InitialAmountRub         *float64
	HorizonDate              *time.Time
	RiskProfile              *portfolio.RiskProfile
	APITradeOnly             *bool
	TurboEntryEnabled        *bool
	MaxWeightedDurationYears *float64
	TargetDurationYears      *float64
	SetMaxWeightedDuration   bool
	SetTargetDuration        bool
}

// PortfolioService manages portfolio CRUD and planning.
type PortfolioService interface {
	ListPortfolios(ctx context.Context) ([]portfolio.Portfolio, error)
	CreatePortfolio(ctx context.Context, params CreatePortfolioParams) (portfolio.Portfolio, error)
	GetPortfolio(ctx context.Context, id string) (*portfolio.Portfolio, error)
	DeletePortfolio(ctx context.Context, id string) (bool, error)
	UpdatePortfolio(ctx context.Context, id string, params UpdatePortfolioParams) (portfolio.Portfolio, error)
	ClearPositions(ctx context.Context, id string) (portfolio.Portfolio, error)
	AddPosition(ctx context.Context, id string, universe []bonds.BondRecord, isin string, lots int, today time.Time) (portfolio.Portfolio, error)
	RemovePosition(ctx context.Context, id, isin string) error
	SetPutOfferDecision(ctx context.Context, id, isin, decision string) (portfolio.Portfolio, error)
	SetSlotOverride(ctx context.Context, id string, sourceISIN string, confirmedISIN *string, universe []bonds.BondRecord, keyRate, taxRate float64, today time.Time, durationPolicy portfolio.DurationPolicy) (portfolio.Portfolio, error)
	ResetAllSlotOverrides(ctx context.Context, id string) (portfolio.Portfolio, error)
	AutoComposePortfolio(ctx context.Context, id string, universe []bonds.BondRecord, keyRate, taxRate float64, today time.Time, durationPolicy portfolio.DurationPolicy) (portfolio.Portfolio, error)
	BuildPortfolioPlan(ctx context.Context, id string, universe []bonds.BondRecord, keyRate, taxRate float64, today time.Time, durationPolicy portfolio.DurationPolicy) (portfolio.PortfolioPlan, error)
}

// TradingAdviceResult bundles advisory output.
type TradingAdviceResult struct {
	Holdings              []trading.HoldingView
	Cashflow              []map[string]any
	Performance           *trading.ActualPerformance
	Suggestions           []trading.Suggestion
	ActiveOrders          []trading.BrokerActiveOrder
	MoneyRub              float64
	AvailableMoneyRub     float64
	BlockedMoneyRub       float64
	Warnings              []string
	AsOf                  string
	WeightedDurationYears *float64
	DeploySession         *trading.DeploySession
}

// TradingStateResult bundles plan + advice.
type TradingStateResult struct {
	Plan   portfolio.PortfolioPlan
	Advice TradingAdviceResult
}

// TradingService covers trading mode operations.
type TradingService interface {
	ListAccounts(ctx context.Context, kind trading.AccountKind) ([]map[string]any, error)
	CreateSandboxAccount(ctx context.Context, initialAmountRub float64, name *string) (map[string]any, error)
	DeleteSandboxAccount(ctx context.Context, accountID string) (map[string]any, error)
	GetAccountPreview(ctx context.Context, portfolioID, accountID string, kind trading.AccountKind, universe []bonds.BondRecord) (map[string]any, error)
	ClearAccountForAttach(ctx context.Context, portfolioID, accountID string, kind trading.AccountKind, payInRub *float64, universe []bonds.BondRecord) (map[string]any, error)
	AttachAccount(ctx context.Context, portfolioID, accountID string, kind trading.AccountKind, universe []bonds.BondRecord, keyRate, taxRate float64, today time.Time) (portfolio.Portfolio, error)
	DetachAccount(ctx context.Context, portfolioID string) (portfolio.Portfolio, error)
	SandboxPayIn(ctx context.Context, portfolioID string, amountRub float64) (map[string]any, error)
	GetAdvice(ctx context.Context, portfolioID string, universe []bonds.BondRecord, keyRate, taxRate float64, today time.Time, durationPolicy portfolio.DurationPolicy) (TradingAdviceResult, error)
	GetTradingState(ctx context.Context, portfolioID string, universe []bonds.BondRecord, keyRate, taxRate float64, today time.Time, durationPolicy portfolio.DurationPolicy) (TradingStateResult, error)
	BuildTradingPlan(ctx context.Context, portfolioID string, universe []bonds.BondRecord, keyRate, taxRate float64, today time.Time, durationPolicy portfolio.DurationPolicy) (portfolio.PortfolioPlan, error)
	CreateDeploySession(ctx context.Context, portfolioID string, universe []bonds.BondRecord, keyRate, taxRate float64, today time.Time) (trading.DeploySession, error)
	GetActiveDeploySession(ctx context.Context, portfolioID string) (*trading.DeploySession, error)
	RefreshDeploySession(ctx context.Context, portfolioID, sessionID string, universe []bonds.BondRecord, keyRate, taxRate float64, today time.Time) (trading.DeploySession, error)
	CancelDeploySession(ctx context.Context, portfolioID, sessionID string) (trading.DeploySession, error)
	SkipDeploySessionItem(ctx context.Context, portfolioID, sessionID, itemID string) (trading.DeploySession, error)
	AcknowledgeRiskAlert(ctx context.Context, portfolioID, isin string, universe []bonds.BondRecord) error
	PreviewOrder(ctx context.Context, portfolioID string, universe []bonds.BondRecord, isin, direction string, lots int, pricePct float64, figi *string) (map[string]any, error)
	PlaceOrder(ctx context.Context, portfolioID string, universe []bonds.BondRecord, isin, direction string, lots int, pricePct float64, figi, suggestionID *string) (map[string]any, error)
	CancelOrder(ctx context.Context, portfolioID, orderID string) error
	PreviewSellPosition(ctx context.Context, portfolioID, isin string, universe []bonds.BondRecord, lots int, pricePct float64, today time.Time) (map[string]any, error)
	GetSellQuote(ctx context.Context, portfolioID, isin string, universe []bonds.BondRecord) (map[string]any, error)
	GetPerformance(ctx context.Context, portfolioID string) (map[string]any, error)
	GetAccountOperations(ctx context.Context, portfolioID string) ([]trading.BrokerOperation, error)
}

// NotificationRecord is a persisted in-app notification.
type NotificationRecord struct {
	ID          string
	Fingerprint string
	PortfolioID string
	Kind        string
	Payload     map[string]any
	Urgency     string
	CreatedAt   time.Time
	ReadAt      *time.Time
	DismissedAt *time.Time
	IsUnread    bool
}

// NotificationsRepository reads and updates user notifications.
type NotificationsRepository interface {
	ListForPortfolio(ctx context.Context, portfolioID string, unreadOnly bool) ([]NotificationRecord, error)
	MarkRead(ctx context.Context, notificationID string) (*NotificationRecord, error)
	Dismiss(ctx context.Context, notificationID string) (*NotificationRecord, error)
}

// NotificationConsumer starts Redis stream consumer on API boot.
type NotificationConsumer interface {
	Start(ctx context.Context) error
	Stop(ctx context.Context) error
}

// MarketRadarResponse is the read-model for GET /market-radar.
type MarketRadarResponse struct {
	ScannedAt       string                  `json:"scanned_at"`
	UniverseScanned int                     `json:"universe_scanned"`
	Sectors         []MarketRadarSectorRow  `json:"sectors"`
	Anomalies       []MarketRadarAnomalyRow `json:"anomalies"`
	DipIdeas        []MarketRadarDipIdeaRow `json:"dip_ideas"`
}

type MarketRadarSectorRow struct {
	Sector       string   `json:"sector"`
	Change7dPct  float64  `json:"change_7d_pct"`
	AnomalyCount int      `json:"anomaly_count"`
	DipIdeaCount int      `json:"dip_idea_count"`
	BondCount    int      `json:"bond_count"`
	InPortfolios []string `json:"in_portfolios,omitempty"`
}

type MarketRadarAnomalyRow struct {
	ISIN             string   `json:"isin"`
	Secid            string   `json:"secid"`
	Name             string   `json:"name"`
	Sector           string   `json:"sector"`
	SpreadPP         float64  `json:"spread_pp"`
	ExpectedSpreadPP float64  `json:"expected_spread_pp"`
	DeltaPP          float64  `json:"delta_pp"`
	ZScore           *float64 `json:"z_score,omitempty"`
	Peers            int      `json:"peers"`
	InPortfolios     []string `json:"in_portfolios,omitempty"`
}

type MarketRadarDipIdeaRow struct {
	ISIN                     string   `json:"isin"`
	Secid                    string   `json:"secid"`
	Name                     string   `json:"name"`
	Sector                   string   `json:"sector"`
	BondChange7dPct          float64  `json:"bond_change_7d_pct"`
	SectorChange7dPct        float64  `json:"sector_change_7d_pct"`
	IdiosyncraticExcess7dPct float64  `json:"idiosyncratic_excess_pct"`
	Score                    float64  `json:"score"`
	Interpretation           string   `json:"interpretation"`
	InPortfolios             []string `json:"in_portfolios,omitempty"`
}

// MarketRadarService reads the latest market radar snapshot.
type MarketRadarService interface {
	GetMarketRadar(ctx context.Context, highlightPortfolios bool) (*MarketRadarResponse, error)
}

// DatabaseInitializer prepares persistence on startup.
type DatabaseInitializer interface {
	Init(ctx context.Context) error
	Migrate(ctx context.Context) error
}

type DeploySessionConflictError struct {
	Message string
}

func (e DeploySessionConflictError) Error() string {
	if e.Message != "" {
		return e.Message
	}
	return "deploy session conflict"
}

func (e DeploySessionConflictError) Is(target error) bool {
	return target == ErrDeploySessionConflict
}

type DeploySessionEmptyError struct {
	Message string
}

func (e DeploySessionEmptyError) Error() string {
	if e.Message != "" {
		return e.Message
	}
	return "deploy session empty"
}

func (e DeploySessionEmptyError) Is(target error) bool {
	return target == ErrDeploySessionEmpty
}

type DeploySessionNotFoundError struct {
	Message string
}

func (e DeploySessionNotFoundError) Error() string {
	if e.Message != "" {
		return e.Message
	}
	return "deploy session not found"
}

func (e DeploySessionNotFoundError) Is(target error) bool {
	return target == ErrDeploySessionNotFound
}

// Domain errors for HTTP mapping.
var (
	ErrNotFound                  = errSentinel("not found")
	ErrPortfolioNotFound         = errSentinel("portfolio not found")
	ErrPositionNotFound          = errSentinel("position not found")
	ErrBondNotFound              = errSentinel("bond not found")
	ErrNotificationNotFound      = errSentinel("notification not found")
	ErrDeploySessionNotFound     = errSentinel("deploy session not found")
	ErrDeploySessionConflict     = errSentinel("deploy session conflict")
	ErrDeploySessionEmpty        = errSentinel("deploy session empty")
	ErrSlotOverrideInvalid       = errSentinel("slot override invalid")
	ErrBrokerCredentialsRequired = errSentinel("broker_credentials_required")
)

type errSentinel string

func (e errSentinel) Error() string { return string(e) }

type SlotOverrideError struct {
	Code    string
	Message string
}

func (e SlotOverrideError) Error() string { return e.Message }
