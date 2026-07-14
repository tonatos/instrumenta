package ratings

import "testing"

func TestNormalizeRating(t *testing.T) {
	tests := []struct {
		in   string
		want string
		ok   bool
	}{
		{"BB+", "ruBB+", true},
		{"CC", "ruCC", true},
		{"ruAA+", "ruAA+", true},
		{"AAA", "ruAAA", true},
		{"", "", false},
		{"—", "", false},
		{"нет", "", false},
		{"unknown", "", false},
	}
	for _, tc := range tests {
		got, ok := NormalizeRating(tc.in)
		if ok != tc.ok || got != tc.want {
			t.Fatalf("NormalizeRating(%q) = (%q, %v), want (%q, %v)", tc.in, got, ok, tc.want, tc.ok)
		}
	}
}
