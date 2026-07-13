package tinvest

import (
	"crypto/x509"
	"os"
	"testing"
)

func TestEmbeddedRussianTrustedRootCA_Parseable(t *testing.T) {
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(russianTrustedRootCAPEM) {
		t.Fatal("embedded Russian Trusted Root CA is not valid PEM")
	}
}

func TestTBankTLSCAFile_WritesEmbeddedCert(t *testing.T) {
	path, err := tbankTLSCAFile()
	if err != nil {
		t.Fatalf("tbankTLSCAFile: %v", err)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read CA file: %v", err)
	}
	if string(data) != string(russianTrustedRootCAPEM) {
		t.Fatal("CA file content does not match embedded cert")
	}
}

func TestVerifyTBankRootCA_Live(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping live TLS check in short mode")
	}
	if err := verifyTBankRootCA(); err != nil {
		t.Fatalf("verify T-Bank TLS with embedded CA: %v", err)
	}
}
