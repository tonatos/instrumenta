export const RISK_LABELS: Record<string, string> = {
  normal: "Нормальный",
  aggressive: "Агрессивный",
  conservative: "Консервативный",
};

export const SOURCE_LABELS: Record<string, string> = {
  initial: "Старт",
  reinvest_maturity: "Реинв. погаш.",
  reinvest_put_offer: "Реинв. оферта",
  reinvest_coupon_cash: "Реинв. купоны",
};

export const POSITION_STATUS_LABELS: Record<string, string> = {
  pending: "Ожидает",
  active: "Активна",
  drift: "Расхождение",
  closed: "Закрыта",
};

export const SUGGESTION_KIND_LABELS: Record<string, string> = {
  buy: "Покупка",
  reinvest: "Реинвестиция",
  put_offer_reminder: "Пут-оферта",
  sell: "Продажа",
};

export const KIND_LABELS: Record<string, string> = {
  initial_buy: "Стартовая покупка",
  reinvest_buy: "Реинвестиция",
  put_offer_submit: "Пут-оферта",
  manual_sell: "Продажа",
};

export const STATUS_LABELS: Record<string, string> = {
  action_required: "Требует действия",
  in_progress: "На бирже",
  overdue: "Просрочено",
  blocked: "Заблокировано",
};

export const ORDER_STATUS_LABELS: Record<string, string> = {
  EXECUTION_REPORT_STATUS_NEW: "Новая",
  EXECUTION_REPORT_STATUS_PARTIALLYFILL: "Частично исполнена",
  EXECUTION_REPORT_STATUS_FILL: "Исполнена",
  EXECUTION_REPORT_STATUS_CANCELLED: "Отменена",
  EXECUTION_REPORT_STATUS_REJECTED: "Отклонена",
  EXECUTION_REPORT_STATUS_PENDING_CANCEL: "Отмена в обработке",
};

export const TRIGGER_LABELS: Record<string, string> = {
  maturity: "Погашение",
  put_offer: "Пут-оферта",
  coupon_cash: "Купонный кэш",
};

export const OPERATION_TYPE_LABELS: Record<string, string> = {
  buy: "Покупка",
  sell: "Продажа",
  coupon: "Купон",
  repayment: "Погашение",
  input: "Пополнение",
  output: "Вывод",
  tax: "Налог",
  fee: "Комиссия",
};

export function formatOrderStatus(status: string | null | undefined): string {
  if (!status) return "—";
  return ORDER_STATUS_LABELS[status] ?? status.replace("EXECUTION_REPORT_STATUS_", "");
}
