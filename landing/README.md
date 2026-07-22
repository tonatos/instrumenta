# Instrumenta Landing

Отдельный маркетинговый лендинг. **Не зависит** от `frontend/` и backend API.

## Продукт (multi-tenant)

Instrumenta — multi-user: вход через Telegram, портфели и избранное привязаны к пользователю.
Торговые ключи T‑Invest хранятся **на пользователя** в зашифрованном виде (envelope encryption + `BROKER_KEK`);
системный `TINKOFF_TOKEN` используется только для обогащения бумаг в скринере.
Настройка ключей и краткое описание защиты — в приложении (`/account`). Отдельная публичная Security-страница на лендинге — в планах.

## Стек

- Vite + TypeScript
- Свой CSS (без Tailwind)
- Playwright e2e в этой же папке

## Команды

```bash
cd landing
npm install
npm run dev          # http://127.0.0.1:5177
npm run build
npm run test:e2e
```

Или из корня: `task run:landing`
