package trading

import (
	"github.com/tonatos/instrumenta/backend/internal/domain/notifications"
)

// AlertsToSuggestions maps domain alerts to trading suggestions.
func AlertsToSuggestions(alerts []notifications.Alert) []Suggestion {
	var suggestions []Suggestion
	for _, alert := range alerts {
		if s := alertToSuggestion(alert); s != nil {
			suggestions = append(suggestions, *s)
		}
	}
	return suggestions
}

func alertToSuggestion(alert notifications.Alert) *Suggestion {
	switch alert.Kind {
	case notifications.AlertKindPutOfferAction:
		return &Suggestion{
			ID: StableID(alert.PortfolioID, "put_offer", alert.ISIN),
			Kind: SuggestionKindPutOfferReminder, ISIN: alert.ISIN, Name: alert.Name,
			Lots: alert.Lots, FIGI: alert.FIGI, SuggestedPricePct: alert.SuggestedPricePct,
			Reason: alert.Reason, DueDate: alert.DueDate, ChatTemplate: alert.ChatTemplate,
			Urgency: SuggestionUrgency(alert.Urgency),
			OfferWindowStatus: alert.OfferWindowStatus,
			SubmissionStart: alert.SubmissionStart, SubmissionEnd: alert.SubmissionEnd,
		}
	case notifications.AlertKindPutOfferWatch:
		return &Suggestion{
			ID: StableID(alert.PortfolioID, "put_offer_watch", alert.ISIN),
			Kind: SuggestionKindPutOfferWatch, ISIN: alert.ISIN, Name: alert.Name,
			Lots: alert.Lots, FIGI: alert.FIGI, SuggestedPricePct: alert.SuggestedPricePct,
			Reason: alert.Reason, DueDate: alert.DueDate, Urgency: SuggestionUrgencyNormal,
			OfferWindowStatus: alert.OfferWindowStatus,
			SubmissionStart: alert.SubmissionStart, SubmissionEnd: alert.SubmissionEnd,
		}
	case notifications.AlertKindRiskEscalation:
		primaryKind := "risk"
		if len(alert.EscalationKinds) > 0 {
			primaryKind = alert.EscalationKinds[0]
		}
		return &Suggestion{
			ID: StableID(alert.PortfolioID, "risk_sell", alert.ISIN+":"+primaryKind),
			Kind: SuggestionKindSell, ISIN: alert.ISIN, Name: alert.Name,
			Lots: alert.Lots, FIGI: alert.FIGI, SuggestedPricePct: alert.SuggestedPricePct,
			MarketPricePct: alert.MarketPricePct, Reason: alert.Reason,
			Urgency: SuggestionUrgency(alert.Urgency), RiskAcknowledgeable: alert.RiskAcknowledgeable,
		}
	default:
		return nil
	}
}
