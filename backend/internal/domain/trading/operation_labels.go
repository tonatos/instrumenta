package trading

import "strings"

var operationTypeLabels = map[string]string{
	"OPERATION_TYPE_INPUT":                    "Пополнение",
	"OPERATION_TYPE_OUTPUT":                   "Вывод",
	"OPERATION_TYPE_BUY":                      "Покупка",
	"OPERATION_TYPE_BUY_CARD":                 "Покупка",
	"OPERATION_TYPE_BUY_MARGIN":               "Покупка",
	"OPERATION_TYPE_SELL":                     "Продажа",
	"OPERATION_TYPE_SELL_CARD":                "Продажа",
	"OPERATION_TYPE_SELL_MARGIN":              "Продажа",
	"OPERATION_TYPE_COUPON":                   "Купон",
	"OPERATION_TYPE_BOND_REPAYMENT":           "Погашение",
	"OPERATION_TYPE_BOND_REPAYMENT_FULL":      "Погашение",
	"OPERATION_TYPE_DIVIDEND":                 "Дивиденд",
	"OPERATION_TYPE_DIV_EXT":                  "Дивиденд",
	"OPERATION_TYPE_BROKER_FEE":               "Комиссия брокера",
	"OPERATION_TYPE_SERVICE_FEE":              "Сервисная комиссия",
	"OPERATION_TYPE_OTHER_FEE":                "Комиссия",
	"OPERATION_TYPE_TAX":                      "Налог",
	"OPERATION_TYPE_TAX_PROGRESSIVE":          "Налог",
	"OPERATION_TYPE_BOND_TAX":                 "Налог по облигации",
	"OPERATION_TYPE_BOND_TAX_PROGRESSIVE":     "Налог по облигации",
	"OPERATION_TYPE_TAX_CORRECTION":           "Корректировка налога",
	"OPERATION_TYPE_TAX_CORRECTION_COUPON":    "Корректировка налога",
	"OPERATION_TYPE_DIVIDEND_TAX":             "Налог на дивиденды",
	"OPERATION_TYPE_DIVIDEND_TAX_PROGRESSIVE": "Налог на дивиденды",
}

var operationStateLabels = map[string]string{
	"OPERATION_STATE_EXECUTED": "Исполнена",
	"OPERATION_STATE_CANCELED": "Отменена",
	"OPERATION_STATE_PROGRESS": "В обработке",
}

// OperationTypeLabel maps OPERATION_TYPE_* to a short Russian label.
func OperationTypeLabel(operationType string) string {
	if label, ok := operationTypeLabels[operationType]; ok {
		return label
	}
	if strings.HasPrefix(operationType, "OPERATION_TYPE_") {
		body := strings.TrimPrefix(operationType, "OPERATION_TYPE_")
		return strings.Title(strings.ReplaceAll(body, "_", " "))
	}
	return operationType
}

// OperationStateLabel maps OPERATION_STATE_* to a short Russian label.
func OperationStateLabel(state string) string {
	if label, ok := operationStateLabels[state]; ok {
		return label
	}
	if strings.HasPrefix(state, "OPERATION_STATE_") {
		body := strings.TrimPrefix(state, "OPERATION_STATE_")
		return strings.Title(strings.ReplaceAll(body, "_", " "))
	}
	return state
}
