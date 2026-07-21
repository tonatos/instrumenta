package httpapi_test

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/application/adapters"
	appportfolio "github.com/tonatos/bond-monitor/backend/internal/application/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/crypto"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/persistence"
	"github.com/tonatos/bond-monitor/backend/internal/interfaces/auth"
	"github.com/tonatos/bond-monitor/backend/internal/interfaces/config"
	httpapi "github.com/tonatos/bond-monitor/backend/internal/interfaces/http"
)

func TestPortfolioIsolationBetweenUsers(t *testing.T) {
	db, err := persistence.Open("file:memdb_iso?mode=memory&cache=shared")
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	if err := persistence.ApplyMigrations(db.DB, "sqlite", ""); err != nil {
		t.Fatal(err)
	}

	portfolioRepo := persistence.NewPortfolioRepository(db)
	favoritesRepo := persistence.NewFavoritesRepository(db)
	usersRepo := persistence.NewUserRepository(db)
	kek, err := crypto.NewLocalKEK("test-isolation-kek-material!!!!", 1)
	if err != nil {
		t.Fatal(err)
	}
	credRepo := persistence.NewBrokerCredentialsRepository(db, kek)
	portfolioSvc := adapters.NewPortfolioService(appportfolio.NewService(portfolioRepo, nil))
	jwt := auth.NewJWTManager("iso-secret", true)

	deps := httpapi.Deps{
		Settings:    config.Settings{AuthDisabled: false, AuthSecret: "iso-secret"},
		JWT:         jwt,
		Portfolios:  portfolioSvc,
		Favorites:   adapters.NewFavoritesRepository(favoritesRepo),
		Credentials: credRepo,
		Users:       usersRepo,
	}
	router := httpapi.NewRouter(deps, nil)

	tokenA, err := jwt.CreateAccessToken(auth.User{TelegramID: 100, DisplayName: "A"})
	if err != nil {
		t.Fatal(err)
	}
	tokenB, err := jwt.CreateAccessToken(auth.User{TelegramID: 200, DisplayName: "B"})
	if err != nil {
		t.Fatal(err)
	}

	body := map[string]any{
		"name": "A portfolio", "initial_amount_rub": 100000,
		"horizon_date": time.Now().AddDate(1, 0, 0).Format("2006-01-02"),
		"risk_profile": "normal",
	}
	raw, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/portfolios/", bytes.NewReader(raw))
	req.Header.Set("Authorization", "Bearer "+tokenA)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	if rec.Code != http.StatusCreated {
		t.Fatalf("create: %d %s", rec.Code, rec.Body.String())
	}
	var created map[string]any
	_ = json.Unmarshal(rec.Body.Bytes(), &created)
	id, _ := created["id"].(string)
	if id == "" {
		t.Fatal("missing id")
	}

	// User B cannot get A's portfolio
	req = httptest.NewRequest(http.MethodGet, "/api/v1/portfolios/"+id, nil)
	req.Header.Set("Authorization", "Bearer "+tokenB)
	rec = httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	if rec.Code != http.StatusNotFound {
		t.Fatalf("expected 404 for B, got %d %s", rec.Code, rec.Body.String())
	}

	// User B list is empty
	req = httptest.NewRequest(http.MethodGet, "/api/v1/portfolios/", nil)
	req.Header.Set("Authorization", "Bearer "+tokenB)
	rec = httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("list B: %d", rec.Code)
	}
	var list []any
	_ = json.Unmarshal(rec.Body.Bytes(), &list)
	if len(list) != 0 {
		t.Fatalf("B should see 0 portfolios, got %d", len(list))
	}

	// User A still sees it
	req = httptest.NewRequest(http.MethodGet, "/api/v1/portfolios/"+id, nil)
	req.Header.Set("Authorization", "Bearer "+tokenA)
	rec = httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("get A: %d %s", rec.Code, rec.Body.String())
	}

	// Favorites isolation at persistence layer
	_ = favoritesRepo.Add(context.Background(), 100, "RU000A0JX0J2")
	isinsB, _ := favoritesRepo.ListISINs(context.Background(), 200)
	if len(isinsB) != 0 {
		t.Fatalf("B favorites leaked: %v", isinsB)
	}
	isinsA, _ := favoritesRepo.ListISINs(context.Background(), 100)
	if len(isinsA) != 1 {
		t.Fatalf("A favorites: %v", isinsA)
	}

	// Direct ownership check on saved row
	got, err := portfolioRepo.GetByIDForOwner(context.Background(), id, 100)
	if err != nil || got == nil {
		t.Fatal("owner 100 should see portfolio")
	}
	missing, err := portfolioRepo.GetByIDForOwner(context.Background(), id, 200)
	if err != nil || missing != nil {
		t.Fatal("owner 200 must not see portfolio")
	}
}
