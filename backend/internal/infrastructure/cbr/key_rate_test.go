package cbr_test

import (
	"testing"
	"time"

	"github.com/tonatos/instrumenta/backend/internal/infrastructure/cbr"
)

func TestParseKeyRateSOAP_LatestByDate(t *testing.T) {
	raw := []byte(`<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <KeyRateXMLResponse xmlns="http://web.cbr.ru/">
      <KeyRateXMLResult>
        <KeyRate xmlns="">
          <KR><DT>2026-06-19T00:00:00+03:00</DT><Rate>14.50</Rate></KR>
          <KR><DT>2026-07-23T00:00:00+03:00</DT><Rate>14.25</Rate></KR>
          <KR><DT>2026-07-01T00:00:00+03:00</DT><Rate>14.25</Rate></KR>
        </KeyRate>
      </KeyRateXMLResult>
    </KeyRateXMLResponse>
  </soap:Body>
</soap:Envelope>`)

	rate, asOf, err := cbr.ParseKeyRateSOAP(raw)
	if err != nil {
		t.Fatal(err)
	}
	if rate != 14.25 {
		t.Fatalf("rate: got %v want 14.25", rate)
	}
	wantDay := time.Date(2026, 7, 23, 0, 0, 0, 0, time.FixedZone("MSK", 3*3600))
	if asOf.Year() != wantDay.Year() || asOf.Month() != wantDay.Month() || asOf.Day() != wantDay.Day() {
		t.Fatalf("asOf: got %v want day %v", asOf, wantDay)
	}
}

func TestParseKeyRateSOAP_Empty(t *testing.T) {
	raw := []byte(`<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <KeyRateXMLResponse xmlns="http://web.cbr.ru/">
      <KeyRateXMLResult><KeyRate xmlns=""></KeyRate></KeyRateXMLResult>
    </KeyRateXMLResponse>
  </soap:Body>
</soap:Envelope>`)
	if _, _, err := cbr.ParseKeyRateSOAP(raw); err == nil {
		t.Fatal("expected error")
	}
}
