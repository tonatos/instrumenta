package tinvest

import (
	_ "embed"
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
)

// Russian Trusted Root CA (НУЦ Минцифры РФ) required for *.tbank.ru TLS.
// See https://developer.tbank.ru/invest/intro/developer/network
//
//go:embed certs/russian_trusted_root_ca.pem
var russianTrustedRootCAPEM []byte

var (
	tbankCAPathOnce sync.Once
	tbankCAPath     string
	tbankCAPathErr  error
)

func tbankTLSCAFile() (string, error) {
	if override := strings.TrimSpace(os.Getenv("TINVEST_TLS_CA_FILE")); override != "" {
		return override, nil
	}
	tbankCAPathOnce.Do(func() {
		path := filepath.Join(os.TempDir(), "bond-monitor-russian-trusted-root-ca.pem")
		tbankCAPathErr = os.WriteFile(path, russianTrustedRootCAPEM, 0o644)
		tbankCAPath = path
	})
	return tbankCAPath, tbankCAPathErr
}

func tbankTLSInsecureSkipVerify() bool {
	v := strings.ToLower(strings.TrimSpace(os.Getenv("TINVEST_TLS_INSECURE_SKIP_VERIFY")))
	switch v {
	case "1", "true", "yes", "on":
		return true
	default:
		return false
	}
}

func verifyTBankRootCA() error {
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(russianTrustedRootCAPEM) {
		return fmt.Errorf("parse embedded Russian Trusted Root CA")
	}
	conn, err := tls.Dial("tcp", productionEndpoint, &tls.Config{
		ServerName: strings.Split(productionEndpoint, ":")[0],
		RootCAs:    pool,
	})
	if err != nil {
		return err
	}
	return conn.Close()
}
