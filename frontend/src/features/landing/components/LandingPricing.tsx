import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { formatRub } from "@/lib/utils";
import { TelegramLoginButton } from "@/features/auth/TelegramLoginButton";

function kopecksToRub(k: number) {
  return k / 100;
}

export function LandingPricing() {
  const { data: catalog, isLoading, isError } = useQuery({
    queryKey: ["billing-catalog"],
    queryFn: () => api.getBillingCatalog(),
    retry: 1,
  });

  const month = catalog?.plans.find((p) => p.period === "month");
  const year = catalog?.plans.find((p) => p.period === "year");

  return (
    <section className="section shell" id="pricing">
      <div className="section__head reveal">
        <h2>Простой прайс</h2>
        <p>
          Начните бесплатно: стратегия и расчёты доступны после входа. Pro — когда
          понадобится связка со счётом и исполнение плана.
        </p>
      </div>

      <div className="pricing-grid">
        <article className="price-card reveal" data-testid="pricing-free">
          <div className="price-card__plan">Free</div>
          <div className="price-card__amount">0 ₽</div>
          <p className="price-card__desc">Чтобы разобрать стратегию и рынок</p>
          <ul className="bullets">
            <li>Алгоритмический отбор по параметрам стратегии</li>
            <li>Симуляция портфеля и реинвеста</li>
            <li>Market Radar и избранное</li>
          </ul>
          <TelegramLoginButton landingStyle />
        </article>

        <article className="price-card reveal" data-testid="pricing-pro-month">
          <div className="price-card__plan">Pro · месяц</div>
          <div className="price-card__amount">
            {isLoading && "…"}
            {!isLoading && month
              ? formatRub(kopecksToRub(month.amount_kopecks))
              : !isLoading
                ? "—"
                : null}
            {month && <span> / мес</span>}
          </div>
          <p className="price-card__desc">Когда портфель уже в деле</p>
          <ul className="bullets">
            <li>Всё из Free</li>
            <li>Ключи T‑Invest и привязка счёта</li>
            <li>Очередь действий и Deploy Session</li>
            <li>Telegram‑уведомления по событиям</li>
          </ul>
          <a className="btn btn--ghost btn--block" href="#cta">
            Войти и подключить
          </a>
        </article>

        <article className="price-card price-card--pro reveal" data-testid="pricing-pro-year">
          <div className="price-card__plan">Pro · год</div>
          {year && year.savings_percent > 0 && (
            <span className="price-card__badge" data-testid="pricing-year-savings">
              −{year.savings_percent.toFixed(0)}% к помесячной оплате
            </span>
          )}
          <div className="price-card__amount">
            {isLoading && "…"}
            {!isLoading && year
              ? formatRub(kopecksToRub(year.monthly_kopecks))
              : !isLoading
                ? "—"
                : null}
            {year && <span> / мес</span>}
          </div>
          <p className="price-card__desc">
            {year
              ? `${formatRub(kopecksToRub(year.amount_kopecks))} сразу · экономия ${formatRub(kopecksToRub(year.savings_kopecks))}`
              : "Выгоднее при годовой оплате"}
          </p>
          <ul className="bullets">
            <li>Всё из Pro · месяц</li>
            <li>Фиксированная цена на год</li>
            <li>Автопродление можно отключить</li>
          </ul>
          <a className="btn btn--primary btn--block" href="#cta">
            Войти и подключить
          </a>
        </article>
      </div>

      {isError && (
        <p className="pricing-note">Не удалось загрузить актуальные тарифы. Попробуйте позже.</p>
      )}
      {!isError && (
        <p className="pricing-note">
          Оплата через ЮKassa. Информационно‑аналитический сервис; решение о сделках принимаете вы.
        </p>
      )}
    </section>
  );
}
