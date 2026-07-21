package bonds

import (
	"testing"
	"time"
)

func date(s string) time.Time {
	t, err := time.Parse("2006-01-02", s)
	if err != nil {
		panic(err)
	}
	return t
}

func datePtr(s string) *time.Time {
	t := date(s)
	return &t
}

func TestApplyOfferWindow_FillsMissingFields(t *testing.T) {
	bond := BondRecord{ISIN: "RU000A109874", OfferDate: datePtr("2026-08-07")}
	price := 100.0
	changed := ApplyOfferWindow(&bond, OfferWindowData{
		OfferDate:       datePtr("2026-08-07"),
		SubmissionStart: datePtr("2026-07-28"),
		SubmissionEnd:   datePtr("2026-08-04"),
		PricePct:        &price,
	})
	if !changed {
		t.Fatal("expected change")
	}
	if bond.OfferSubmissionStart == nil || !bond.OfferSubmissionStart.Equal(date("2026-07-28")) {
		t.Fatalf("start = %v", bond.OfferSubmissionStart)
	}
	if bond.OfferSubmissionEnd == nil || !bond.OfferSubmissionEnd.Equal(date("2026-08-04")) {
		t.Fatalf("end = %v", bond.OfferSubmissionEnd)
	}
	if bond.OfferPricePct == nil || *bond.OfferPricePct != 100 {
		t.Fatalf("price = %v", bond.OfferPricePct)
	}
}

func TestApplyOfferWindow_DoesNotOverwriteExisting(t *testing.T) {
	bond := BondRecord{
		OfferDate:            datePtr("2026-08-07"),
		OfferSubmissionStart: datePtr("2026-07-28"),
		OfferSubmissionEnd:   datePtr("2026-08-04"),
	}
	price := 100.0
	other := 99.0
	changed := ApplyOfferWindow(&bond, OfferWindowData{
		OfferDate:       datePtr("2026-08-07"),
		SubmissionStart: datePtr("2026-07-01"),
		SubmissionEnd:   datePtr("2026-07-02"),
		PricePct:        &price,
	})
	if !changed {
		t.Fatal("price fill should change")
	}
	if !bond.OfferSubmissionStart.Equal(date("2026-07-28")) {
		t.Fatal("start overwritten")
	}
	if !bond.OfferSubmissionEnd.Equal(date("2026-08-04")) {
		t.Fatal("end overwritten")
	}
	_ = other
	if bond.OfferPricePct == nil || *bond.OfferPricePct != 100 {
		t.Fatalf("price = %v", bond.OfferPricePct)
	}
}

func TestApplyOfferWindow_RejectsMismatchedOfferDate(t *testing.T) {
	bond := BondRecord{OfferDate: datePtr("2026-08-07")}
	changed := ApplyOfferWindow(&bond, OfferWindowData{
		OfferDate:     datePtr("2025-02-05"),
		SubmissionEnd: datePtr("2025-02-03"),
	})
	if changed {
		t.Fatal("expected no change for past offer")
	}
	if bond.OfferSubmissionEnd != nil {
		t.Fatal("past offer window applied")
	}
}

func TestApplyOfferWindow_PriceOnlyWhenDatesMissing(t *testing.T) {
	bond := BondRecord{OfferDate: datePtr("2026-08-07")}
	price := 100.0
	changed := ApplyOfferWindow(&bond, OfferWindowData{
		OfferDate: datePtr("2026-08-07"),
		PricePct:  &price,
	})
	if !changed {
		t.Fatal("expected price apply")
	}
	if bond.OfferPricePct == nil || *bond.OfferPricePct != 100 {
		t.Fatalf("price = %v", bond.OfferPricePct)
	}
	if bond.OfferSubmissionStart != nil || bond.OfferSubmissionEnd != nil {
		t.Fatal("dates should stay nil")
	}
}

func TestSelectOfferWindow_PrefersMatchingOfferDate(t *testing.T) {
	offers := []OfferWindowData{
		{OfferDate: datePtr("2025-02-05"), SubmissionStart: datePtr("2025-01-28"), SubmissionEnd: datePtr("2025-02-03")},
		{OfferDate: datePtr("2026-08-07"), SubmissionStart: datePtr("2026-07-28"), SubmissionEnd: datePtr("2026-08-04")},
	}
	got := SelectOfferWindow(offers, datePtr("2026-08-07"), date("2026-07-20"))
	if got == nil || !got.OfferDate.Equal(date("2026-08-07")) {
		t.Fatalf("got %#v", got)
	}
}

func TestSelectOfferWindow_SkipsPastWhenNoPrefer(t *testing.T) {
	offers := []OfferWindowData{
		{OfferDate: datePtr("2025-02-05"), SubmissionEnd: datePtr("2025-02-03")},
		{OfferDate: datePtr("2026-08-07"), SubmissionEnd: datePtr("2026-08-04")},
	}
	got := SelectOfferWindow(offers, nil, date("2026-07-20"))
	if got == nil || !got.OfferDate.Equal(date("2026-08-07")) {
		t.Fatalf("got %#v", got)
	}
}

func TestOfferWindowStatusFor_PartialWindowIsUnknown(t *testing.T) {
	// fixDate-only from T-Invest is not a full issuer/broker window
	status := OfferWindowStatusFor(datePtr("2026-08-07"), nil, datePtr("2026-08-04"), date("2026-07-20"))
	if status == nil || *status != OfferWindowUnknown {
		t.Fatalf("status = %v, want unknown when start is missing", status)
	}
	status = OfferWindowStatusFor(datePtr("2026-08-07"), datePtr("2026-07-28"), nil, date("2026-07-20"))
	if status == nil || *status != OfferWindowUnknown {
		t.Fatalf("status = %v, want unknown when end is missing", status)
	}
}

func TestOfferWindowStatusFor_FullWindow(t *testing.T) {
	notOpen := OfferWindowStatusFor(
		datePtr("2026-08-07"), datePtr("2026-07-28"), datePtr("2026-07-31"), date("2026-07-20"),
	)
	if notOpen == nil || *notOpen != OfferWindowNotOpen {
		t.Fatalf("status = %v, want not_open", notOpen)
	}
	open := OfferWindowStatusFor(
		datePtr("2026-08-07"), datePtr("2026-07-28"), datePtr("2026-07-31"), date("2026-07-29"),
	)
	if open == nil || *open != OfferWindowOpen {
		t.Fatalf("status = %v, want open", open)
	}
}
