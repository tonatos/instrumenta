package moex

import (
	"encoding/gob"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/paths"
)

const (
	issBase           = "https://iss.moex.com/iss"
	cacheTTLSeconds   = 900
	securitiesColumns = "SECID,BOARDID,SHORTNAME,ISIN,MATDATE,OFFERDATE,PREVDATE,COUPONPERCENT,ACCRUEDINT,FACEVALUE,FACEUNIT,COUPONPERIOD,COUPONVALUE,NEXTCOUPON,LOTSIZE,LOTVALUE"
	marketdataColumns = "SECID,BOARDID,LAST,PREVPRICE,YIELDATWAP,YIELD,YIELDCLOSE,DURATION,VALTODAY"
)

// Client fetches bond data from MOEX ISS with disk caching.
type Client struct {
	httpClient *http.Client
	cacheFile  string
	cacheDir   string
}

type cacheBundle struct {
	SavedDate   time.Time
	Bonds       map[string]map[string]any
	PrevVolumes map[string]float64
}

// NewClient creates a MOEX ISS client.
func NewClient() *Client {
	cacheDir := paths.CacheDir()
	return &Client{
		httpClient: &http.Client{Timeout: 60 * time.Second},
		cacheFile:  filepath.Join(cacheDir, "moex_bonds.gob"),
		cacheDir:   cacheDir,
	}
}

func (c *Client) FetchAllBondsUnfiltered() ([]bonds.BondRecord, error) {
	today := time.Now()
	bundle, err := c.loadOrFetchBundle()
	if err != nil {
		return nil, err
	}
	var result []bonds.BondRecord
	for isin, raw := range bundle.Bonds {
		if bond := buildBondRecord(isin, raw, today, prevVolumePtr(bundle.PrevVolumes[isin])); bond != nil {
			result = append(result, *bond)
		}
	}
	return result, nil
}

func (c *Client) FetchBondBySecid(secid string) (*bonds.BondRecord, error) {
	if secid == "" {
		return nil, nil
	}
	today := time.Now()
	bundle, err := c.loadOrFetchBundle()
	if err != nil {
		return nil, err
	}
	for isin, raw := range bundle.Bonds {
		if v, _ := raw["SECID"].(string); v == secid {
			return buildBondRecord(isin, raw, today, prevVolumePtr(bundle.PrevVolumes[isin])), nil
		}
	}
	return nil, nil
}

func (c *Client) FetchBondsByISINs(isins map[string]struct{}) ([]bonds.BondRecord, error) {
	if len(isins) == 0 {
		return nil, nil
	}
	today := time.Now()
	bundle, err := c.loadOrFetchBundle()
	if err != nil {
		return nil, err
	}
	var result []bonds.BondRecord
	for isin := range isins {
		raw, ok := bundle.Bonds[isin]
		if !ok {
			continue
		}
		if bond := buildBondRecord(isin, raw, today, prevVolumePtr(bundle.PrevVolumes[isin])); bond != nil {
			result = append(result, *bond)
		}
	}
	return result, nil
}

func (c *Client) IsCacheFresh() bool {
	info, err := os.Stat(c.cacheFile)
	if err != nil {
		return false
	}
	return time.Since(info.ModTime()) < cacheTTLSeconds*time.Second
}

func (c *Client) InvalidateCache() {
	_ = os.Remove(c.cacheFile)
}

func (c *Client) loadOrFetchBundle() (*cacheBundle, error) {
	if fresh := c.readDiskCache(false); fresh != nil {
		return fresh, nil
	}
	stale := c.readDiskCache(true)
	merged, err := c.fetchFromMOEX()
	if err != nil {
		return nil, err
	}
	return c.saveDiskCache(merged, stale)
}

func (c *Client) readDiskCache(allowStale bool) *cacheBundle {
	info, err := os.Stat(c.cacheFile)
	if err != nil {
		return nil
	}
	if !allowStale && time.Since(info.ModTime()) >= cacheTTLSeconds*time.Second {
		return nil
	}
	f, err := os.Open(c.cacheFile)
	if err != nil {
		return nil
	}
	defer f.Close()
	var bundle cacheBundle
	if err := gob.NewDecoder(f).Decode(&bundle); err != nil {
		return nil
	}
	return &bundle
}

func (c *Client) saveDiskCache(merged map[string]map[string]any, old *cacheBundle) (*cacheBundle, error) {
	today := time.Now().Truncate(24 * time.Hour)
	prev := prevVolumesFromBundle(old, today)
	if len(prev) == 0 {
		prev = c.fetchPrevVolumesFromHistory(merged)
	}
	bundle := &cacheBundle{SavedDate: today, Bonds: merged, PrevVolumes: prev}
	if err := os.MkdirAll(c.cacheDir, 0o755); err != nil {
		return bundle, nil
	}
	tmp := c.cacheFile + ".tmp"
	f, err := os.Create(tmp)
	if err != nil {
		return bundle, err
	}
	if err := gob.NewEncoder(f).Encode(bundle); err != nil {
		f.Close()
		return bundle, err
	}
	f.Close()
	_ = os.Rename(tmp, c.cacheFile)
	return bundle, nil
}

func (c *Client) fetchFromMOEX() (map[string]map[string]any, error) {
	u := issBase + "/engines/stock/markets/bonds/securities.json"
	q := url.Values{
		"iss.meta":           {"off"},
		"securities.columns": {securitiesColumns},
		"marketdata.columns": {marketdataColumns},
	}
	resp, err := c.httpClient.Get(u + "?" + q.Encode())
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	var data map[string]json.RawMessage
	if err := json.Unmarshal(body, &data); err != nil {
		return nil, err
	}
	secs, err := parseBlock(data["securities"])
	if err != nil {
		return nil, err
	}
	mdata, err := parseBlock(data["marketdata"])
	if err != nil {
		return nil, err
	}
	return mergeRows(secs, mdata), nil
}

func parseBlock(raw json.RawMessage) ([]map[string]any, error) {
	var block struct {
		Columns []string `json:"columns"`
		Data    [][]any  `json:"data"`
	}
	if err := json.Unmarshal(raw, &block); err != nil {
		return nil, err
	}
	rows := make([]map[string]any, 0, len(block.Data))
	for _, row := range block.Data {
		m := make(map[string]any, len(block.Columns))
		for i, col := range block.Columns {
			if i < len(row) {
				m[col] = row[i]
			}
		}
		rows = append(rows, m)
	}
	return rows, nil
}

func mergeRows(secs, mdata []map[string]any) map[string]map[string]any {
	index := make(map[string]map[string]any, len(mdata))
	for _, r := range mdata {
		key := fmt.Sprintf("%v|%v", r["SECID"], r["BOARDID"])
		index[key] = r
	}
	byISIN := make(map[string]map[string]any)
	for _, sec := range secs {
		isin, _ := sec["ISIN"].(string)
		if isin == "" {
			continue
		}
		key := fmt.Sprintf("%v|%v", sec["SECID"], sec["BOARDID"])
		merged := make(map[string]any)
		for k, v := range sec {
			merged[k] = v
		}
		for k, v := range index[key] {
			merged[k] = v
		}
		valToday := parseFloat(merged["VALTODAY"])
		prev := parseFloat(byISIN[isin]["VALTODAY"])
		val := 0.0
		prevVal := 0.0
		if valToday != nil {
			val = *valToday
		}
		if prev != nil {
			prevVal = *prev
		}
		if val >= prevVal {
			byISIN[isin] = merged
		}
	}
	return byISIN
}

func buildBondRecord(isin string, raw map[string]any, today time.Time, prevVolume *float64) *bonds.BondRecord {
	if faceUnit, _ := raw["FACEUNIT"].(string); faceUnit != "" && faceUnit != "SUR" {
		return nil
	}
	maturity := parseDate(raw["MATDATE"])
	offer := parseDate(raw["OFFERDATE"])
	var candidates []time.Time
	if maturity != nil && !maturity.Before(today) {
		candidates = append(candidates, *maturity)
	}
	if offer != nil && !offer.Before(today) {
		candidates = append(candidates, *offer)
	}
	if len(candidates) == 0 {
		return nil
	}
	effective := candidates[0]
	for _, d := range candidates[1:] {
		if d.Before(effective) {
			effective = d
		}
	}
	days := int(effective.Sub(today).Hours() / 24)
	if days <= 0 {
		return nil
	}
	ytm := pickYTM(raw["YIELDATWAP"], raw["YIELD"], raw["YIELDCLOSE"])
	last := parseFloat(raw["LAST"])
	if last == nil {
		last = parseFloat(raw["PREVPRICE"])
	}
	faceValue := parseFloat(raw["FACEVALUE"])
	fv := 1000.0
	if faceValue != nil {
		fv = *faceValue
	}
	lotSizeRaw := parseFloat(raw["LOTSIZE"])
	lotSize := 1
	if lotSizeRaw != nil && *lotSizeRaw > 0 {
		lotSize = int(*lotSizeRaw + 0.5)
	} else if lotValue := parseFloat(raw["LOTVALUE"]); lotValue != nil && fv > 0 {
		lotSize = int(*lotValue/fv + 0.5)
	}
	if lotSize < 1 {
		lotSize = 1
	}
	volToday := parseFloat(raw["VALTODAY"])
	bond := &bonds.BondRecord{
		Secid: strVal(raw["SECID"]), ISIN: isin, Name: strVal(raw["SHORTNAME"]),
		MaturityDate: maturity, OfferDate: offer, EffectiveDate: &effective, DaysToMaturity: &days,
		YTM: ytm, CouponRate: parseFloat(raw["COUPONPERCENT"]),
		AccruedInterest: parseFloat(raw["ACCRUEDINT"]), CouponType: bonds.CouponTypeUnknown,
		FaceValue: fv, LotSize: lotSize, LastPrice: last,
		DurationDays: parseFloat(raw["DURATION"]),
	}
	if volToday != nil {
		bond.VolumeRub = volToday
	}
	if prevVolume != nil {
		bond.PrevVolumeRub = prevVolume
	}
	if cp := parseFloat(raw["COUPONPERIOD"]); cp != nil && *cp > 0 {
		v := int(*cp)
		bond.CouponPeriodDays = &v
	}
	bond.CouponValue = parseFloat(raw["COUPONVALUE"])
	bond.NextCouponDate = parseDate(raw["NEXTCOUPON"])
	return bond
}

func (c *Client) fetchPrevVolumesFromHistory(merged map[string]map[string]any) map[string]float64 {
	var tradeDate *time.Time
	secidToISIN := make(map[string]string)
	for isin, row := range merged {
		if d := parseDate(row["PREVDATE"]); d != nil {
			tradeDate = d
		}
		secidToISIN[strVal(row["SECID"])] = isin
	}
	if tradeDate == nil {
		return nil
	}
	bySecid := make(map[string]float64)
	for start := 0; ; start += 100 {
		u := issBase + "/history/engines/stock/markets/bonds/securities.json"
		q := url.Values{
			"iss.meta":         {"off"},
			"history.columns":  {"SECID,VALUE"},
			"date":             {tradeDate.Format("2006-01-02")},
			"start":            {fmt.Sprintf("%d", start)},
			"limit":            {"100"},
		}
		resp, err := c.httpClient.Get(u + "?" + q.Encode())
		if err != nil {
			break
		}
		body, _ := io.ReadAll(resp.Body)
		resp.Body.Close()
		var data map[string]json.RawMessage
		if json.Unmarshal(body, &data) != nil {
			break
		}
		rows, err := parseBlock(data["history"])
		if err != nil || len(rows) == 0 {
			break
		}
		for _, row := range rows {
			secid := strVal(row["SECID"])
			value := parseFloat(row["VALUE"])
			if secid == "" || value == nil {
				continue
			}
			if *value > bySecid[secid] {
				bySecid[secid] = *value
			}
		}
		if len(rows) < 100 {
			break
		}
	}
	result := make(map[string]float64)
	for secid, value := range bySecid {
		if isin, ok := secidToISIN[secid]; ok {
			if value > result[isin] {
				result[isin] = value
			}
		}
	}
	log.Printf("Loaded %d previous-session volumes from MOEX history (%s)", len(result), tradeDate.Format("2006-01-02"))
	return result
}

func prevVolumesFromBundle(old *cacheBundle, today time.Time) map[string]float64 {
	if old == nil {
		return nil
	}
	if old.SavedDate.Before(today) {
		prev := make(map[string]float64, len(old.Bonds))
		for isin, row := range old.Bonds {
			if v := parseFloat(row["VALTODAY"]); v != nil {
				prev[isin] = *v
			}
		}
		return prev
	}
	return old.PrevVolumes
}

func parseDate(v any) *time.Time {
	s := strVal(v)
	if s == "" || strings.HasPrefix(s, "0000") {
		return nil
	}
	t, err := time.Parse("2006-01-02", s)
	if err != nil {
		return nil
	}
	return &t
}

func parseFloat(v any) *float64 {
	switch x := v.(type) {
	case float64:
		return &x
	case string:
		if x == "" {
			return nil
		}
		var f float64
		if _, err := fmt.Sscanf(x, "%f", &f); err == nil {
			return &f
		}
	case json.Number:
		if f, err := x.Float64(); err == nil {
			return &f
		}
	}
	return nil
}

func pickYTM(candidates ...any) *float64 {
	for _, c := range candidates {
		if v := parseFloat(c); v != nil && *v > 0 {
			return v
		}
	}
	return nil
}

func prevVolumePtr(v float64) *float64 {
	if v == 0 {
		return nil
	}
	return &v
}

func strVal(v any) string {
	if v == nil {
		return ""
	}
	switch x := v.(type) {
	case string:
		return x
	default:
		return fmt.Sprint(x)
	}
}

var _ bonds.MOEXClient = (*Client)(nil)
