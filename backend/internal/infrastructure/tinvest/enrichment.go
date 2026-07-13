package tinvest

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	pb "github.com/russianinvestments/invest-api-go-sdk/proto"
	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/paths"
	"google.golang.org/protobuf/types/known/timestamppb"
)

const (
	bondsCacheTTLSeconds     = 15 * 60
	metadataCacheTTLSeconds  = 7 * 24 * 60 * 60
	couponScheduleDaysAhead  = 365
)

type tinvestBondData struct {
	FIGI                   string    `json:"figi"`
	FloatingCouponFlag     bool      `json:"floating_coupon_flag"`
	AmortizationFlag       bool      `json:"amortization_flag"`
	PerpetualFlag          bool      `json:"perpetual_flag"`
	SubordinatedFlag       bool      `json:"subordinated_flag"`
	ForQualInvestorFlag    bool      `json:"for_qual_investor_flag"`
	LiquidityFlag          bool      `json:"liquidity_flag"`
	APITradeAvailableFlag  bool      `json:"api_trade_available_flag"`
	CallDate               *string   `json:"call_date,omitempty"`
	RiskLevel              int       `json:"risk_level"`
	InstrumentFullName     string    `json:"instrument_full_name"`
	Sector                 string    `json:"sector"`
	AssetUID               string    `json:"asset_uid"`
}

type assetMetadata struct {
	IssuerName  string `json:"issuer_name"`
	Description string `json:"description"`
	Sector      string `json:"sector"`
}

type bondsDiskCache struct {
	CachedAt float64                       `json:"cached_at"`
	Bonds    map[string]tinvestBondData      `json:"bonds"`
}

type metadataCacheEntry struct {
	CachedAt    float64 `json:"cached_at"`
	IssuerName  string  `json:"issuer_name"`
	Description string  `json:"description"`
	Sector      string  `json:"sector"`
}

type bondsDataCache struct {
	mu       sync.RWMutex
	token    string
	api      *investAPI
	loadedAt time.Time
	data     map[string]tinvestBondData
}

func newBondsDataCache(token string) *bondsDataCache {
	return &bondsDataCache{
		token: token,
		api:   newInvestAPI(token, productionEndpoint),
	}
}

func bondsCachePath() string {
	return filepath.Join(paths.CacheDir(), "tinvest_bonds.json")
}

func metadataCachePath() string {
	return filepath.Join(paths.CacheDir(), "tinvest_asset_metadata.json")
}

func assetIndexCachePath() string {
	return filepath.Join(paths.CacheDir(), "tinvest_asset_index.json")
}

func protoDate(ts *timestamppb.Timestamp) *time.Time {
	if ts == nil || ts.GetSeconds() <= 0 {
		return nil
	}
	t := ts.AsTime().UTC()
	d := time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC)
	return &d
}

func mapRiskLevel(raw pb.RiskLevel) bonds.RiskLevel {
	switch raw {
	case pb.RiskLevel_RISK_LEVEL_LOW:
		return bonds.RiskLevelLow
	case pb.RiskLevel_RISK_LEVEL_MODERATE:
		return bonds.RiskLevelModerate
	case pb.RiskLevel_RISK_LEVEL_HIGH:
		return bonds.RiskLevelHigh
	default:
		return bonds.RiskLevelUnknown
	}
}

func mapCouponType(raw int32) bonds.CouponType {
	switch pb.CouponType(raw) {
	case pb.CouponType_COUPON_TYPE_CONSTANT, pb.CouponType_COUPON_TYPE_FIX:
		return bonds.CouponTypeFixed
	case pb.CouponType_COUPON_TYPE_FLOATING:
		return bonds.CouponTypeFloating
	case pb.CouponType_COUPON_TYPE_VARIABLE, pb.CouponType_COUPON_TYPE_OTHER:
		return bonds.CouponTypeVariable
	default:
		return bonds.CouponTypeUnknown
	}
}

func couponTypeFromFloating(floating bool) bonds.CouponType {
	if floating {
		return bonds.CouponTypeFloating
	}
	return bonds.CouponTypeFixed
}

func firstNonEmpty(values ...string) string {
	for _, v := range values {
		if strings.TrimSpace(v) != "" {
			return v
		}
	}
	return ""
}

func (c *bondsDataCache) loadDisk() (map[string]tinvestBondData, bool) {
	raw, err := os.ReadFile(bondsCachePath())
	if err != nil {
		return nil, false
	}
	var payload bondsDiskCache
	if err := json.Unmarshal(raw, &payload); err != nil || payload.Bonds == nil {
		return nil, false
	}
	if time.Since(time.Unix(int64(payload.CachedAt), 0)) >= bondsCacheTTLSeconds*time.Second {
		return nil, false
	}
	return payload.Bonds, true
}

func (c *bondsDataCache) saveDisk(data map[string]tinvestBondData) {
	_ = os.MkdirAll(paths.CacheDir(), 0o755)
	payload := bondsDiskCache{
		CachedAt: float64(time.Now().Unix()),
		Bonds:    data,
	}
	raw, err := json.Marshal(payload)
	if err != nil {
		return
	}
	_ = os.WriteFile(bondsCachePath(), raw, 0o644)
}

func (c *bondsDataCache) fetchFromAPI(ctx context.Context) (map[string]tinvestBondData, error) {
	client, err := c.api.connect(ctx)
	if err != nil {
		return nil, err
	}
	status := pb.InstrumentStatus_INSTRUMENT_STATUS_BASE
	resp, err := client.NewInstrumentsServiceClient().Bonds(status)
	if err != nil {
		return nil, mapRPCError(err, "")
	}
	out := make(map[string]tinvestBondData, len(resp.GetInstruments()))
	for _, ins := range resp.GetInstruments() {
		isin := strings.TrimSpace(ins.GetIsin())
		if isin == "" {
			continue
		}
		var callDate *string
		if d := protoDate(ins.GetCallDate()); d != nil {
			s := d.Format("2006-01-02")
			callDate = &s
		}
		out[isin] = tinvestBondData{
			FIGI:                  ins.GetFigi(),
			FloatingCouponFlag:    ins.GetFloatingCouponFlag(),
			AmortizationFlag:      ins.GetAmortizationFlag(),
			PerpetualFlag:         ins.GetPerpetualFlag(),
			SubordinatedFlag:      ins.GetSubordinatedFlag(),
			ForQualInvestorFlag:   ins.GetForQualInvestorFlag(),
			LiquidityFlag:         ins.GetLiquidityFlag(),
			APITradeAvailableFlag: ins.GetApiTradeAvailableFlag(),
			CallDate:              callDate,
			RiskLevel:             int(mapRiskLevel(ins.GetRiskLevel())),
			InstrumentFullName:    ins.GetName(),
			Sector:                ins.GetSector(),
			AssetUID:              ins.GetAssetUid(),
		}
	}
	packageLogger.Info("T-Invest: loaded bonds from API", "count", len(out))
	return out, nil
}

func (c *bondsDataCache) get(ctx context.Context) (map[string]tinvestBondData, error) {
	c.mu.RLock()
	if c.data != nil && time.Since(c.loadedAt) < bondsCacheTTLSeconds*time.Second {
		data := c.data
		c.mu.RUnlock()
		return data, nil
	}
	c.mu.RUnlock()

	c.mu.Lock()
	defer c.mu.Unlock()
	if c.data != nil && time.Since(c.loadedAt) < bondsCacheTTLSeconds*time.Second {
		return c.data, nil
	}
	if disk, ok := c.loadDisk(); ok {
		c.data = disk
		c.loadedAt = time.Now()
		return c.data, nil
	}
	data, err := c.fetchFromAPI(ctx)
	if err != nil {
		return nil, err
	}
	c.data = data
	c.loadedAt = time.Now()
	c.saveDisk(data)
	return data, nil
}

func applyTInvestData(bond *bonds.BondRecord, data tinvestBondData) {
	bond.FIGI = data.FIGI
	bond.FloatingCouponFlag = data.FloatingCouponFlag
	bond.AmortizationFlag = data.AmortizationFlag
	bond.PerpetualFlag = data.PerpetualFlag
	bond.SubordinatedFlag = data.SubordinatedFlag
	bond.ForQualInvestorFlag = data.ForQualInvestorFlag
	bond.LiquidityFlag = data.LiquidityFlag
	tradable := data.APITradeAvailableFlag
	bond.APITradeAvailableFlag = &tradable
	if data.CallDate != nil {
		if t, err := time.Parse("2006-01-02", *data.CallDate); err == nil {
			bond.CallDate = &t
		}
	}
	bond.RiskLevel = bonds.RiskLevel(data.RiskLevel)
	bond.InstrumentFullName = data.InstrumentFullName
	bond.Sector = data.Sector
	bond.AssetUID = data.AssetUID
	bond.TInvestEnriched = true
	if bond.CouponType == bonds.CouponTypeUnknown || bond.CouponType == "" {
		bond.CouponType = couponTypeFromFloating(data.FloatingCouponFlag)
	}
}

func enrichBondsFromAPI(ctx context.Context, cache *bondsDataCache, bs []bonds.BondRecord) []bonds.BondRecord {
	apiData, err := cache.get(ctx)
	if err != nil {
		packageLogger.Error("T-Invest enrichment failed", "error", err)
		return applyFallbackTradeFlags(bs)
	}
	matched := 0
	for i := range bs {
		data, ok := apiData[bs[i].ISIN]
		if !ok {
			applyFallbackTradeFlag(&bs[i])
			continue
		}
		applyTInvestData(&bs[i], data)
		matched++
	}
	packageLogger.Info("T-Invest enrichment", "matched", matched, "total", len(bs))
	return bs
}

func loadJSONCache(path string) map[string]json.RawMessage {
	raw, err := os.ReadFile(path)
	if err != nil {
		return map[string]json.RawMessage{}
	}
	var data map[string]json.RawMessage
	if err := json.Unmarshal(raw, &data); err != nil {
		return map[string]json.RawMessage{}
	}
	return data
}

func saveJSONCache(path string, data map[string]json.RawMessage) {
	_ = os.MkdirAll(filepath.Dir(path), 0o755)
	raw, err := json.MarshalIndent(data, "", "  ")
	if err != nil {
		return
	}
	_ = os.WriteFile(path, raw, 0o644)
}

func metadataCacheGet(isin string) *assetMetadata {
	entryRaw, ok := loadJSONCache(metadataCachePath())[strings.ToUpper(isin)]
	if !ok {
		return nil
	}
	var entry metadataCacheEntry
	if err := json.Unmarshal(entryRaw, &entry); err != nil {
		return nil
	}
	if time.Since(time.Unix(int64(entry.CachedAt), 0)) > metadataCacheTTLSeconds*time.Second {
		return nil
	}
	return &assetMetadata{
		IssuerName:  entry.IssuerName,
		Description: entry.Description,
		Sector:      entry.Sector,
	}
}

func metadataCachePut(isin string, meta assetMetadata) {
	cache := loadJSONCache(metadataCachePath())
	payload, _ := json.Marshal(metadataCacheEntry{
		CachedAt:    float64(time.Now().Unix()),
		IssuerName:  meta.IssuerName,
		Description: meta.Description,
		Sector:      meta.Sector,
	})
	cache[strings.ToUpper(isin)] = payload
	saveJSONCache(metadataCachePath(), cache)
}

func parseAssetMetadata(asset *pb.AssetFull) assetMetadata {
	if asset == nil {
		return assetMetadata{}
	}
	meta := assetMetadata{Description: asset.GetDescription()}
	if brand := asset.GetBrand(); brand != nil {
		meta.Sector = brand.GetSector()
		meta.IssuerName = firstNonEmpty(brand.GetCompany(), brand.GetName())
		if meta.Description == "" {
			meta.Description = brand.GetDescription()
		}
	}
	if security := asset.GetSecurity(); security != nil {
		if bond := security.GetBond(); bond != nil {
			meta.IssuerName = firstNonEmpty(bond.GetBorrowName(), meta.IssuerName)
		}
	}
	return meta
}

func fetchAssetMetadata(ctx context.Context, api *investAPI, assetUID string) assetMetadata {
	if assetUID == "" {
		return assetMetadata{}
	}
	client, err := api.connect(ctx)
	if err != nil {
		return assetMetadata{}
	}
	resp, err := client.NewInstrumentsServiceClient().GetAssetBy(assetUID)
	if err != nil {
		packageLogger.Debug("get_asset_by failed", "asset_uid", assetUID, "error", err)
		return assetMetadata{}
	}
	return parseAssetMetadata(resp.GetAsset())
}

func enrichBondDetailMetadata(ctx context.Context, api *investAPI, bond *bonds.BondRecord) {
	if bond == nil || bond.ISIN == "" {
		return
	}
	if cached := metadataCacheGet(bond.ISIN); cached != nil {
		bond.IssuerName = firstNonEmpty(cached.IssuerName, bond.InstrumentFullName, bond.Name)
		bond.Description = cached.Description
		if cached.Sector != "" && bond.Sector == "" {
			bond.Sector = cached.Sector
		}
		return
	}
	assetUID := bond.AssetUID
	if assetUID == "" {
		return
	}
	meta := fetchAssetMetadata(ctx, api, assetUID)
	if meta.IssuerName != "" || meta.Description != "" || meta.Sector != "" {
		metadataCachePut(bond.ISIN, meta)
	}
	bond.IssuerName = firstNonEmpty(meta.IssuerName, bond.InstrumentFullName, bond.Name)
	bond.Description = meta.Description
	if meta.Sector != "" && bond.Sector == "" {
		bond.Sector = meta.Sector
	}
}

func resolveCouponTypeFromSchedule(payments []bonds.CouponPayment) bonds.CouponType {
	if len(payments) == 0 {
		return bonds.CouponTypeUnknown
	}
	counts := map[int32]int{}
	for _, p := range payments {
		counts[int32(p.CouponTypeRaw)]++
	}
	var dominant int32
	maxCount := 0
	for raw, count := range counts {
		if count > maxCount {
			maxCount = count
			dominant = raw
		}
	}
	return mapCouponType(dominant)
}

func fetchCouponSchedule(ctx context.Context, api *investAPI, figi string) []bonds.CouponPayment {
	if figi == "" {
		return nil
	}
	client, err := api.connect(ctx)
	if err != nil {
		return nil
	}
	from := time.Now().UTC()
	to := from.Add(couponScheduleDaysAhead * 24 * time.Hour)
	resp, err := client.NewInstrumentsServiceClient().GetBondCoupons(figi, from, to)
	if err != nil {
		packageLogger.Debug("get_bond_coupons failed", "figi", figi, "error", err)
		return nil
	}
	var payments []bonds.CouponPayment
	for _, event := range resp.GetEvents() {
		var amount *float64
		if mv := event.GetPayOneBond(); mv != nil {
			v := mv.ToFloat()
			amount = &v
		}
		payments = append(payments, bonds.CouponPayment{
			PaymentDate:   protoDate(event.GetCouponDate()),
			AmountRub:     amount,
			CouponTypeRaw: int(event.GetCouponType()),
		})
	}
	return payments
}

// InvalidateBondsCache clears T-Invest GetBonds disk and RAM cache.
func InvalidateBondsCache() {
	_ = os.Remove(bondsCachePath())
}
