package bonds_test

import (
	"testing"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
)

func bondFixture(segid, isin, name string, opts ...func(*bonds.BondRecord)) bonds.BondRecord {
	b := bonds.BondRecord{
		Secid: segid, ISIN: isin, Name: name,
		FaceValue: 1000, LotSize: 1,
		CouponType: bonds.CouponTypeFixed,
	}
	for _, opt := range opts {
		opt(&b)
	}
	return b
}

func TestFilterBondListHideDefaultAndSubordinated(t *testing.T) {
	list := []bonds.BondRecord{
		bondFixture("A", "ISIN-A", "Normal"),
		bondFixture("B", "ISIN-B", "Default", func(b *bonds.BondRecord) { b.HasDefault = true }),
		bondFixture("C", "ISIN-C", "Sub", func(b *bonds.BondRecord) { b.SubordinatedFlag = true }),
	}
	q := bonds.BondListQuery{HideDefault: true, HideSubordinated: true}
	out := bonds.FilterBondList(list, q)
	if len(out) != 1 || out[0].Secid != "A" {
		t.Fatalf("expected only normal bond, got %+v", out)
	}
}

func TestFilterBondListMinVolume(t *testing.T) {
	list := []bonds.BondRecord{
		bondFixture("LOW", "I1", "Low", func(b *bonds.BondRecord) {
			b.PrevVolumeRub = bonds.FloatPtr(100_000)
		}),
		bondFixture("HIGH", "I2", "High", func(b *bonds.BondRecord) {
			b.PrevVolumeRub = bonds.FloatPtr(1_000_000)
		}),
	}
	minVol := 500_000.0
	out := bonds.FilterBondList(list, bonds.BondListQuery{MinVolumeRub: &minVol})
	if len(out) != 1 || out[0].Secid != "HIGH" {
		t.Fatalf("expected high volume bond, got %+v", out)
	}
}

func TestFilterBondListMaxDaysEffective(t *testing.T) {
	list := []bonds.BondRecord{
		bondFixture("SHORT", "I1", "Short", func(b *bonds.BondRecord) {
			b.DaysToMaturity = bonds.IntPtr(90)
		}),
		bondFixture("LONG", "I2", "Long", func(b *bonds.BondRecord) {
			b.DaysToMaturity = bonds.IntPtr(200)
		}),
	}
	maxDays := 120
	out := bonds.FilterBondList(list, bonds.BondListQuery{
		FilterBy: "effective",
		MaxDays:  &maxDays,
	})
	if len(out) != 1 || out[0].Secid != "SHORT" {
		t.Fatalf("expected short bond, got %+v", out)
	}
}

func TestFilterBondListSearch(t *testing.T) {
	list := []bonds.BondRecord{
		bondFixture("SU26238", "RU000A106VN0", "ОФЗ 26238"),
		bondFixture("CORP1", "RU000ACORP1", "Корпоративная"),
	}
	out := bonds.FilterBondList(list, bonds.BondListQuery{Search: "офз"})
	if len(out) != 1 || out[0].Secid != "SU26238" {
		t.Fatalf("expected OFZ match, got %+v", out)
	}
}

func TestFilterBondListSectors(t *testing.T) {
	list := []bonds.BondRecord{
		bondFixture("FIN", "I1", "Financial", func(b *bonds.BondRecord) { b.Sector = "financial" }),
		bondFixture("RE", "I2", "RealEstate", func(b *bonds.BondRecord) { b.Sector = "real_estate" }),
		bondFixture("EMPTY", "I3", "NoSector"),
	}
	out := bonds.FilterBondList(list, bonds.BondListQuery{Sectors: []string{"financial", "real_estate"}})
	if len(out) != 2 {
		t.Fatalf("expected 2 bonds, got %+v", out)
	}
	outOne := bonds.FilterBondList(list, bonds.BondListQuery{Sectors: []string{"financial"}})
	if len(outOne) != 1 || outOne[0].Secid != "FIN" {
		t.Fatalf("expected financial bond only, got %+v", outOne)
	}
}

func TestSortBondListByYTMNet(t *testing.T) {
	list := []bonds.BondRecord{
		bondFixture("A", "I1", "A", func(b *bonds.BondRecord) { b.YTMNet = bonds.FloatPtr(10) }),
		bondFixture("B", "I2", "B", func(b *bonds.BondRecord) { b.YTMNet = bonds.FloatPtr(15) }),
	}
	out := bonds.SortBondList(list, bonds.BondListQuery{SortBy: "ytm_net", SortDesc: true})
	if out[0].Secid != "B" {
		t.Fatalf("expected B first, got %s", out[0].Secid)
	}
}

func TestPaginateBondList(t *testing.T) {
	list := make([]bonds.BondRecord, 5)
	for i := range list {
		list[i] = bondFixture("B"+string(rune('0'+i)), "I", "X")
	}
	page, total := bonds.PaginateBondList(list, bonds.BondListQuery{Page: 2, PageSize: 2})
	if total != 5 || len(page) != 2 {
		t.Fatalf("expected page 2 with 2 items, total 5, got len=%d total=%d", len(page), total)
	}
}

func TestNormalizeBondListQuery(t *testing.T) {
	q := bonds.NormalizeBondListQuery(bonds.BondListQuery{})
	if q.Page != 1 || q.PageSize != bonds.DefaultBondListPageSize {
		t.Fatalf("unexpected defaults: page=%d size=%d", q.Page, q.PageSize)
	}
}
