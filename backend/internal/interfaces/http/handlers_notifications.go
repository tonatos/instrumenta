package httpapi

import (
	"net/http"

	"github.com/go-chi/chi/v5"
)

func (h *Handler) ListNotifications(w http.ResponseWriter, r *http.Request) {
	portfolioID := chi.URLParam(r, "portfolio_id")
	unreadOnly := r.URL.Query().Get("unread_only") == "true"
	records, err := h.deps.Notifications.ListForPortfolio(r.Context(), portfolioID, unreadOnly)
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	out := make([]NotificationResponse, 0, len(records))
	for _, record := range records {
		out = append(out, NotificationToResponse(record))
	}
	WriteJSON(w, http.StatusOK, NotificationsListResponse{Notifications: out})
}

func (h *Handler) MarkNotificationRead(w http.ResponseWriter, r *http.Request) {
	notificationID := chi.URLParam(r, "notification_id")
	record, err := h.deps.Notifications.MarkRead(r.Context(), notificationID)
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	if record == nil {
		WriteNotFound(w, "Notification not found")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (h *Handler) DismissNotification(w http.ResponseWriter, r *http.Request) {
	notificationID := chi.URLParam(r, "notification_id")
	record, err := h.deps.Notifications.Dismiss(r.Context(), notificationID)
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	if record == nil {
		WriteNotFound(w, "Notification not found")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
