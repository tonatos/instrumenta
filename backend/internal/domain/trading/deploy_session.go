package trading

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"time"

	"github.com/tonatos/instrumenta/backend/internal/domain/bonds"
	"github.com/tonatos/instrumenta/backend/internal/domain/portfolio"
	"github.com/tonatos/instrumenta/backend/internal/domain/shared"
)

type DeploySessionStatus string

const (
	DeploySessionActive    DeploySessionStatus = "active"
	DeploySessionCompleted DeploySessionStatus = "completed"
	DeploySessionCancelled DeploySessionStatus = "cancelled"
	DeploySessionExpired   DeploySessionStatus = "expired"
)

type DeploySessionItemKind string

const (
	DeploySessionItemBuy      DeploySessionItemKind = "buy"
	DeploySessionItemReinvest DeploySessionItemKind = "reinvest"
)

type DeploySessionItemStatus string

const (
	ItemStatusPending DeploySessionItemStatus = "pending"
	ItemStatusPlaced  DeploySessionItemStatus = "placed"
	ItemStatusFilled  DeploySessionItemStatus = "filled"
	ItemStatusSkipped DeploySessionItemStatus = "skipped"
	ItemStatusStale   DeploySessionItemStatus = "stale"
)

var terminalOrderStatuses = map[string]bool{
	"EXECUTION_REPORT_STATUS_FILL":      true,
	"EXECUTION_REPORT_STATUS_CANCELLED": true,
	"EXECUTION_REPORT_STATUS_REJECTED":  true,
}

const filledOrderStatus = "EXECUTION_REPORT_STATUS_FILL"

type DeploySessionItem struct {
	ID                  string
	Kind                DeploySessionItemKind
	ISIN                string
	Name                string
	Lots                int
	FIGI                *string
	SuggestedPricePct   float64
	EstimatedAmountRub  float64
	Reason              string
	Status              DeploySessionItemStatus
	SourceISIN          *string
	DueDate             *time.Time
	OrderID             *string
	Urgency             SuggestionUrgency
}

type DeploySession struct {
	ID              string
	PortfolioID     string
	Status          DeploySessionStatus
	Items           []DeploySessionItem
	CashSnapshotRub float64
	CreatedAt       time.Time
	ExpiresAt       time.Time
	Warnings        []string
	CompletedAt     *time.Time
}

type DeploySessionProgress struct {
	Total   int
	Pending int
	Placed  int
	Filled  int
	Skipped int
	Stale   int
}

func asUTC(t time.Time) time.Time {
	if t.Location() == time.UTC {
		return t
	}
	return t.UTC()
}

func DeploySessionProgressOf(session DeploySession) DeploySessionProgress {
	counts := map[DeploySessionItemStatus]int{
		ItemStatusPending: 0, ItemStatusPlaced: 0, ItemStatusFilled: 0,
		ItemStatusSkipped: 0, ItemStatusStale: 0,
	}
	for _, item := range session.Items {
		counts[item.Status]++
	}
	return DeploySessionProgress{
		Total:   len(session.Items),
		Pending: counts[ItemStatusPending],
		Placed:  counts[ItemStatusPlaced],
		Filled:  counts[ItemStatusFilled],
		Skipped: counts[ItemStatusSkipped],
		Stale:   counts[ItemStatusStale],
	}
}

func itemKey(s Suggestion) string {
	if s.Kind == SuggestionKindReinvest && s.SourceISIN != nil && s.DueDate != nil {
		return *s.SourceISIN + ":" + shared.FormatISODate(*s.DueDate)
	}
	return s.ISIN
}

func estimatedAmountRub(s Suggestion, universeByISIN map[string]bonds.BondRecord) float64 {
	bond, ok := universeByISIN[s.ISIN]
	if !ok {
		return 0
	}
	if p := bond.PricePerLotRub(); p != nil && *p > 0 {
		return round2(float64(s.Lots) * *p)
	}
	face := bond.FaceValue
	if face <= 0 {
		face = 1000
	}
	aci := 0.0
	if bond.AccruedInterest != nil {
		aci = *bond.AccruedInterest
	}
	pricePct := 100.0
	if s.SuggestedPricePct != nil {
		pricePct = *s.SuggestedPricePct
	}
	lotSize := bond.LotSize
	if lotSize <= 0 {
		lotSize = 1
	}
	return round2(float64(s.Lots*lotSize) * (face*pricePct/100 + aci))
}

func round2(v float64) float64 {
	return float64(int(v*100+0.5)) / 100
}

func SuggestionToSessionItem(
	s Suggestion,
	sessionID, portfolioID string,
	universeByISIN map[string]bonds.BondRecord,
) DeploySessionItem {
	itemID := StableID(portfolioID, "deploy-item", sessionID+":"+string(s.Kind)+":"+itemKey(s))
	price := 100.0
	if s.SuggestedPricePct != nil {
		price = *s.SuggestedPricePct
	}
	kind := DeploySessionItemBuy
	if s.Kind == SuggestionKindReinvest {
		kind = DeploySessionItemReinvest
	}
	return DeploySessionItem{
		ID:                 itemID,
		Kind:               kind,
		ISIN:               s.ISIN,
		Name:               s.Name,
		Lots:               s.Lots,
		FIGI:               s.FIGI,
		SuggestedPricePct:  price,
		EstimatedAmountRub: estimatedAmountRub(s, universeByISIN),
		Reason:             s.Reason,
		SourceISIN:         s.SourceISIN,
		DueDate:            s.DueDate,
		Urgency:            s.Urgency,
		Status:             ItemStatusPending,
	}
}

// BuildDeploySessionPlan freezes buy+reinvest suggestions into a deploy session.
func BuildDeploySessionPlan(
	p portfolio.Portfolio,
	holdings []HoldingView,
	positions []portfolio.PortfolioPosition,
	universe []bonds.BondRecord,
	availableCash float64,
	today time.Time,
	keyRate, taxRate float64,
	selectionPolicy portfolio.BondSelectionPolicy,
	planningPolicy portfolio.PlanningPolicy,
	durationPolicy portfolio.DurationPolicy,
	policy DeploySessionPolicy,
	now *time.Time,
	sessionID *string,
) DeploySession {
	universeByISIN := make(map[string]bonds.BondRecord, len(universe))
	for _, bond := range universe {
		universeByISIN[bond.ISIN] = bond
	}
	resolvedSessionID := randomSessionID()
	if sessionID != nil {
		resolvedSessionID = *sessionID
	}
	created := time.Now().UTC()
	if now != nil {
		created = asUTC(*now)
	}
	expires := created.Add(time.Duration(policy.TTLHours) * time.Hour)

	buySuggestions := BuildBuySuggestions(p, holdings, universe, availableCash, today, keyRate, taxRate, durationPolicy)
	reinvestSuggestions := BuildReinvestSuggestions(
		p, positions, universe, today, keyRate, taxRate, selectionPolicy, planningPolicy, durationPolicy, nil,
	)
	var items []DeploySessionItem
	for _, s := range append(buySuggestions, reinvestSuggestions...) {
		items = append(items, SuggestionToSessionItem(s, resolvedSessionID, p.ID, universeByISIN))
	}
	return DeploySession{
		ID:              resolvedSessionID,
		PortfolioID:     p.ID,
		Status:          DeploySessionActive,
		Items:           items,
		CashSnapshotRub: availableCash,
		CreatedAt:       created,
		ExpiresAt:       expires,
	}
}

func randomSessionID() string {
	var b [16]byte
	_, _ = rand.Read(b[:])
	return hex.EncodeToString(b[:])
}

func SessionItemToSuggestion(item DeploySessionItem, universeByISIN map[string]bonds.BondRecord) Suggestion {
	var marketPrice *float64
	if bond, ok := universeByISIN[item.ISIN]; ok && bond.LastPrice != nil {
		marketPrice = bond.LastPrice
	}
	kind := SuggestionKindBuy
	if item.Kind == DeploySessionItemReinvest {
		kind = SuggestionKindReinvest
	}
	price := item.SuggestedPricePct
	return Suggestion{
		ID:                item.ID,
		Kind:              kind,
		ISIN:              item.ISIN,
		Name:              item.Name,
		Lots:              item.Lots,
		FIGI:              item.FIGI,
		SuggestedPricePct: &price,
		MarketPricePct:    marketPrice,
		Reason:            item.Reason,
		DueDate:           item.DueDate,
		SourceISIN:        item.SourceISIN,
		Urgency:           item.Urgency,
	}
}

// SessionItemsToSuggestions converts pending session items to actionable suggestions.
func SessionItemsToSuggestions(session DeploySession, universe []bonds.BondRecord, kinds map[DeploySessionItemKind]bool) []Suggestion {
	universeByISIN := make(map[string]bonds.BondRecord, len(universe))
	for _, bond := range universe {
		universeByISIN[bond.ISIN] = bond
	}
	var result []Suggestion
	for _, item := range session.Items {
		if !kinds[item.Kind] || item.Status != ItemStatusPending {
			continue
		}
		result = append(result, SessionItemToSuggestion(item, universeByISIN))
	}
	return result
}

func impliedMarketPricePct(suggestedPricePct float64, accountKind *AccountKind) float64 {
	buffer := BuyLimitPriceBuffer(accountKind)
	return suggestedPricePct / (1 + buffer)
}

// ApplySessionStaleness marks items stale when prices drift or reinvest timing is wrong.
func ApplySessionStaleness(
	session DeploySession,
	universe []bonds.BondRecord,
	p portfolio.Portfolio,
	policy DeploySessionPolicy,
	now *time.Time,
) DeploySession {
	current := time.Now().UTC()
	if now != nil {
		current = asUTC(*now)
	}
	if !asUTC(session.ExpiresAt).After(current) {
		session.Status = DeploySessionExpired
		return session
	}
	universeByISIN := make(map[string]bonds.BondRecord, len(universe))
	for _, bond := range universe {
		universeByISIN[bond.ISIN] = bond
	}
	warnings := append([]string(nil), session.Warnings...)
	var updated []DeploySessionItem
	for _, item := range session.Items {
		if item.Status == ItemStatusFilled || item.Status == ItemStatusSkipped ||
			item.Status == ItemStatusStale || item.Status == ItemStatusPlaced {
			updated = append(updated, item)
			continue
		}
		if item.Kind == DeploySessionItemReinvest && item.DueDate != nil {
			due := shared.DateOnly(*item.DueDate)
			today := shared.DateOnly(current)
			if due.After(today) {
				item.Status = ItemStatusStale
				warnings = append(warnings, fmt.Sprintf(
					"%s: реинвестиция доступна с %s — обновите план ближе к дате",
					item.Name, shared.FormatDate(&due),
				))
				updated = append(updated, item)
				continue
			}
			if due.Before(today) {
				item.Status = ItemStatusStale
				warnings = append(warnings, fmt.Sprintf(
					"%s: погашение источника %s прошло — обновите план",
					item.Name, shared.FormatDate(&due),
				))
				updated = append(updated, item)
				continue
			}
		}
		bond, ok := universeByISIN[item.ISIN]
		if !ok || !portfolio.HasUsablePrice(bond) {
			item.Status = ItemStatusStale
			warnings = append(warnings, item.ISIN+": бумага недоступна для покупки")
			updated = append(updated, item)
			continue
		}
		implied := impliedMarketPricePct(item.SuggestedPricePct, p.AccountKind)
		currentMarket := implied
		if bond.LastPrice != nil {
			currentMarket = *bond.LastPrice
		}
		if implied <= 0 {
			updated = append(updated, item)
			continue
		}
		driftPct := abs(currentMarket-implied) / implied * 100
		if driftPct >= policy.PriceDriftStalePct {
			item.Status = ItemStatusStale
			warnings = append(warnings, fmt.Sprintf("%s: цена ушла на %.1f%% — обновите план", item.Name, driftPct))
		} else if driftPct >= policy.PriceDriftWarnPct {
			warnings = append(warnings, fmt.Sprintf("%s: цена изменилась на %.1f%%", item.Name, driftPct))
		}
		updated = append(updated, item)
	}
	session.Items = updated
	session.Warnings = dedupeWarnings(warnings)
	return session
}

func abs(v float64) float64 {
	if v < 0 {
		return -v
	}
	return v
}

func dedupeWarnings(warnings []string) []string {
	seen := make(map[string]struct{})
	var out []string
	for _, w := range warnings {
		if _, ok := seen[w]; ok {
			continue
		}
		seen[w] = struct{}{}
		out = append(out, w)
	}
	return out
}

// SyncSessionWithOrders updates placed items from broker order statuses.
func SyncSessionWithOrders(session DeploySession, activeOrders []BrokerActiveOrder) DeploySession {
	ordersByID := make(map[string]BrokerActiveOrder, len(activeOrders))
	for _, order := range activeOrders {
		ordersByID[order.OrderID] = order
	}
	var updated []DeploySessionItem
	for _, item := range session.Items {
		if item.Status != ItemStatusPlaced || item.OrderID == nil {
			updated = append(updated, item)
			continue
		}
		order, ok := ordersByID[*item.OrderID]
		if !ok {
			item.Status = ItemStatusFilled
			updated = append(updated, item)
			continue
		}
		switch {
		case order.Status == filledOrderStatus:
			item.Status = ItemStatusFilled
		case terminalOrderStatuses[order.Status]:
			item.Status = ItemStatusPending
			item.OrderID = nil
		}
		updated = append(updated, item)
	}
	session.Items = updated
	return CompleteSessionIfNoPending(session)
}

func MarkItemPlaced(session DeploySession, itemID, orderID string) DeploySession {
	for i := range session.Items {
		if session.Items[i].ID == itemID {
			session.Items[i].Status = ItemStatusPlaced
			session.Items[i].OrderID = &orderID
			break
		}
	}
	return CompleteSessionIfNoPending(session)
}

func MarkItemSkipped(session DeploySession, itemID string) DeploySession {
	for i := range session.Items {
		if session.Items[i].ID == itemID {
			session.Items[i].Status = ItemStatusSkipped
			break
		}
	}
	return CompleteSessionIfNoPending(session)
}

func FindSessionItem(session DeploySession, itemID string) *DeploySessionItem {
	for i := range session.Items {
		if session.Items[i].ID == itemID {
			return &session.Items[i]
		}
	}
	return nil
}

func CompleteSessionIfNoPending(session DeploySession) DeploySession {
	if session.Status != DeploySessionActive || len(session.Items) == 0 {
		return session
	}
	for _, item := range session.Items {
		if item.Status == ItemStatusPending {
			return session
		}
	}
	session.Status = DeploySessionCompleted
	now := time.Now().UTC()
	session.CompletedAt = &now
	return session
}

func SessionHasPendingItems(session DeploySession) bool {
	for _, item := range session.Items {
		if item.Status == ItemStatusPending {
			return true
		}
	}
	return false
}

func IsSessionActive(session DeploySession, now *time.Time) bool {
	current := time.Now().UTC()
	if now != nil {
		current = asUTC(*now)
	}
	return session.Status == DeploySessionActive && asUTC(session.ExpiresAt).After(current)
}
