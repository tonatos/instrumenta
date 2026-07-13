package httpapi

import (
	"encoding/json"
	"errors"
	"net/http"
)

// APIError matches Litestar HTTPException JSON body.
type APIError struct {
	Detail     string         `json:"detail"`
	StatusCode int            `json:"status_code"`
	Extra      map[string]any `json:"extra,omitempty"`
}

func WriteJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if payload == nil {
		return
	}
	_ = json.NewEncoder(w).Encode(payload)
}

func WriteError(w http.ResponseWriter, status int, detail string, extra map[string]any) {
	WriteJSON(w, status, APIError{Detail: detail, StatusCode: status, Extra: extra})
}

func WriteNotFound(w http.ResponseWriter, detail string) {
	WriteError(w, http.StatusNotFound, detail, nil)
}

func WriteClientError(w http.ResponseWriter, status int, detail string) {
	if status == 0 {
		status = http.StatusBadRequest
	}
	WriteError(w, status, detail, nil)
}

func WriteValidationError(w http.ResponseWriter, detail string, extra map[string]any) {
	WriteError(w, http.StatusUnprocessableEntity, detail, extra)
}

func WriteUnauthorized(w http.ResponseWriter, detail string) {
	if detail == "" {
		detail = "Unauthorized"
	}
	WriteError(w, http.StatusUnauthorized, detail, nil)
}

func WriteConflict(w http.ResponseWriter, detail string) {
	WriteError(w, http.StatusConflict, detail, nil)
}

func DecodeBody(r *http.Request, dst any) error {
	if r.Body == nil {
		return errors.New("empty body")
	}
	defer r.Body.Close()
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	return dec.Decode(dst)
}
