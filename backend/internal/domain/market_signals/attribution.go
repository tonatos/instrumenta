package market_signals

import "math"

type Attribution struct {
	BondChange7dPct          float64
	SectorChange7dPct        float64
	MarketChange7dPct        float64
	IdiosyncraticExcess7dPct float64
	Interpretation           string
}

func PriceChangePct(now, past float64) float64 {
	if past == 0 {
		return 0
	}
	return (now - past) / past * 100
}

func BuildAttribution(bondChangePct, sectorChangePct, marketChangePct float64) Attribution {
	idio := bondChangePct - sectorChangePct
	interp := "mixed"
	if sectorChangePct < -10 && math.Abs(idio) < 5 {
		interp = "sector_stress"
	} else if math.Abs(sectorChangePct) < 3 && bondChangePct < -10 {
		interp = "idiosyncratic_drop"
	}
	return Attribution{
		BondChange7dPct: bondChangePct, SectorChange7dPct: sectorChangePct, MarketChange7dPct: marketChangePct,
		IdiosyncraticExcess7dPct: idio, Interpretation: interp,
	}
}

