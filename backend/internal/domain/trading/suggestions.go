package trading

import "time"

// SuggestionKind classifies trading recommendations for the UI queue.
type SuggestionKind string

const (
	SuggestionKindBuy              SuggestionKind = "buy"
	SuggestionKindReinvest         SuggestionKind = "reinvest"
	SuggestionKindReinvestWatch      SuggestionKind = "reinvest_watch"
	SuggestionKindPutOfferReminder   SuggestionKind = "put_offer_reminder"
	SuggestionKindPutOfferWatch      SuggestionKind = "put_offer_watch"
	SuggestionKindSell               SuggestionKind = "sell"
)

// SuggestionUrgency drives UI ordering and Telegram policy.
type SuggestionUrgency string

const (
	SuggestionUrgencyNormal   SuggestionUrgency = "normal"
	SuggestionUrgencySoon     SuggestionUrgency = "soon"
	SuggestionUrgencyCritical SuggestionUrgency = "critical"
)

// Suggestion is an actionable or informational trading recommendation.
type Suggestion struct {
	ID                   string
	Kind                 SuggestionKind
	ISIN                 string
	Name                 string
	Lots                 int
	FIGI                 *string
	SuggestedPricePct    *float64
	Reason               string
	MarketPricePct       *float64
	DueDate              *time.Time
	SourceISIN           *string
	ChatTemplate         *string
	Urgency              SuggestionUrgency
	RiskAcknowledgeable  bool
	OfferWindowStatus    *string
	SubmissionStart      *time.Time
	SubmissionEnd        *time.Time
}
