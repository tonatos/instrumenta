import { Link } from "react-router-dom";
import { GITHUB_REPO, GitHubIcon } from "./github";
import "./landing.css";

const TOKEN_DOCS = "https://developer.tbank.ru/invest/intro/intro/token";

export function SecurityPage() {
  return (
    <div className="landing-root" data-testid="security-page">
      <div className="page">
        <header className="nav shell" role="banner">
          <Link className="brand" to="/landing" aria-label="Instrumenta">
            <img
              className="brand__logo"
              src="/brand/instrumenta-logo.png"
              alt="Instrumenta"
              width={168}
              height={28}
            />
          </Link>
          <Link className="nav__cta" to="/login">
            Войти
          </Link>
        </header>

        <main className="shell security-doc">
          <Link className="offer-back" to="/landing">
            ← Вернуться
          </Link>

          <h1>Безопасность и брокерские ключи</h1>
          <p className="offer-meta">
            Коротко о том, зачем нужен доступ к T‑Invest, как мы с ним обращаемся и как его
            отозвать.
          </p>

          <section className="security-block" data-testid="security-why">
            <span className="tag tag--blue">Зачем</span>
            <h2>Зачем привязывать ключи T‑Invest</h2>
            <p>
              Без ключа Instrumenta работает как калькулятор и скринер: подбирает бумаги,
              считает план, показывает радар. Чтобы связать сервис с вашим брокерским счётом,
              нужен API‑токен T‑Invest — его вы выпускаете сами в кабинете банка.
            </p>
            <p>С сохранённым ключом (на тарифе Pro) сервис может:</p>
            <ul className="offer-list">
              <li>видеть позиции и свободные деньги на привязанном счёте;</li>
              <li>показывать очередь действий по реальному портфелю;</li>
              <li>отправлять лимитные заявки от вашего имени — только когда вы сами
                подтверждаете покупку или продажу в интерфейсе;</li>
              <li>присылать уведомления по вашим позициям (пут‑оферты, риск и т.п.).</li>
            </ul>
            <p>
              Мы не торгуем «сами по себе» и не обещаем доходность. Решение о каждой сделке
              остаётся за вами.
            </p>
          </section>

          <section className="security-block" data-testid="security-storage">
            <span className="tag tag--mint">Хранение</span>
            <h2>Как мы храним ключи</h2>
            <p>
              Токен не лежит у нас «как есть» — перед сохранением он шифруется. Ключ
              шифрования хранится отдельно от базы, где лежат ваши данные.
            </p>
            <ul className="offer-list">
              <li>Мы не показываем сохранённый токен обратно в интерфейсе — только факт,
                что ключ задан.</li>
              <li>Полный текст токена не пишется в журналы и не уходит в ответы API.</li>
              <li>
                Сохранение ключей доступно по подписке Pro; удалить уже сохранённый ключ
                можно в любой момент, даже без активной оплаты.
              </li>
            </ul>
          </section>

          <section className="security-block" data-testid="security-revoke">
            <span className="tag tag--amber">Контроль</span>
            <h2>Как отозвать доступ</h2>
            <p>Вы полностью контролируете токен — и в Instrumenta, и у брокера.</p>
            <ol className="security-steps">
              <li>
                <strong>В приложении.</strong> Раздел «Аккаунт → Ключи»: кнопка «Удалить»
                убирает токен с наших серверов. После этого Instrumenta больше не сможет
                обращаться к вашему счёту.
              </li>
              <li>
                <strong>В T‑Инвестициях.</strong> В{" "}
                <a href={TOKEN_DOCS} target="_blank" rel="noreferrer">
                  кабинете T‑Invest API
                </a>{" "}
                отзовите или удалите токен. Старый ключ перестанет работать везде — даже если
                кто‑то его скопировал раньше.
              </li>
            </ol>
            <p>
              Надёжный порядок: сначала удалить ключ в Instrumenta, затем отозвать его в
              T‑Банке. Если сомневаетесь — отзовите токен у брокера в первую очередь.
            </p>
          </section>

          <section className="security-block" data-testid="security-opensource">
            <span className="tag tag--blue">Открытость</span>
            <h2>Исходный код</h2>
            <p>
              Код сервиса открыт: можно самостоятельно посмотреть, как устроены шифрование
              ключей, торговый контур и уведомления. Лицензия PolyForm Noncommercial —
              личное и некоммерческое использование, без перепродажи.
            </p>
            <a
              className="security-github"
              href={GITHUB_REPO}
              target="_blank"
              rel="noreferrer"
              data-testid="security-github"
            >
              <GitHubIcon />
              <span>Исходники на GitHub</span>
            </a>
          </section>

          <div className="security-cta">
            <Link className="btn btn--primary" to="/login">
              Войти в Instrumenta
            </Link>
            <Link className="btn btn--ghost" to="/offer">
              Публичная оферта
            </Link>
          </div>
        </main>

        <footer className="footer">
          <div className="shell">
            <p className="footer__legal">
              © 2026 Instrumenta. Сервис носит информационно‑аналитический характер и не
              является индивидуальной инвестиционной рекомендацией.
            </p>
          </div>
        </footer>
      </div>
    </div>
  );
}
