// Package httpx builds shared HTTP clients for outbound calls.
package httpx

import (
	"net/http"
	"net/url"
	"strings"
	"time"
)

// Client returns an HTTP client with an optional explicit proxy.
// When proxyURL is empty, the client does not use HTTP(S)_PROXY from the environment,
// so MOEX / YooKassa / other RU APIs stay direct while Telegram can be proxied separately.
func Client(timeout time.Duration, proxyURL string) *http.Client {
	transport := http.DefaultTransport.(*http.Transport).Clone()
	proxyURL = strings.TrimSpace(proxyURL)
	if proxyURL != "" {
		if u, err := url.Parse(proxyURL); err == nil && u.Host != "" {
			transport.Proxy = http.ProxyURL(u)
		}
	} else {
		transport.Proxy = nil
	}
	return &http.Client{Timeout: timeout, Transport: transport}
}
