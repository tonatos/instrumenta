package notifications

import "time"

// AlertUrgency classifies alert priority.
type AlertUrgency string

const (
	AlertUrgencyNormal   AlertUrgency = "normal"
	AlertUrgencySoon     AlertUrgency = "soon"
	AlertUrgencyCritical AlertUrgency = "critical"
)

// AlertKind identifies portfolio alert types.
type AlertKind string

const (
	AlertKindPutOfferAction  AlertKind = "put_offer_action"
	AlertKindPutOfferWatch   AlertKind = "put_offer_watch"
	AlertKindRiskEscalation  AlertKind = "risk_escalation"
)

// Alert is a detected portfolio event for suggestions and outbound notifications.
type Alert struct {
	PortfolioID          string
	Kind                 AlertKind
	ISIN                 string
	Name                 string
	Lots                 int
	FIGI                 *string
	Reason               string
	Urgency              AlertUrgency
	DetailKey            string
	DueDate              *time.Time
	ChatTemplate         *string
	SuggestedPricePct    *float64
	MarketPricePct       *float64
	RiskAcknowledgeable  bool
	OfferWindowStatus    *string
	SubmissionStart      *time.Time
	SubmissionEnd        *time.Time
	EscalationKinds      []string
}
