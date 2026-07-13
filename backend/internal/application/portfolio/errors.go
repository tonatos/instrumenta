package portfolio

import "errors"

// SlotOverrideValidationError is returned when a slot override is invalid.
type SlotOverrideValidationError struct {
	Message string
}

func (e SlotOverrideValidationError) Error() string { return e.Message }

// ErrNotFound indicates a missing portfolio.
var ErrNotFound = errors.New("portfolio not found")

// ErrPositionNotFound indicates a missing position.
var ErrPositionNotFound = errors.New("position not found")

// ErrBondNotFound indicates a missing bond in universe.
var ErrBondNotFound = errors.New("bond not found in universe")
