package yookassa

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// PaymentGateway creates and fetches payments at the acquirer.
type PaymentGateway interface {
	Enabled() bool
	CreatePayment(ctx context.Context, req CreatePaymentRequest) (CreatePaymentResult, error)
	GetPayment(ctx context.Context, paymentID string) (PaymentInfo, error)
}

// CreatePaymentRequest is provider-agnostic checkout input.
type CreatePaymentRequest struct {
	AmountKopecks   int64
	Description     string
	ReturnURL       string
	IdempotencyKey  string
	SavePaymentMethod bool
	PaymentMethodID string // for recurring charge; empty for first payment
	Metadata        map[string]string
}

// CreatePaymentResult is returned after create.
type CreatePaymentResult struct {
	ID              string
	Status          string
	ConfirmationURL string
	Paid            bool
	PaymentMethodID string
}

// PaymentInfo is a verified payment snapshot from the provider.
type PaymentInfo struct {
	ID              string
	Status          string
	Paid            bool
	AmountKopecks   int64
	PaymentMethodID string
	Metadata        map[string]string
}

// DisabledGateway is used when shop credentials are missing.
type DisabledGateway struct{}

func (DisabledGateway) Enabled() bool { return false }

func (DisabledGateway) CreatePayment(context.Context, CreatePaymentRequest) (CreatePaymentResult, error) {
	return CreatePaymentResult{}, ErrPaymentUnavailable
}

func (DisabledGateway) GetPayment(context.Context, string) (PaymentInfo, error) {
	return PaymentInfo{}, ErrPaymentUnavailable
}

// ErrPaymentUnavailable means YooKassa is not configured.
var ErrPaymentUnavailable = fmt.Errorf("payment_unavailable")

// Client talks to YooKassa Payments API v3.
type Client struct {
	ShopID     string
	SecretKey  string
	HTTPClient *http.Client
	BaseURL    string
}

// NewClient returns a live client, or DisabledGateway when credentials are empty.
func NewClient(shopID, secretKey string, httpClient *http.Client) PaymentGateway {
	shopID = strings.TrimSpace(shopID)
	secretKey = strings.TrimSpace(secretKey)
	if shopID == "" || secretKey == "" {
		return DisabledGateway{}
	}
	if httpClient == nil {
		httpClient = &http.Client{Timeout: 20 * time.Second}
	}
	return &Client{
		ShopID:     shopID,
		SecretKey:  secretKey,
		HTTPClient: httpClient,
		BaseURL:    "https://api.yookassa.ru/v3",
	}
}

func (c *Client) Enabled() bool { return true }

type amountDTO struct {
	Value    string `json:"value"`
	Currency string `json:"currency"`
}

type createPaymentBody struct {
	Amount            amountDTO         `json:"amount"`
	Capture           bool              `json:"capture"`
	Description       string            `json:"description,omitempty"`
	Confirmation      *confirmationDTO  `json:"confirmation,omitempty"`
	SavePaymentMethod bool              `json:"save_payment_method,omitempty"`
	PaymentMethodID   string            `json:"payment_method_id,omitempty"`
	Metadata          map[string]string `json:"metadata,omitempty"`
}

type confirmationDTO struct {
	Type      string `json:"type"`
	ReturnURL string `json:"return_url,omitempty"`
}

type paymentMethodDTO struct {
	ID    string `json:"id"`
	Saved bool   `json:"saved"`
}

type paymentResponse struct {
	ID           string            `json:"id"`
	Status       string            `json:"status"`
	Paid         bool              `json:"paid"`
	Amount       amountDTO         `json:"amount"`
	Confirmation *confirmationDTO  `json:"confirmation"`
	PaymentMethod *paymentMethodDTO `json:"payment_method"`
	Metadata     map[string]string `json:"metadata"`
}

func (c *Client) CreatePayment(ctx context.Context, req CreatePaymentRequest) (CreatePaymentResult, error) {
	body := createPaymentBody{
		Amount: amountDTO{
			Value:    formatRub(req.AmountKopecks),
			Currency: "RUB",
		},
		Capture:           true,
		Description:       req.Description,
		SavePaymentMethod: req.SavePaymentMethod && req.PaymentMethodID == "",
		PaymentMethodID:   req.PaymentMethodID,
		Metadata:          req.Metadata,
	}
	if req.PaymentMethodID == "" {
		body.Confirmation = &confirmationDTO{Type: "redirect", ReturnURL: req.ReturnURL}
	}
	raw, err := json.Marshal(body)
	if err != nil {
		return CreatePaymentResult{}, err
	}
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, c.BaseURL+"/payments", bytes.NewReader(raw))
	if err != nil {
		return CreatePaymentResult{}, err
	}
	httpReq.SetBasicAuth(c.ShopID, c.SecretKey)
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Idempotence-Key", req.IdempotencyKey)

	resp, err := c.HTTPClient.Do(httpReq)
	if err != nil {
		return CreatePaymentResult{}, err
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 300 {
		return CreatePaymentResult{}, fmt.Errorf("yookassa create payment: %s: %s", resp.Status, truncate(string(data), 300))
	}
	var parsed paymentResponse
	if err := json.Unmarshal(data, &parsed); err != nil {
		return CreatePaymentResult{}, err
	}
	out := CreatePaymentResult{
		ID:     parsed.ID,
		Status: parsed.Status,
		Paid:   parsed.Paid,
	}
	if parsed.Confirmation != nil {
		out.ConfirmationURL = parsed.Confirmation.ReturnURL
		// confirmation.confirmation_url is the redirect URL; parse from raw if needed
	}
	var full struct {
		Confirmation *struct {
			ConfirmationURL string `json:"confirmation_url"`
			ReturnURL       string `json:"return_url"`
			Type            string `json:"type"`
		} `json:"confirmation"`
		PaymentMethod *paymentMethodDTO `json:"payment_method"`
	}
	_ = json.Unmarshal(data, &full)
	if full.Confirmation != nil {
		out.ConfirmationURL = full.Confirmation.ConfirmationURL
	}
	if full.PaymentMethod != nil {
		out.PaymentMethodID = full.PaymentMethod.ID
	}
	return out, nil
}

func (c *Client) GetPayment(ctx context.Context, paymentID string) (PaymentInfo, error) {
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodGet, c.BaseURL+"/payments/"+paymentID, nil)
	if err != nil {
		return PaymentInfo{}, err
	}
	httpReq.SetBasicAuth(c.ShopID, c.SecretKey)
	resp, err := c.HTTPClient.Do(httpReq)
	if err != nil {
		return PaymentInfo{}, err
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 300 {
		return PaymentInfo{}, fmt.Errorf("yookassa get payment: %s: %s", resp.Status, truncate(string(data), 300))
	}
	var parsed paymentResponse
	if err := json.Unmarshal(data, &parsed); err != nil {
		return PaymentInfo{}, err
	}
	kopecks, err := parseRub(parsed.Amount.Value)
	if err != nil {
		return PaymentInfo{}, err
	}
	info := PaymentInfo{
		ID:            parsed.ID,
		Status:        parsed.Status,
		Paid:          parsed.Paid,
		AmountKopecks: kopecks,
		Metadata:      parsed.Metadata,
	}
	if parsed.PaymentMethod != nil {
		info.PaymentMethodID = parsed.PaymentMethod.ID
	}
	return info, nil
}

func formatRub(kopecks int64) string {
	rub := kopecks / 100
	kop := kopecks % 100
	if kop < 0 {
		kop = -kop
	}
	return fmt.Sprintf("%d.%02d", rub, kop)
}

func parseRub(value string) (int64, error) {
	value = strings.TrimSpace(value)
	parts := strings.SplitN(value, ".", 2)
	var rub, kop int64
	_, err := fmt.Sscanf(parts[0], "%d", &rub)
	if err != nil {
		return 0, fmt.Errorf("parse amount: %w", err)
	}
	if len(parts) == 2 {
		frac := parts[1]
		if len(frac) == 1 {
			frac += "0"
		}
		if len(frac) > 2 {
			frac = frac[:2]
		}
		_, err = fmt.Sscanf(frac, "%d", &kop)
		if err != nil {
			return 0, err
		}
	}
	if rub < 0 {
		return rub*100 - kop, nil
	}
	return rub*100 + kop, nil
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}
