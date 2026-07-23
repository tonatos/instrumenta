package notifications

import "testing"

func TestParseBotCommand(t *testing.T) {
	cmd, args := ParseBotCommand("/start")
	if cmd != "/start" || args != "" {
		t.Fatalf("got %q %q", cmd, args)
	}
	cmd, args = ParseBotCommand("/start@MyBot hello")
	if cmd != "/start" || args != "hello" {
		t.Fatalf("got %q %q", cmd, args)
	}
	cmd, args = ParseBotCommand("/STOP")
	if cmd != "/stop" {
		t.Fatalf("got %q", cmd)
	}
}

func TestBotDeepLink(t *testing.T) {
	if got := BotDeepLink("bond_monitor_bot"); got != "https://t.me/bond_monitor_bot" {
		t.Fatalf("got %q", got)
	}
	if got := BotDeepLink("@x"); got != "https://t.me/x" {
		t.Fatalf("got %q", got)
	}
	if BotDeepLink("") != "" {
		t.Fatal("expected empty")
	}
}
