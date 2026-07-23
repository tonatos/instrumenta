package ratings

import (
	"fmt"
	"io"
	"net/http"
	"regexp"
	"strings"
)

const smartLabBondsPageURL = "https://smart-lab.ru/q/bonds/order_by_yield/desc/page"

var (
	bondRowRe = regexp.MustCompile(`(?is)<tr[^>]*>.*?</tr>`)
	isinRe    = regexp.MustCompile(`/q/bonds/(RU[0-9A-Z]+)/`)
	tdRe      = regexp.MustCompile(`(?is)<td[^>]*>(.*?)</td>`)
	tagRe     = regexp.MustCompile(`(?is)<[^>]+>`)
)

type pageFetcher func(url string) (string, error)

// ScrapeSmartLabRatings loads ISIN → rating map from smart-lab bond screener pages.
func ScrapeSmartLabRatings(fetch pageFetcher) (map[string]string, error) {
	out := make(map[string]string)
	for page := 1; page <= 32; page++ {
		html, err := fetch(smartLabBondsPageURL + itoa(page) + "/")
		if err != nil {
			return out, err
		}
		rows := parseBondRows(html)
		if len(rows) == 0 {
			break
		}
		for isin, rating := range rows {
			out[isin] = rating
		}
	}
	return out, nil
}

func parseBondRows(html string) map[string]string {
	out := make(map[string]string)
	for _, row := range bondRowRe.FindAllString(html, -1) {
		match := isinRe.FindStringSubmatch(row)
		if len(match) < 2 {
			continue
		}
		cells := tdRe.FindAllStringSubmatch(row, -1)
		if len(cells) < 8 {
			continue
		}
		ratingRaw := strings.TrimSpace(tagRe.ReplaceAllString(cells[7][1], ""))
		rating, ok := NormalizeRating(ratingRaw)
		if !ok {
			continue
		}
		out[match[1]] = rating
	}
	return out
}

func defaultHTTPFetcher(url string) (string, error) {
	req, err := http.NewRequest(http.MethodGet, url, nil)
	if err != nil {
		return "", err
	}
	req.Header.Set("User-Agent", "instrumenta/1.0")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("smart-lab: HTTP %d", resp.StatusCode)
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", err
	}
	return string(body), nil
}

func itoa(v int) string {
	if v == 0 {
		return "0"
	}
	var digits []byte
	for v > 0 {
		digits = append([]byte{byte('0' + v%10)}, digits...)
		v /= 10
	}
	return string(digits)
}
