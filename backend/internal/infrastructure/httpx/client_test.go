package httpx_test

import (
	"net/http"
	"net/url"
	"testing"
	"time"

	"github.com/tonatos/instrumenta/backend/internal/infrastructure/httpx"
)

func TestClientUsesExplicitProxy(t *testing.T) {
	client := httpx.Client(5*time.Second, "http://hysteria:8080")
	if client.Timeout != 5*time.Second {
		t.Fatalf("timeout: %v", client.Timeout)
	}
	tr, ok := client.Transport.(*http.Transport)
	if !ok || tr.Proxy == nil {
		t.Fatal("expected transport with Proxy")
	}
	req, _ := http.NewRequest(http.MethodGet, "https://api.telegram.org/", nil)
	proxyURL, err := tr.Proxy(req)
	if err != nil {
		t.Fatalf("Proxy: %v", err)
	}
	want, _ := url.Parse("http://hysteria:8080")
	if proxyURL == nil || proxyURL.String() != want.String() {
		t.Fatalf("proxy URL = %v, want %v", proxyURL, want)
	}
}

func TestClientWithoutProxyDoesNotForceEnvProxy(t *testing.T) {
	client := httpx.Client(5*time.Second, "")
	tr, ok := client.Transport.(*http.Transport)
	if !ok {
		t.Fatal("expected *http.Transport")
	}
	if tr.Proxy != nil {
		t.Fatal("empty proxy URL must not set Transport.Proxy (avoids HTTPS_PROXY for MOEX/T-Invest)")
	}
}
