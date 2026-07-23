package cbr

import (
	"bytes"
	"context"
	"encoding/xml"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"
)

const (
	// DailyInfoSOAP is the Bank of Russia DailyInfo web service endpoint.
	DailyInfoSOAP = "https://www.cbr.ru/DailyInfoWebServ/DailyInfo.asmx"
	soapAction    = "http://web.cbr.ru/KeyRateXML"
)

// Client fetches the key rate from CBR DailyInfo SOAP.
type Client struct {
	HTTP     *http.Client
	Endpoint string
}

func NewClient(httpClient *http.Client) *Client {
	if httpClient == nil {
		httpClient = &http.Client{Timeout: 15 * time.Second}
	}
	return &Client{HTTP: httpClient, Endpoint: DailyInfoSOAP}
}

// FetchLatestKeyRate returns the most recent key rate (percent points) and its date.
func (c *Client) FetchLatestKeyRate(ctx context.Context, now time.Time) (rate float64, asOf time.Time, err error) {
	from := now.AddDate(0, 0, -45)
	body := keyRateSOAPRequest(from, now)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.Endpoint, bytes.NewReader(body))
	if err != nil {
		return 0, time.Time{}, err
	}
	req.Header.Set("Content-Type", "text/xml; charset=utf-8")
	req.Header.Set("SOAPAction", `"`+soapAction+`"`)

	resp, err := c.HTTP.Do(req)
	if err != nil {
		return 0, time.Time{}, err
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return 0, time.Time{}, err
	}
	if resp.StatusCode != http.StatusOK {
		return 0, time.Time{}, fmt.Errorf("cbr key rate: HTTP %d", resp.StatusCode)
	}
	return ParseKeyRateSOAP(raw)
}

func keyRateSOAPRequest(from, to time.Time) []byte {
	const layout = "2006-01-02T15:04:05"
	return []byte(fmt.Sprintf(`<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <KeyRateXML xmlns="http://web.cbr.ru/">
      <fromDate>%s</fromDate>
      <ToDate>%s</ToDate>
    </KeyRateXML>
  </soap:Body>
</soap:Envelope>`, from.UTC().Format(layout), to.UTC().Format(layout)))
}

type soapEnvelope struct {
	Body struct {
		KeyRateXMLResponse struct {
			KeyRateXMLResult struct {
				Inner []byte `xml:",innerxml"`
			} `xml:"KeyRateXMLResult"`
		} `xml:"KeyRateXMLResponse"`
	} `xml:"Body"`
}

type keyRateDoc struct {
	Rows []keyRateRow `xml:"KR"`
}

type keyRateRow struct {
	DT   string `xml:"DT"`
	Rate string `xml:"Rate"`
}

// ParseKeyRateSOAP extracts the latest key rate from a CBR KeyRateXML SOAP response.
func ParseKeyRateSOAP(raw []byte) (rate float64, asOf time.Time, err error) {
	var env soapEnvelope
	if err := xml.Unmarshal(raw, &env); err != nil {
		return 0, time.Time{}, fmt.Errorf("cbr soap xml: %w", err)
	}
	inner := env.Body.KeyRateXMLResponse.KeyRateXMLResult.Inner
	if len(bytes.TrimSpace(inner)) == 0 {
		// Some responses nest KeyRate as a child element without innerxml fallback.
		return parseKeyRateDocument(raw)
	}
	rate, asOf, err = parseKeyRateDocument(inner)
	if err == nil {
		return rate, asOf, nil
	}
	return parseKeyRateDocument(raw)
}

func parseKeyRateDocument(raw []byte) (float64, time.Time, error) {
	var doc keyRateDoc
	if err := xml.Unmarshal(raw, &doc); err != nil {
		// Try wrapping fragment in a root for innerxml that starts with <KR>.
		wrapped := append([]byte("<KeyRate>"), append(raw, []byte("</KeyRate>")...)...)
		if err2 := xml.Unmarshal(wrapped, &doc); err2 != nil {
			return 0, time.Time{}, fmt.Errorf("cbr key rate xml: %w", err)
		}
	}
	if len(doc.Rows) == 0 {
		return 0, time.Time{}, fmt.Errorf("cbr key rate: empty series")
	}
	bestRate := 0.0
	var bestAsOf time.Time
	found := false
	for _, row := range doc.Rows {
		r, err := strconv.ParseFloat(strings.TrimSpace(row.Rate), 64)
		if err != nil {
			continue
		}
		dt, err := parseCBRDate(row.DT)
		if err != nil {
			continue
		}
		if !found || dt.After(bestAsOf) {
			bestRate = r
			bestAsOf = dt
			found = true
		}
	}
	if !found {
		return 0, time.Time{}, fmt.Errorf("cbr key rate: no parseable rows")
	}
	return bestRate, bestAsOf, nil
}

func parseCBRDate(s string) (time.Time, error) {
	s = strings.TrimSpace(s)
	layouts := []string{
		time.RFC3339,
		"2006-01-02T15:04:05",
		"2006-01-02",
	}
	for _, layout := range layouts {
		if t, err := time.Parse(layout, s); err == nil {
			return t, nil
		}
	}
	// Offset without colon sometimes appears; strip zone and parse local wall time.
	if i := strings.IndexAny(s, "+-"); i > 10 {
		if t, err := time.Parse("2006-01-02T15:04:05", s[:i]); err == nil {
			return t, nil
		}
	}
	return time.Time{}, fmt.Errorf("bad date %q", s)
}
