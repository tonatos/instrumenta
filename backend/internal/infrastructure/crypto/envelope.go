package crypto

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"strings"
)

var (
	ErrInvalidKEK     = errors.New("invalid broker KEK")
	ErrDecryptFailed  = errors.New("decrypt failed")
	ErrEmptyPlaintext = errors.New("empty plaintext")
)

// KeyWrapper wraps/unwraps data encryption keys (DEK).
type KeyWrapper interface {
	Wrap(dek []byte) ([]byte, error)
	Unwrap(wrapped []byte) ([]byte, error)
	Version() int
}

// LocalKEK is an app-level AES-256-GCM KEK from BROKER_KEK.
type LocalKEK struct {
	key     []byte
	version int
}

// ParseKEK accepts raw 32 bytes, base64, or hex of 32 bytes.
func ParseKEK(raw string) ([]byte, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return nil, fmt.Errorf("%w: empty", ErrInvalidKEK)
	}
	if decoded, err := base64.StdEncoding.DecodeString(raw); err == nil && len(decoded) == 32 {
		return decoded, nil
	}
	if decoded, err := hex.DecodeString(raw); err == nil && len(decoded) == 32 {
		return decoded, nil
	}
	if len(raw) == 32 {
		return []byte(raw), nil
	}
	// Derive a stable 32-byte key from arbitrary secret material (dev convenience).
	sum := sha256.Sum256([]byte(raw))
	return sum[:], nil
}

func NewLocalKEK(raw string, version int) (*LocalKEK, error) {
	key, err := ParseKEK(raw)
	if err != nil {
		return nil, err
	}
	if version <= 0 {
		version = 1
	}
	return &LocalKEK{key: key, version: version}, nil
}

func (k *LocalKEK) Version() int { return k.version }

func (k *LocalKEK) Wrap(dek []byte) ([]byte, error) {
	return gcmSeal(k.key, dek, nil)
}

func (k *LocalKEK) Unwrap(wrapped []byte) ([]byte, error) {
	return gcmOpen(k.key, wrapped, nil)
}

// Envelope is ciphertext produced by Encrypt.
type Envelope struct {
	Ciphertext []byte
	DEKWrapped []byte
	Nonce      []byte // unused externally; nonce is embedded in ciphertext blobs
	KEKVersion int
}

// Encrypt seals plaintext with a random DEK; DEK is wrapped by KEK. AAD binds ciphertext to tenant.
func Encrypt(wrapper KeyWrapper, plaintext, aad []byte) (Envelope, error) {
	if len(plaintext) == 0 {
		return Envelope{}, ErrEmptyPlaintext
	}
	dek := make([]byte, 32)
	if _, err := io.ReadFull(rand.Reader, dek); err != nil {
		return Envelope{}, err
	}
	ciphertext, err := gcmSeal(dek, plaintext, aad)
	if err != nil {
		return Envelope{}, err
	}
	wrapped, err := wrapper.Wrap(dek)
	if err != nil {
		return Envelope{}, err
	}
	return Envelope{
		Ciphertext: ciphertext,
		DEKWrapped: wrapped,
		KEKVersion: wrapper.Version(),
	}, nil
}

// Decrypt opens an envelope. AAD must match Encrypt.
func Decrypt(wrapper KeyWrapper, env Envelope, aad []byte) ([]byte, error) {
	dek, err := wrapper.Unwrap(env.DEKWrapped)
	if err != nil {
		return nil, fmt.Errorf("%w: unwrap dek: %v", ErrDecryptFailed, err)
	}
	plain, err := gcmOpen(dek, env.Ciphertext, aad)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrDecryptFailed, err)
	}
	return plain, nil
}

// Fingerprint returns a short non-secret token fingerprint for UI.
func Fingerprint(token string) string {
	sum := sha256.Sum256([]byte(token))
	return hex.EncodeToString(sum[:8])
}

// CredentialAAD builds GCM associated data for a broker credential row.
func CredentialAAD(ownerTelegramID int64, credentialID, accountKind string) []byte {
	return []byte(fmt.Sprintf("%d|%s|%s", ownerTelegramID, credentialID, accountKind))
}

func gcmSeal(key, plaintext, aad []byte) ([]byte, error) {
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, err
	}
	nonce := make([]byte, gcm.NonceSize())
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return nil, err
	}
	return gcm.Seal(nonce, nonce, plaintext, aad), nil
}

func gcmOpen(key, sealed, aad []byte) ([]byte, error) {
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, err
	}
	if len(sealed) < gcm.NonceSize() {
		return nil, ErrDecryptFailed
	}
	nonce, ciphertext := sealed[:gcm.NonceSize()], sealed[gcm.NonceSize():]
	return gcm.Open(nil, nonce, ciphertext, aad)
}
