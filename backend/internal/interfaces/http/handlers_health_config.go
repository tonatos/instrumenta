package httpapi

import (
	"net/http"
)

func (h *Handler) Health(w http.ResponseWriter, _ *http.Request) {
	WriteJSON(w, http.StatusOK, HealthResponse{Status: "ok"})
}

func (h *Handler) GetConfig(w http.ResponseWriter, r *http.Request) {
	keyRate, taxFrac := h.resolveMarketRates(r.Context())
	WriteJSON(w, http.StatusOK, ConfigToResponse(h.deps.Settings, keyRate, taxFrac*100))
}
