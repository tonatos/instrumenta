package notifications

import (
	"strings"
	"testing"
)

func TestFormatAndParseSupportRelayMessage(t *testing.T) {
	msg := FormatSupportRelayMessage(139693774, "alice", "Pro", "Не проходит оплата")
	want := "Support tg_id=139693774\n@alice · Pro\n---\nНе проходит оплата"
	if msg != want {
		t.Fatalf("format:\n got %q\nwant %q", msg, want)
	}
	id, ok := ParseSupportTgID(msg)
	if !ok || id != 139693774 {
		t.Fatalf("parse got %d ok=%v", id, ok)
	}
}

func TestParseSupportTgID_RejectsGarbage(t *testing.T) {
	if _, ok := ParseSupportTgID("hello"); ok {
		t.Fatal("expected false")
	}
	if _, ok := ParseSupportTgID("Support tg_id=0\n---\nx"); ok {
		t.Fatal("zero id")
	}
}

func TestFormatSupportRelayMessage_NoUsername(t *testing.T) {
	msg := FormatSupportRelayMessage(42, "", "", "hi")
	if msg != "Support tg_id=42\nfree\n---\nhi" {
		t.Fatalf("got %q", msg)
	}
}

func TestSupportDeepLink(t *testing.T) {
	if got := SupportDeepLink("https://t.me/bot"); got != "https://t.me/bot?start=support" {
		t.Fatalf("got %q", got)
	}
	if got := SupportDeepLink("https://t.me/bot?start=support"); got != "https://t.me/bot?start=support" {
		t.Fatalf("idempotent: %q", got)
	}
	if got := SupportDeepLink(""); got != "" {
		t.Fatalf("empty: %q", got)
	}
	if got := SupportDeepLink("https://t.me/bot?foo=1"); !strings.HasPrefix(got, "https://t.me/bot?start=support") {
		t.Fatalf("got %q", got)
	}
}
