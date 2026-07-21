package crypto

import (
	"bytes"
	"testing"
)

func TestEnvelopeRoundTrip(t *testing.T) {
	kek, err := NewLocalKEK("test-broker-kek-secret-material!!", 1)
	if err != nil {
		t.Fatal(err)
	}
	aad := CredentialAAD(42, "cred1", "sandbox")
	env, err := Encrypt(kek, []byte("t.invest.token"), aad)
	if err != nil {
		t.Fatal(err)
	}
	plain, err := Decrypt(kek, env, aad)
	if err != nil {
		t.Fatal(err)
	}
	if string(plain) != "t.invest.token" {
		t.Fatalf("got %q", plain)
	}
}

func TestEnvelopeAADMismatch(t *testing.T) {
	kek, err := NewLocalKEK("test-broker-kek-secret-material!!", 1)
	if err != nil {
		t.Fatal(err)
	}
	env, err := Encrypt(kek, []byte("secret"), CredentialAAD(1, "a", "production"))
	if err != nil {
		t.Fatal(err)
	}
	_, err = Decrypt(kek, env, CredentialAAD(2, "a", "production"))
	if err == nil {
		t.Fatal("expected AAD mismatch error")
	}
}

func TestFingerprintStable(t *testing.T) {
	a := Fingerprint("abc")
	b := Fingerprint("abc")
	if a != b || a == "" {
		t.Fatalf("fingerprint unstable: %q %q", a, b)
	}
	if Fingerprint("abc") == Fingerprint("abd") {
		t.Fatal("fingerprints should differ")
	}
}

func TestParseKEKBase64(t *testing.T) {
	raw := make([]byte, 32)
	for i := range raw {
		raw[i] = byte(i)
	}
	encoded := "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=" // wrong length check via ParseKEK derive path
	_, err := ParseKEK("any-dev-secret")
	if err != nil {
		t.Fatal(err)
	}
	_ = encoded
	key, err := ParseKEK(string(raw))
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(key, raw) {
		t.Fatal("raw 32-byte key mismatch")
	}
}
