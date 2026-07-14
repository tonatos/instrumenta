package persistence

import (
	"context"
	"database/sql"
	"errors"
	"strings"
	"time"

	"github.com/jmoiron/sqlx"
)

const (
	RatingSourceSmartLab = "smartlab"
	RatingSourceManual   = "manual"
	DefaultSourceMOEX    = "moex"
	DefaultSourceManual  = "manual"

	SettingBondRatingsScrapedAt    = "bond_ratings_scraped_at"
	SettingBondDefaultsRefreshedAt = "bond_defaults_refreshed_at"
)

// BondCreditRating is one ISIN credit rating row.
type BondCreditRating struct {
	ISIN      string    `db:"isin"`
	Rating    string    `db:"rating"`
	Source    string    `db:"source"`
	UpdatedAt time.Time `db:"updated_at"`
}

// BondDefaultFlagRow is one ISIN default flag row.
type BondDefaultFlagRow struct {
	ISIN                string    `db:"isin"`
	HasDefault          bool      `db:"has_default"`
	HasTechnicalDefault bool      `db:"has_technical_default"`
	Source              string    `db:"source"`
	UpdatedAt           time.Time `db:"updated_at"`
}

// BondReferenceRepository stores bond credit ratings and default flags.
type BondReferenceRepository struct {
	db *sqlx.DB
}

func NewBondReferenceRepository(db *sqlx.DB) *BondReferenceRepository {
	return &BondReferenceRepository{db: db}
}

func (r *BondReferenceRepository) UpsertSmartLabRatings(ctx context.Context, ratings map[string]string) (int, error) {
	if len(ratings) == 0 {
		return 0, nil
	}
	now := time.Now().UTC()
	tx, err := r.db.BeginTxx(ctx, nil)
	if err != nil {
		return 0, err
	}
	defer func() { _ = tx.Rollback() }()

	count := 0
	for isin, rating := range ratings {
		isin = strings.ToUpper(strings.TrimSpace(isin))
		rating = strings.TrimSpace(rating)
		if isin == "" || rating == "" {
			continue
		}
		_, err := tx.ExecContext(ctx, `
INSERT INTO bond_credit_ratings (isin, rating, source, updated_at)
VALUES ($1, $2, $3, $4)
ON CONFLICT (isin) DO UPDATE SET
  rating = excluded.rating,
  source = excluded.source,
  updated_at = excluded.updated_at
WHERE bond_credit_ratings.source != $5`,
			isin, rating, RatingSourceSmartLab, now, RatingSourceManual,
		)
		if err != nil {
			return count, err
		}
		count++
	}
	if err := r.setSettingTx(ctx, tx, SettingBondRatingsScrapedAt, now.Format(time.RFC3339)); err != nil {
		return count, err
	}
	return count, tx.Commit()
}

func (r *BondReferenceRepository) UpsertManualRating(ctx context.Context, isin, rating string) error {
	isin = strings.ToUpper(strings.TrimSpace(isin))
	rating = strings.TrimSpace(rating)
	if isin == "" || rating == "" {
		return nil
	}
	now := time.Now().UTC()
	_, err := r.db.ExecContext(ctx, `
INSERT INTO bond_credit_ratings (isin, rating, source, updated_at)
VALUES ($1, $2, $3, $4)
ON CONFLICT (isin) DO UPDATE SET
  rating = excluded.rating,
  source = excluded.source,
  updated_at = excluded.updated_at`,
		isin, rating, RatingSourceManual, now,
	)
	return err
}

func (r *BondReferenceRepository) ListRatingsByISINs(ctx context.Context, isins []string) (map[string]string, error) {
	if len(isins) == 0 {
		return map[string]string{}, nil
	}
	query, args, err := sqlx.In(`
SELECT isin, rating, source
FROM bond_credit_ratings
WHERE isin IN (?)
ORDER BY CASE source WHEN 'manual' THEN 0 ELSE 1 END, updated_at DESC`, isins)
	if err != nil {
		return nil, err
	}
	query = r.db.Rebind(query)
	type row struct {
		ISIN   string `db:"isin"`
		Rating string `db:"rating"`
		Source string `db:"source"`
	}
	var rows []row
	if err := r.db.SelectContext(ctx, &rows, query, args...); err != nil {
		return nil, err
	}
	out := make(map[string]string, len(rows))
	for _, row := range rows {
		if _, ok := out[row.ISIN]; !ok {
			out[row.ISIN] = row.Rating
		}
	}
	return out, nil
}

func (r *BondReferenceRepository) ListIssuerPatterns(ctx context.Context) (map[string]string, error) {
	var rows []struct {
		Pattern string `db:"pattern"`
		Rating  string `db:"rating"`
	}
	if err := r.db.SelectContext(ctx, &rows, `SELECT pattern, rating FROM issuer_rating_patterns ORDER BY LENGTH(pattern) DESC`); err != nil {
		return nil, err
	}
	out := make(map[string]string, len(rows))
	for _, row := range rows {
		out[strings.ToLower(row.Pattern)] = row.Rating
	}
	return out, nil
}

func (r *BondReferenceRepository) UpsertMOEXDefaultFlags(ctx context.Context, flags map[string]BondDefaultFlagRow) (int, error) {
	if len(flags) == 0 {
		return 0, nil
	}
	now := time.Now().UTC()
	tx, err := r.db.BeginTxx(ctx, nil)
	if err != nil {
		return 0, err
	}
	defer func() { _ = tx.Rollback() }()

	count := 0
	for isin, flag := range flags {
		isin = strings.ToUpper(strings.TrimSpace(isin))
		if isin == "" {
			continue
		}
		_, err := tx.ExecContext(ctx, `
INSERT INTO bond_default_flags (isin, has_default, has_technical_default, source, updated_at)
VALUES ($1, $2, $3, $4, $5)
ON CONFLICT (isin) DO UPDATE SET
  has_default = excluded.has_default,
  has_technical_default = excluded.has_technical_default,
  source = excluded.source,
  updated_at = excluded.updated_at
WHERE bond_default_flags.source != $6`,
			isin, flag.HasDefault, flag.HasTechnicalDefault, DefaultSourceMOEX, now, DefaultSourceManual,
		)
		if err != nil {
			return count, err
		}
		count++
	}
	if err := r.setSettingTx(ctx, tx, SettingBondDefaultsRefreshedAt, now.Format(time.RFC3339)); err != nil {
		return count, err
	}
	return count, tx.Commit()
}

func (r *BondReferenceRepository) UpsertManualDefault(ctx context.Context, isin string, hasDefault, hasTechnicalDefault bool) error {
	isin = strings.ToUpper(strings.TrimSpace(isin))
	if isin == "" {
		return nil
	}
	now := time.Now().UTC()
	_, err := r.db.ExecContext(ctx, `
INSERT INTO bond_default_flags (isin, has_default, has_technical_default, source, updated_at)
VALUES ($1, $2, $3, $4, $5)
ON CONFLICT (isin) DO UPDATE SET
  has_default = excluded.has_default,
  has_technical_default = excluded.has_technical_default,
  source = excluded.source,
  updated_at = excluded.updated_at`,
		isin, hasDefault, hasTechnicalDefault, DefaultSourceManual, now,
	)
	return err
}

func (r *BondReferenceRepository) ListDefaultFlags(ctx context.Context) (map[string]BondDefaultFlagRow, error) {
	var rows []struct {
		ISIN                string `db:"isin"`
		HasDefault          bool   `db:"has_default"`
		HasTechnicalDefault bool   `db:"has_technical_default"`
		Source              string `db:"source"`
	}
	if err := r.db.SelectContext(ctx, &rows, `
SELECT isin, has_default, has_technical_default, source
FROM bond_default_flags
ORDER BY CASE source WHEN 'manual' THEN 0 ELSE 1 END, updated_at DESC`); err != nil {
		return nil, err
	}
	out := make(map[string]BondDefaultFlagRow, len(rows))
	for _, row := range rows {
		if _, ok := out[row.ISIN]; !ok {
			out[row.ISIN] = BondDefaultFlagRow{
				ISIN:                row.ISIN,
				HasDefault:          row.HasDefault,
				HasTechnicalDefault: row.HasTechnicalDefault,
				Source:              row.Source,
			}
		}
	}
	return out, nil
}

func (r *BondReferenceRepository) GetSetting(ctx context.Context, key string) (string, error) {
	var value string
	err := r.db.GetContext(ctx, &value, `SELECT value FROM app_settings WHERE key = $1`, key)
	if errors.Is(err, sql.ErrNoRows) {
		return "", nil
	}
	return value, err
}

func (r *BondReferenceRepository) SetSetting(ctx context.Context, key, value string) error {
	_, err := r.db.ExecContext(ctx, `
INSERT INTO app_settings (key, value) VALUES ($1, $2)
ON CONFLICT (key) DO UPDATE SET value = excluded.value`, key, value)
	return err
}

func (r *BondReferenceRepository) setSettingTx(ctx context.Context, tx *sqlx.Tx, key, value string) error {
	_, err := tx.ExecContext(ctx, `
INSERT INTO app_settings (key, value) VALUES ($1, $2)
ON CONFLICT (key) DO UPDATE SET value = excluded.value`, key, value)
	return err
}

func (r *BondReferenceRepository) RatingsScrapedAt(ctx context.Context) (time.Time, error) {
	return parseSettingTime(ctx, r, SettingBondRatingsScrapedAt)
}

func (r *BondReferenceRepository) DefaultsRefreshedAt(ctx context.Context) (time.Time, error) {
	return parseSettingTime(ctx, r, SettingBondDefaultsRefreshedAt)
}

func parseSettingTime(ctx context.Context, r *BondReferenceRepository, key string) (time.Time, error) {
	raw, err := r.GetSetting(ctx, key)
	if err != nil || raw == "" {
		return time.Time{}, err
	}
	return time.Parse(time.RFC3339, raw)
}
