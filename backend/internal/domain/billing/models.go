package billing

import "time"

// Period is a billing cycle length.
type Period string

const (
	PeriodMonth Period = "month"
	PeriodYear  Period = "year"
)

// SubscriptionStatus is the lifecycle state of a subscription.
type SubscriptionStatus string

const (
	StatusActive   SubscriptionStatus = "active"
	StatusPastDue  SubscriptionStatus = "past_due"
	StatusCanceled SubscriptionStatus = "canceled"
	StatusExpired  SubscriptionStatus = "expired"
)

// PaymentStatus tracks a payment attempt.
type PaymentStatus string

const (
	PaymentPending   PaymentStatus = "pending"
	PaymentSucceeded PaymentStatus = "succeeded"
	PaymentCanceled  PaymentStatus = "canceled"
	PaymentFailed    PaymentStatus = "failed"
)

// LedgerEntryKind is credit (money in / entitlement grant) or debit (charge).
type LedgerEntryKind string

const (
	LedgerCredit LedgerEntryKind = "credit"
	LedgerDebit  LedgerEntryKind = "debit"
)

// PlanVersion is an immutable price+feature snapshot. New prices create a new version;
// active subscriptions keep the version they paid for until the period ends.
type PlanVersion struct {
	ID             string
	CatalogGroup   string // e.g. "pro"
	Code           string // e.g. "pro_month"
	Period         Period
	AmountKopecks  int64
	Features       []Feature
	EffectiveFrom  time.Time
	IsCurrent      bool
}

// Subscription is the owner's paid access state.
type Subscription struct {
	ID                 string
	OwnerTelegramID    int64
	Status             SubscriptionStatus
	PlanVersionID      string
	Period             Period
	AmountKopecks      int64 // grandfathered price for renewals
	Features           []Feature
	CurrentPeriodStart time.Time
	CurrentPeriodEnd   time.Time
	CancelAtPeriodEnd  bool
	PaymentMethodID    string // opaque YooKassa id; never expose via API
	PastDueSince       *time.Time
	CreatedAt          time.Time
	UpdatedAt          time.Time
}

// Payment is a checkout or renewal attempt.
type Payment struct {
	ID                string
	OwnerTelegramID   int64
	PlanVersionID     string
	Period            Period
	AmountKopecks     int64
	Status            PaymentStatus
	IdempotencyKey    string
	YooKassaPaymentID string
	ConfirmationURL   string
	Purpose           string // "checkout" | "renew" | "change_period"
	CreatedAt         time.Time
	UpdatedAt         time.Time
}

// LedgerEntry is an accounting row for the finance UI.
type LedgerEntry struct {
	ID              string
	OwnerTelegramID int64
	Kind            LedgerEntryKind
	AmountKopecks   int64
	Reason          string
	PaymentID       string
	CreatedAt       time.Time
}

// CatalogItem is a public plan option for the tariff page.
type CatalogItem struct {
	Period         Period    `json:"period"`
	AmountKopecks  int64     `json:"amount_kopecks"`
	MonthlyKopecks int64     `json:"monthly_kopecks"`
	SavingsKopecks int64     `json:"savings_kopecks"`
	SavingsPercent float64   `json:"savings_percent"`
	Features       []Feature `json:"features"`
	PlanVersionID  string    `json:"plan_version_id"`
}
