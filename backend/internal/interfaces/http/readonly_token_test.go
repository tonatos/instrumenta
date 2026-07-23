package httpapi_test

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/tonatos/instrumenta/backend/internal/application"
	httpapi "github.com/tonatos/instrumenta/backend/internal/interfaces/http"
)

func TestWriteAppError_brokerTokenReadOnly(t *testing.T) {
	t.Parallel()
	rr := httptest.NewRecorder()
	if !httpapi.WriteAppError(rr, application.ErrBrokerTokenReadOnly) {
		t.Fatal("expected handled")
	}
	if rr.Code != http.StatusForbidden {
		t.Fatalf("status %d", rr.Code)
	}
	var body map[string]any
	if err := json.Unmarshal(rr.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	extra, _ := body["extra"].(map[string]any)
	if extra["code"] != "broker_token_readonly" {
		t.Fatalf("body=%s", rr.Body.String())
	}
}

func TestAdviceToResponse_canPlaceOrders(t *testing.T) {
	t.Parallel()
	resp := httpapi.AdviceToResponse(application.TradingAdviceResult{
		AsOf:           "2026-07-23T00:00:00Z",
		CanPlaceOrders: false,
	})
	if resp.CanPlaceOrders {
		t.Fatal("expected false")
	}
	resp2 := httpapi.AdviceToResponse(application.TradingAdviceResult{CanPlaceOrders: true})
	if !resp2.CanPlaceOrders {
		t.Fatal("expected true")
	}
}
