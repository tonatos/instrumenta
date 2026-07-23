import { useCallback, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { useAuth } from "@/features/auth/AuthContext";
import { TelegramLoginButton } from "@/features/auth/TelegramLoginButton";
import { LandingPricing } from "./components/LandingPricing";
import { PortfolioHeroMock } from "./components/PortfolioHeroMock";
import { ScreencastModal } from "./components/ScreencastModal";
import { GITHUB_REPO, GitHubIcon } from "./github";
import { useLandingEffects } from "./useLandingEffects";
import "./landing.css";

export function LandingPage() {
  const { authEnabled, isAuthenticated, loading } = useAuth();
  const [rootEl, setRootEl] = useState<HTMLDivElement | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [videoOpen, setVideoOpen] = useState(false);
  useLandingEffects(rootEl);

  const closeVideo = useCallback(() => setVideoOpen(false), []);

  if (loading) {
    return (
      <div className="landing-root">
        <div className="shell" style={{ paddingBlock: "4rem", textAlign: "center", color: "var(--text-muted)" }}>
          Загрузка...
        </div>
      </div>
    );
  }

  // Logged-in users skip the marketing page and go straight to the terminal.
  if (authEnabled && isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="landing-root" ref={setRootEl} data-testid="landing-page">
      <div className="page">
        <header className="nav shell" role="banner" data-nav>
          <a className="brand" href="#top" aria-label="Instrumenta">
            <img
              className="brand__logo"
              src="/brand/instrumenta-logo.png"
              alt="Instrumenta"
              width={168}
              height={28}
            />
          </a>
          <nav
            className="nav__links"
            aria-label="Разделы"
            data-open={menuOpen ? "true" : "false"}
          >
            <a href="#strategy" onClick={() => setMenuOpen(false)}>
              Стратегия
            </a>
            <a href="#how" onClick={() => setMenuOpen(false)}>
              Как работает
            </a>
            <a href="#pricing" onClick={() => setMenuOpen(false)}>
              Прайс
            </a>
            <Link to="/offer" onClick={() => setMenuOpen(false)}>
              Оферта
            </Link>
            <Link to="/security" onClick={() => setMenuOpen(false)}>
              Безопасность
            </Link>
          </nav>
          <Link className="nav__cta" to="/login" data-testid="nav-login">
            Войти
          </Link>
          <button
            className="nav__menu"
            type="button"
            aria-label="Меню"
            data-menu
            onClick={() => setMenuOpen((v) => !v)}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path
                d="M4 7h16M4 12h16M4 17h16"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </header>

        <main id="top">
          <section className="hero shell">
            <div className="hero__copy reveal">
              <div className="eyebrow">
                <span className="eyebrow__dot" aria-hidden="true" />
                Предсказуемый поток · умеренный риск
              </div>
              <h1>Облигационная стратегия, которой можно управлять</h1>
              <p className="hero__lead">
                Instrumenta — информационно‑аналитический инструмент: алгоритмически
                ранжирует короткие облигации по параметрам выбранной стратегии,
                считает план и помогает держать реинвест и события под контролем —
                без ручной возни с таблицами.
              </p>
              <div className="hero__actions">
                <a className="btn btn--primary" href="#cta">
                  Начать со стратегии
                </a>
                <a className="btn btn--ghost" href="#strategy">
                  Как устроена идея
                </a>
              </div>
            </div>

            <div className="hero__stage reveal">
              <div className="hero__slabs" aria-hidden="true">
                <div className="slab slab--a" />
                <div className="slab slab--b" />
                <div className="slab slab--c" />
              </div>
              <PortfolioHeroMock onPlay={() => setVideoOpen(true)} />
            </div>
          </section>

          <section className="trust">
            <div className="shell trust__grid reveal">
              <article className="trust-card">
                <div className="trust-card__icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none">
                    <path
                      d="M12 3l2.4 4.9 5.4.8-3.9 3.8.9 5.4L12 15.9 7.2 18l.9-5.4L4.2 8.7l5.4-.8L12 3z"
                      stroke="currentColor"
                      strokeWidth="1.6"
                      strokeLinejoin="round"
                    />
                  </svg>
                </div>
                <div>
                  <h3>3 стратегии</h3>
                  <p>в скоре и отборе</p>
                </div>
              </article>
              <article className="trust-card">
                <div className="trust-card__icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none">
                    <rect x="3" y="6" width="18" height="12" rx="2" stroke="currentColor" strokeWidth="1.6" />
                    <path d="M3 10h18M8 14h4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                  </svg>
                </div>
                <div>
                  <h3>План закупок</h3>
                  <p>фиксируете и исполняете</p>
                </div>
              </article>
              <article className="trust-card">
                <div className="trust-card__icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none">
                    <circle cx="12" cy="12" r="8" stroke="currentColor" strokeWidth="1.6" />
                    <circle cx="12" cy="12" r="4" stroke="currentColor" strokeWidth="1.6" />
                    <circle cx="12" cy="12" r="1.5" fill="currentColor" />
                  </svg>
                </div>
                <div>
                  <h3>Радар рынка</h3>
                  <p>сектора и спреды</p>
                </div>
              </article>
              <article className="trust-card">
                <div className="trust-card__icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none">
                    <path
                      d="M21 5 3 12.5l5.5 1.7L17 8l-6.8 7.2.3 4.3L13 16.5 18.5 20 21 5z"
                      stroke="currentColor"
                      strokeWidth="1.6"
                      strokeLinejoin="round"
                    />
                  </svg>
                </div>
                <div>
                  <h3>Telegram</h3>
                  <p>события портфеля</p>
                </div>
              </article>
            </div>
          </section>

          <section className="section shell" id="strategy">
            <div className="section__head reveal">
              <h2>Стратегия простыми словами</h2>
              <p>
                Не «магический скринер», а повторяемый контур: короткие
                качественные облигации, математический отбор и управляемый реинвест.
              </p>
            </div>
            <div className="strategy-grid">
              <article className="strategy-card reveal">
                <span className="tag tag--mint">На чём строится результат</span>
                <h3>Купоны и погашения на коротком горизонте</h3>
                <p>
                  Деньги возвращаются относительно быстро: тело бумаги и купоны
                  снова идут в работу. Расчётные показатели портфеля опираются на
                  понятный денежный поток, а не на длинную дюрацию.
                </p>
              </article>
              <article className="strategy-card reveal">
                <span className="tag tag--blue">Как отбираем</span>
                <h3>Математика под стратегию</h3>
                <p>
                  «Тихая гавань», «Умеренность», «Возможность» — разные веса
                  доходности, риска и ликвидности. Сервис ранжирует бумаги по скору
                  выбранной стратегии: это аналитический расчёт, а не совет
                  совершить сделку с конкретной бумагой.
                </p>
              </article>
              <article className="strategy-card reveal">
                <span className="tag tag--amber">Почему короткие</span>
                <h3>Меньше сюрпризов от ставки</h3>
                <p>
                  Короткие выпуски быстрее погашаются и реже «замораживают» капитал
                  на годы. Реинвест можно делать по актуальным рыночным условиям —
                  стратегия остаётся управляемой.
                </p>
              </article>
              <article className="strategy-card reveal">
                <span className="tag tag--mint">Высокий ключ</span>
                <h3>Фиксируем повышенные ставки на коротком окне</h3>
                <p>
                  В среде высокой ключевой ставки рынок часто предлагает
                  привлекательную YTM на коротком горизонте. Инструмент помогает
                  собрать и сопровождать такой портфель с умеренным риском по
                  рейтинговым фильтрам стратегии.
                </p>
              </article>
            </div>
          </section>

          <section className="section shell" id="how">
            <div className="section__head reveal">
              <h2>Как это работает</h2>
              <p>
                Четыре шага от стратегии до исполнения. Скринер, радар и алерты —
                вспомогательные контуры вокруг стратегии.
              </p>
            </div>
            <div className="feature-grid">
              <article className="feature-card reveal">
                <span className="tag tag--mint">1</span>
                <h3>Выбираете стратегию</h3>
                <p>
                  Задаёте горизонт и параметры стратегии. Дальше скоринг и фильтры
                  работают в одной логике — и в симуляции, и при отборе.
                </p>
              </article>
              <article className="feature-card reveal">
                <span className="tag tag--blue">2</span>
                <h3>Алгоритмический отбор</h3>
                <p>
                  Система собирает корзину кандидатов по скору: рейтинг,
                  ликвидность, YTM и ограничения выбранной стратегии.
                </p>
              </article>
              <article className="feature-card reveal">
                <span className="tag tag--amber">3</span>
                <h3>Фиксируете расчётный план</h3>
                <p>
                  Deploy Session держит buy и reinvest стабильными, пока вы
                  исполняете. Sell и критичные события обновляются live.
                </p>
              </article>
              <article className="feature-card reveal">
                <span className="tag tag--mint">4</span>
                <h3>Сигналы и уведомления</h3>
                <p>
                  Пут‑оферты, эскалация риска, радар рынка — чтобы вовремя увидеть
                  событие. Решение всегда остаётся за вами.
                </p>
              </article>
            </div>
          </section>

          <section className="section shell" id="portfolio">
            <div className="split reveal">
              <div className="split__copy">
                <span className="tag tag--blue">Исполнение</span>
                <h2>Зафиксировали расчётный план — и спокойно исполняете</h2>
                <p>
                  Очередь действий группирует срочное, контроль и покупки. При
                  подключении T‑Invest лимитные заявки уходят из того же окна.
                  Sandbox — чтобы проверить контур без боевого счёта.
                </p>
                <ul className="bullets">
                  <li>Очередь: срочно / на контроле / покупки</li>
                  <li>Лимитные заявки через T‑Invest</li>
                  <li>Стабильный план на время исполнения</li>
                </ul>
              </div>
              <div className="panel">
                <h3>Очередь действий</h3>
                <div className="queue-group">
                  <div className="queue-group__label queue-group__label--urgent">Срочно</div>
                  <div className="queue-item">
                    <div>
                      <strong>Пут‑оферта · Сбербанк 002P</strong>
                      <span>Окно приёма заявок открыто</span>
                    </div>
                    <span className="btn btn--danger-soft" aria-hidden="true">
                      К заявке
                    </span>
                  </div>
                </div>
                <div className="queue-group">
                  <div className="queue-group__label queue-group__label--buy">
                    Кандидаты · deploy session
                  </div>
                  <div className="queue-item">
                    <div>
                      <strong>Кандидат · ОФЗ 26238</strong>
                      <span>12 лотов · расчётная сумма</span>
                    </div>
                    <span className="btn btn--primary" aria-hidden="true">
                      К заявке
                    </span>
                  </div>
                  <div className="queue-item">
                    <div>
                      <strong>Реинвест · купон Газпром</strong>
                      <span>остаток к размещению</span>
                    </div>
                    <span className="btn btn--primary" aria-hidden="true">
                      К заявке
                    </span>
                  </div>
                </div>
                <div className="session-bar">
                  <span>Сессия активна · TTL 24ч</span>
                  <span>Обновить план</span>
                </div>
              </div>
            </div>
          </section>

          <section className="section shell" id="radar">
            <div className="split split--reverse reveal">
              <div className="split__copy">
                <span className="tag tag--amber">Контроль рынка</span>
                <h2>Радар рядом со стратегией</h2>
                <p>
                  Секторальные сдвиги и аномалии спреда — отдельный контур
                  наблюдения. Он не подменяет портфель, а помогает вовремя
                  заметить, где рынок «шумит» сильнее обычного.
                </p>
                <ul className="bullets bullets--amber">
                  <li>Аномалии спреда относительно peers</li>
                  <li>Heatmap секторов за 7 дней</li>
                  <li>Сигналы по удерживаемым бумагам</li>
                </ul>
              </div>
              <div className="panel split__visual" data-heatmap>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    gap: "0.75rem",
                    flexWrap: "wrap",
                  }}
                >
                  <h3>Market Radar</h3>
                  <span
                    className="chip chip--profile"
                    style={{
                      color: "var(--accent)",
                      borderColor: "color-mix(in srgb, var(--accent) 40%, var(--border))",
                      background: "color-mix(in srgb, var(--accent) 10%, transparent)",
                    }}
                  >
                    Сначала мои
                  </span>
                </div>
                <p style={{ color: "var(--text-muted)", fontSize: "0.82rem", margin: 0 }}>
                  Секторы · Δ спреда 7д
                </p>
                <div className="heatmap">
                  <div className="heatmap__row">
                    <div className="heatmap__meta">
                      <span>Нефть и газ</span>
                      <span style={{ color: "var(--danger)" }}>+42 б.п.</span>
                    </div>
                    <div className="heatmap__track">
                      <div className="heatmap__bar" style={{ ["--w" as string]: "95%", background: "var(--danger)" }} />
                    </div>
                  </div>
                  <div className="heatmap__row">
                    <div className="heatmap__meta">
                      <span>Банки</span>
                      <span style={{ color: "var(--accent-amber)" }}>+18 б.п.</span>
                    </div>
                    <div className="heatmap__track">
                      <div
                        className="heatmap__bar"
                        style={{ ["--w" as string]: "70%", background: "var(--accent-amber)" }}
                      />
                    </div>
                  </div>
                  <div className="heatmap__row">
                    <div className="heatmap__meta">
                      <span>ОФЗ</span>
                      <span style={{ color: "var(--accent)" }}>−4 б.п.</span>
                    </div>
                    <div className="heatmap__track">
                      <div className="heatmap__bar" style={{ ["--w" as string]: "30%", background: "var(--accent)" }} />
                    </div>
                  </div>
                </div>
                <div className="dip">
                  <strong>Сигнал</strong>
                  <p>Секторный стресс без новостного фона — на радаре для самостоятельной оценки</p>
                </div>
              </div>
            </div>
          </section>

          <LandingPricing />

          <section className="oss-teaser shell" id="opensource" data-testid="oss-teaser">
            <div className="oss-teaser__card reveal">
              <div className="oss-teaser__icon" aria-hidden="true">
                <GitHubIcon />
              </div>
              <div className="oss-teaser__copy">
                <span className="tag tag--mint">Open source friendly</span>
                <h2>Исходники открыты — можно проверить самому</h2>
                <p>
                  Код скоринга, шифрования ключей и торгового контура доступен на
                  GitHub. Лицензия разрешает личное и некоммерческое использование —
                  без перепродажи и коммерческих продуктов на базе кода.
                </p>
              </div>
              <a
                className="btn btn--ghost oss-teaser__cta"
                href={GITHUB_REPO}
                target="_blank"
                rel="noreferrer"
                data-testid="oss-teaser-github"
              >
                <GitHubIcon />
                Смотреть на GitHub
              </a>
            </div>
          </section>

          <section className="final-cta shell" id="cta">
            <div className="final-cta__card reveal">
              <h2>Соберите управляемую облигационную стратегию</h2>
              <p>
                Войдите через Telegram, выберите стратегию и соберите расчётный
                портфель. Подписка Pro — когда понадобится связка со счётом и
                уведомления.
              </p>
              <TelegramLoginButton landingStyle />
            </div>
          </section>
        </main>

        <footer className="footer">
          <div className="shell">
            <div className="footer__top">
              <a className="brand" href="#top" aria-label="Instrumenta">
                <img
                  className="brand__logo"
                  src="/brand/instrumenta-logo.png"
                  alt="Instrumenta"
                  width={168}
                  height={28}
                />
              </a>
              <div className="footer__links">
                <a href="#strategy">Стратегия</a>
                <a href="#how">Как работает</a>
                <a href="#pricing">Прайс</a>
                <Link to="/offer">Оферта</Link>
                <Link to="/security">Безопасность</Link>
                <a
                  className="footer__github"
                  href={GITHUB_REPO}
                  target="_blank"
                  rel="noreferrer"
                  data-testid="footer-github"
                >
                  <GitHubIcon />
                  <span>GitHub</span>
                </a>
              </div>
            </div>
            <p className="footer__legal">
              © 2026 Instrumenta ·{" "}
              <a href="https://instrumenta.trade/">instrumenta.trade</a>. Данные
              Мосбиржи и T‑Invest. Исходный код —{" "}
              <a href={GITHUB_REPO} target="_blank" rel="noreferrer">
                GitHub
              </a>
              , лицензия PolyForm Noncommercial 1.0.0 (личное и некоммерческое
              использование). Информация носит аналитический характер и не является
              индивидуальной инвестиционной рекомендацией; финансовые инструменты либо
              сделки, упомянутые в Сервисе, могут не соответствовать вашему финансовому
              положению, целям инвестирования, допустимому риску и (или) ожидаемой
              доходности. Расчётные показатели носят модельный характер. Заявки
              отправляет пользователь самостоятельно — автоследования нет. Исполнитель:
              Семячкин Виталий Юрьевич, ИНН 660608518305.
            </p>
          </div>
        </footer>
      </div>

      <ScreencastModal open={videoOpen} onClose={closeVideo} />
    </div>
  );
}
