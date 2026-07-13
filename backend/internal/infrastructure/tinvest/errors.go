package tinvest

import "fmt"

// TradingClientError is a base error for T-Invest broker I/O.
type TradingClientError struct {
	Message string
}

func (e *TradingClientError) Error() string {
	if e == nil {
		return ""
	}
	return e.Message
}

// OrderTooLargeError is returned when order amount exceeds API limit.
type OrderTooLargeError struct {
	*TradingClientError
}

// TradingNotAvailableError is returned when instrument is not API-tradable.
type TradingNotAvailableError struct {
	*TradingClientError
}

func tradingErrorf(format string, args ...any) error {
	return &TradingClientError{Message: fmt.Sprintf(format, args...)}
}

func tradingNotAvailablef(format string, args ...any) error {
	return &TradingNotAvailableError{
		TradingClientError: &TradingClientError{Message: fmt.Sprintf(format, args...)},
	}
}

func orderTooLargef(format string, args ...any) error {
	return &OrderTooLargeError{
		TradingClientError: &TradingClientError{Message: fmt.Sprintf(format, args...)},
	}
}
