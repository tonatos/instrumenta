import type { SubscriptionPaywallReason } from "./subscriptionPaywallBus";

export type PaywallCopy = {
  title: string;
  lead: string;
  bullets: string[];
};

const COPY: Record<SubscriptionPaywallReason, PaywallCopy> = {
  default: {
    title: "Доступно в Instrumenta Pro",
    lead: "Подписка открывает живую торговлю с брокером: привязка счёта, ключи T‑Invest и очередь действий по реальному портфелю. Скринер, симуляция и radar остаются бесплатными.",
    bullets: [
      "Привязка брокерского счёта и сохранение ключей",
      "Уведомления в Telegram о пут‑офертах и риске",
      "Очередь покупок, реинвеста и срочных продаж",
    ],
  },
  "portfolio.attach": {
    title: "Привязка счёта — в Instrumenta Pro",
    lead: "Свяжите портфель с T‑Invest и управляйте реальными позициями по плану. Без подписки доступны скринер и симуляция — Pro добавляет исполнение и контроль риска на вашем счёте.",
    bullets: [
      "Живые рекомендации по кэшу и реинвесту",
      "Deploy Session: зафиксированный план покупок",
      "Сигналы и уведомления по удерживаемым бумагам",
    ],
  },
  "broker_credentials.write": {
    title: "Ключи брокера — в Instrumenta Pro",
    lead: "Сохранение токенов T‑Invest доступно по подписке. Уже сохранённые ключи можно удалить в любой момент — после оплаты вы снова сможете добавить или обновить токен.",
    bullets: [
      "Шифрованное хранение токенов (AES‑GCM)",
      "Чтение портфеля и выставление заявок от вашего имени",
      "Песочница и production в одном кабинете",
    ],
  },
  "trading_portfolio.access": {
    title: "Торговый портфель ждёт подписку",
    lead: "Привязанный счёт и ключи на месте — нужен только активный тариф Pro. После оплаты доступ восстановится без повторной настройки.",
    bullets: [
      "Ключи и привязка счёта сохраняются",
      "Очередь действий и уведомления снова онлайн",
      "Скринер и симуляция работают без оплаты",
    ],
  },
  telegram_bot: {
    title: "Telegram-бот — в Instrumenta Pro",
    lead: "Push о пут‑офертах и критическом риске доступен подписчикам. После оплаты откройте бота в Telegram и нажмите Start — без этого шага бот не может писать первым.",
    bullets: [
      "Уведомления на ваш Telegram ID",
      "Пут‑оферты и критические эскалации риска",
      "Отключение в любой момент: /stop в чате с ботом",
    ],
  },
};

export function paywallCopyFor(reason: SubscriptionPaywallReason = "default"): PaywallCopy {
  return COPY[reason] ?? COPY.default;
}
