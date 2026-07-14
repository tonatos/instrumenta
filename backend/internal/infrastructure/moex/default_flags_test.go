package moex

import "testing"

func TestParseDefaultFlagsDescription(t *testing.T) {
	body := []byte(`{
  "description": {
    "data": [
      ["ISIN", "ISIN код", "RU000A10CAQ0", "string", 6, 0, null],
      ["HASDEFAULT", "Допущен дефолт", "0", "boolean", 17, 1, 0],
      ["HASTECHNICALDEFAULT", "Допущен технический дефолт", "1", "boolean", 18, 1, 0]
    ]
  }
}`)
	isin, flags, err := parseDefaultFlagsDescription(body)
	if err != nil {
		t.Fatal(err)
	}
	if isin != "RU000A10CAQ0" {
		t.Fatalf("isin = %q", isin)
	}
	if flags.HasDefault {
		t.Fatal("expected HasDefault=false")
	}
	if !flags.HasTechnicalDefault {
		t.Fatal("expected HasTechnicalDefault=true")
	}
}

func TestParseMOEXBool(t *testing.T) {
	if !parseMOEXBool("1") || parseMOEXBool("0") {
		t.Fatal("unexpected bool parse")
	}
}
