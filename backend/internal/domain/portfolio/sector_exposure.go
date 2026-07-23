package portfolio

import (
	"sort"
	"strings"

	"github.com/tonatos/instrumenta/backend/internal/domain/bonds"
)

type Exposure struct {
	Key       string
	ValueRub  float64
	Share     float64
	Positions int
}

type exposureAgg struct {
	valueRub  float64
	positions int
}

func exposureKey(raw string) string {
	k := strings.TrimSpace(raw)
	if k == "" {
		return "unknown"
	}
	return strings.ToLower(k)
}

func ExposureBySector(
	universeByISIN map[string]bonds.BondRecord,
	lotsByISIN map[string]int,
	totalValueRub float64,
) []Exposure {
	byKey := make(map[string]*exposureAgg)
	for isin, lots := range lotsByISIN {
		if lots <= 0 {
			continue
		}
		b, ok := universeByISIN[isin]
		if !ok {
			continue
		}
		p := b.PricePerLotRub()
		if p == nil || *p <= 0 {
			continue
		}
		key := exposureKey(b.Sector)
		a := byKey[key]
		if a == nil {
			a = &exposureAgg{}
			byKey[key] = a
		}
		a.valueRub += *p * float64(lots)
		a.positions++
	}
	return exposuresFromAgg(byKey, totalValueRub)
}

func ExposureByIssuer(
	universeByISIN map[string]bonds.BondRecord,
	lotsByISIN map[string]int,
	totalValueRub float64,
) []Exposure {
	byKey := make(map[string]*exposureAgg)
	for isin, lots := range lotsByISIN {
		if lots <= 0 {
			continue
		}
		b, ok := universeByISIN[isin]
		if !ok {
			continue
		}
		p := b.PricePerLotRub()
		if p == nil || *p <= 0 {
			continue
		}
		key := exposureKey(b.IssuerName)
		a := byKey[key]
		if a == nil {
			a = &exposureAgg{}
			byKey[key] = a
		}
		a.valueRub += *p * float64(lots)
		a.positions++
	}
	return exposuresFromAgg(byKey, totalValueRub)
}

func exposuresFromAgg(byKey map[string]*exposureAgg, totalValueRub float64) []Exposure {
	out := make([]Exposure, 0, len(byKey))
	for k, a := range byKey {
		share := 0.0
		if totalValueRub > 0 {
			share = a.valueRub / totalValueRub
		}
		out = append(out, Exposure{
			Key: k, ValueRub: a.valueRub, Share: share, Positions: a.positions,
		})
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].ValueRub == out[j].ValueRub {
			return out[i].Key < out[j].Key
		}
		return out[i].ValueRub > out[j].ValueRub
	})
	return out
}

