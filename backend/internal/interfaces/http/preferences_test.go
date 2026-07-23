package httpapi_test

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"

	"github.com/tonatos/instrumenta/backend/internal/infrastructure/persistence"
	"github.com/tonatos/instrumenta/backend/internal/interfaces/auth"
	"github.com/tonatos/instrumenta/backend/internal/interfaces/config"
	httpapi "github.com/tonatos/instrumenta/backend/internal/interfaces/http"
)

func TestPutPreferencesTaxRate(t *testing.T) {
	dir := t.TempDir()
	db, err := persistence.Open("sqlite://" + filepath.Join(dir, "prefs.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	if err := persistence.ApplyMigrations(db.DB, "sqlite", ""); err != nil {
		t.Fatal(err)
	}
	if err := persistence.EnsureUsersTaxSchema(t.Context(), db.DB); err != nil {
		t.Fatal(err)
	}
	users := persistence.NewUserRepository(db)
	jwt := auth.NewJWTManager("prefs-secret", true)
	token, err := jwt.CreateAccessToken(auth.User{TelegramID: 7, DisplayName: "T"})
	if err != nil {
		t.Fatal(err)
	}
	router := httpapi.NewRouter(httpapi.Deps{
		Settings: config.Settings{AuthDisabled: false, AuthSecret: "prefs-secret"},
		JWT:      jwt,
		Users:    users,
	}, nil)

	body, _ := json.Marshal(map[string]any{"tax_rate": 0})
	req := httptest.NewRequest(http.MethodPut, "/api/v1/me/preferences", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("put: %d %s", rec.Code, rec.Body.String())
	}

	cfgReq := httptest.NewRequest(http.MethodGet, "/api/v1/config/", nil)
	cfgReq.Header.Set("Authorization", "Bearer "+token)
	cfgRec := httptest.NewRecorder()
	router.ServeHTTP(cfgRec, cfgReq)
	if cfgRec.Code != 200 {
		t.Fatalf("config: %d", cfgRec.Code)
	}
	var cfg map[string]any
	_ = json.Unmarshal(cfgRec.Body.Bytes(), &cfg)
	if cfg["tax_rate"] != float64(0) {
		t.Fatalf("config tax_rate=%v want 0", cfg["tax_rate"])
	}

	bad, _ := json.Marshal(map[string]any{"tax_rate": 14})
	badReq := httptest.NewRequest(http.MethodPut, "/api/v1/me/preferences", bytes.NewReader(bad))
	badReq.Header.Set("Authorization", "Bearer "+token)
	badReq.Header.Set("Content-Type", "application/json")
	badRec := httptest.NewRecorder()
	router.ServeHTTP(badRec, badReq)
	if badRec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for invalid tax, got %d", badRec.Code)
	}
}
