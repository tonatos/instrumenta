import "./styles/base.css";
import "./styles/landing.css";

const app = document.querySelector<HTMLDivElement>("#app");
if (!app) {
  throw new Error("#app not found");
}

app.innerHTML = `
  <div class="page">
    <header class="nav shell" role="banner" data-nav>
      <a class="brand" href="#top" aria-label="Bond Monitor">
        <span class="brand__mark" aria-hidden="true"></span>
        Bond Monitor
      </a>
      <nav class="nav__links" aria-label="Разделы">
        <a href="#features">Возможности</a>
        <a href="#portfolio">Портфель</a>
        <a href="#radar">Радар</a>
        <a href="#pricing">Прайс</a>
      </nav>
      <a class="nav__cta" href="#pricing">Войти</a>
      <button class="nav__menu" type="button" aria-label="Меню" data-menu>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M4 7h16M4 12h16M4 17h16" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
        </svg>
      </button>
    </header>

    <main id="top">
      <section class="hero shell">
        <div class="hero__copy reveal">
          <div class="eyebrow">
            <span class="eyebrow__dot" aria-hidden="true"></span>
            Мосбиржа · T-Invest · сигналы
          </div>
          <h1>Облигации без сюрпризов. Портфель — под полным контролем.</h1>
          <p class="hero__lead">
            Скринер с риск-профилями, план закупок через брокера, радар рынка
            и алерты по пут-офертам — в одном окне. Спокойные решения вместо
            разрозненных таблиц.
          </p>
          <div class="hero__actions">
            <a class="btn btn--primary" href="#pricing">Открыть скринер</a>
            <a class="btn btn--ghost" href="#features">Смотреть, как работает</a>
          </div>
        </div>

        <div class="hero__stage reveal">
          <div class="hero__slabs" aria-hidden="true">
            <div class="slab slab--a"></div>
            <div class="slab slab--b"></div>
            <div class="slab slab--c"></div>
          </div>

          <div class="product-mock" data-testid="product-mock">
            <div class="product-mock__chrome">
              <div class="product-mock__dots" aria-hidden="true">
                <span></span><span></span><span></span>
              </div>
              bond-monitor.app / screener
            </div>
            <div class="product-mock__body">
              <aside class="product-mock__side" aria-hidden="true">
                <div class="side-link is-active">Скринер</div>
                <div class="side-link">Избранное</div>
                <div class="side-link">Портфели</div>
                <div class="side-link">Радар</div>
                <div class="side-link">Калькулятор</div>
              </aside>
              <div class="product-mock__main">
                <div class="mock-toolbar">
                  <div style="display:flex;gap:0.5rem;align-items:center;flex-wrap:wrap">
                    <h3>Скринер облигаций</h3>
                    <span class="chip chip--profile">Профиль: Normal</span>
                  </div>
                  <div class="chips">
                    <span class="chip">YTM ≥ 12%</span>
                    <span class="chip">≥ ruA−</span>
                    <span class="chip">Без дефолта</span>
                  </div>
                </div>
                <div style="overflow-x:auto">
                  <table class="mock-table">
                    <thead>
                      <tr>
                        <th>Бумага</th>
                        <th>YTM</th>
                        <th>Рейтинг</th>
                        <th>Дней</th>
                        <th>Скор</th>
                        <th>Оборот</th>
                        <th>Сигнал</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td>ОФЗ 26238</td>
                        <td class="ytm">14.2%</td>
                        <td>AAA</td>
                        <td>842</td>
                        <td class="score">91</td>
                        <td>2.1 млрд</td>
                        <td>—</td>
                      </tr>
                      <tr>
                        <td>Сбербанк 002P</td>
                        <td class="ytm">16.8%</td>
                        <td>ruAAA</td>
                        <td>412</td>
                        <td class="score">88</td>
                        <td>890 млн</td>
                        <td class="signal--put">Put 12д</td>
                      </tr>
                      <tr>
                        <td>Газпром Кап 1P</td>
                        <td class="ytm">17.4%</td>
                        <td>ruAA+</td>
                        <td>298</td>
                        <td class="score">84</td>
                        <td>540 млн</td>
                        <td>—</td>
                      </tr>
                      <tr>
                        <td>МТС 002P-06</td>
                        <td class="ytm">18.1%</td>
                        <td>ruA+</td>
                        <td>185</td>
                        <td class="score">79</td>
                        <td>220 млн</td>
                        <td class="signal--spread">Spread ↑</td>
                      </tr>
                      <tr>
                        <td>Сегежа 1P2</td>
                        <td class="ytm">22.4%</td>
                        <td>ruBB+</td>
                        <td>94</td>
                        <td class="score">61</td>
                        <td>48 млн</td>
                        <td class="signal--risk">Риск</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <div class="mock-alert">
                  <div>
                    <strong>3 действия в очереди</strong>
                    · пут-оферта Сбербанк до 28 июл
                  </div>
                  <a class="btn btn--primary" href="#portfolio">Открыть очередь</a>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section class="trust">
        <div class="shell trust__grid reveal">
          <article class="trust-card">
            <div class="trust-card__icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none"><path d="M12 3l2.4 4.9 5.4.8-3.9 3.8.9 5.4L12 15.9 7.2 18l.9-5.4L4.2 8.7l5.4-.8L12 3z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>
            </div>
            <div>
              <h3>3 риск-профиля</h3>
              <p>в скоре и подборе</p>
            </div>
          </article>
          <article class="trust-card">
            <div class="trust-card__icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none"><rect x="3" y="6" width="18" height="12" rx="2" stroke="currentColor" stroke-width="1.6"/><path d="M3 10h18M8 14h4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>
            </div>
            <div>
              <h3>T-Invest</h3>
              <p>заявки из очереди</p>
            </div>
          </article>
          <article class="trust-card">
            <div class="trust-card__icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="8" stroke="currentColor" stroke-width="1.6"/><circle cx="12" cy="12" r="4" stroke="currentColor" stroke-width="1.6"/><circle cx="12" cy="12" r="1.5" fill="currentColor"/></svg>
            </div>
            <div>
              <h3>Радар 24/7</h3>
              <p>сектора и спреды</p>
            </div>
          </article>
          <article class="trust-card">
            <div class="trust-card__icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none"><path d="M21 5 3 12.5l5.5 1.7L17 8l-6.8 7.2.3 4.3L13 16.5 18.5 20 21 5z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>
            </div>
            <div>
              <h3>Telegram</h3>
              <p>пуш по пут-офертам</p>
            </div>
          </article>
        </div>
      </section>

      <section class="section shell" id="features">
        <div class="section__head reveal">
          <h2>Полный контур работы с облигациями</h2>
          <p>
            Bond Monitor закрывает цикл: найти бумагу → собрать портфель →
            исполнить план → вовремя среагировать на событие.
          </p>
        </div>
        <div class="feature-grid">
          <article class="feature-card reveal">
            <span class="tag tag--mint">Скринер</span>
            <h3>Скор под ваш риск</h3>
            <p>
              Conservative, Normal, Aggressive — у каждого профиля свои веса
              YTM, риска и ликвидности. Одна таблица, три взгляда на рынок.
            </p>
          </article>
          <article class="feature-card reveal">
            <span class="tag tag--blue">Портфель</span>
            <h3>Стабильный план покупок</h3>
            <p>
              Автоподбор, реинвест купонов, deploy-сессия: фиксируете корзину
              и исполняете по одной кнопке — рекомендации остаются стабильными.
            </p>
          </article>
          <article class="feature-card reveal">
            <span class="tag tag--amber">Радар</span>
            <h3>Рынок шире портфеля</h3>
            <p>
              Аномалии спреда, heatmap секторов, идеи на просадке. Рыночные
              сигналы — отдельный контур рядом с вашими позициями.
            </p>
          </article>
        </div>
      </section>

      <section class="section shell" id="portfolio">
        <div class="split reveal">
          <div class="split__copy">
            <span class="tag tag--blue">Торговля</span>
            <h2>Зафиксировали план — и спокойно исполняем</h2>
            <p>
              Deploy Session держит корзину на время исполнения: buy и reinvest
              в одном снимке. Sell и пут-оферты обновляются live. Рекомендации
              остаются стабильными, пока вы покупаете.
            </p>
            <ul class="bullets">
              <li>Очередь: срочно / на контроле / покупки</li>
              <li>Лимитные заявки через T-Invest</li>
              <li>Sandbox для проверки без боевого счёта</li>
            </ul>
          </div>
          <div class="panel">
            <h3>Очередь действий</h3>
            <div class="queue-group">
              <div class="queue-group__label queue-group__label--urgent">Срочно</div>
              <div class="queue-item">
                <div>
                  <strong>Пут-оферта · Сбербанк 002P</strong>
                  <span>Подать до 28 июл · окно OPEN</span>
                </div>
                <a class="btn btn--danger-soft" href="#pricing">К заявке</a>
              </div>
            </div>
            <div class="queue-group">
              <div class="queue-group__label queue-group__label--buy">Покупки · deploy session</div>
              <div class="queue-item">
                <div>
                  <strong>Купить ОФЗ 26238</strong>
                  <span>12 лотов · ~118 400 ₽</span>
                </div>
                <a class="btn btn--primary" href="#pricing">Купить</a>
              </div>
              <div class="queue-item">
                <div>
                  <strong>Реинвест · купон Газпром</strong>
                  <span>остаток 24 800 ₽</span>
                </div>
                <a class="btn btn--primary" href="#pricing">Купить</a>
              </div>
            </div>
            <div class="session-bar">
              <span>Сессия активна · TTL 24ч</span>
              <span>Обновить план</span>
            </div>
          </div>
        </div>
      </section>

      <section class="section shell" id="radar">
        <div class="split split--reverse reveal">
          <div class="split__copy">
            <span class="tag tag--amber">Радар</span>
            <h2>Когда сектор трясёт — вы это видите первыми</h2>
            <p>
              Спред каждой бумаги сравнивается с похожими выпусками. Так
              аномалии, heatmap и идеи на просадке появляются раньше — и живут
              отдельно от ваших позиций.
            </p>
            <ul class="bullets bullets--amber">
              <li>Аномалии спреда относительно peers</li>
              <li>Heatmap секторов за 7 дней</li>
              <li>Сортировка «Сначала мои» для бумаг в портфелях</li>
            </ul>
          </div>
          <div class="panel" data-heatmap>
            <div style="display:flex;justify-content:space-between;align-items:center;gap:0.75rem;flex-wrap:wrap">
              <h3>Market Radar</h3>
              <span class="chip chip--profile" style="color:var(--accent);border-color:color-mix(in srgb, var(--accent) 40%, var(--border));background:color-mix(in srgb, var(--accent) 10%, transparent)">Сначала мои</span>
            </div>
            <p style="color:var(--text-muted);font-size:0.82rem;margin:0">Секторы · Δ спреда 7д</p>
            <div class="heatmap">
              <div class="heatmap__row">
                <div class="heatmap__meta"><span>Нефть и газ</span><span style="color:var(--danger)">+42 б.п.</span></div>
                <div class="heatmap__track"><div class="heatmap__bar" style="--w:95%;background:var(--danger)"></div></div>
              </div>
              <div class="heatmap__row">
                <div class="heatmap__meta"><span>Банки</span><span style="color:var(--accent-amber)">+18 б.п.</span></div>
                <div class="heatmap__track"><div class="heatmap__bar" style="--w:70%;background:var(--accent-amber)"></div></div>
              </div>
              <div class="heatmap__row">
                <div class="heatmap__meta"><span>Телеком</span><span style="color:var(--blue)">+6 б.п.</span></div>
                <div class="heatmap__track"><div class="heatmap__bar" style="--w:45%;background:var(--blue)"></div></div>
              </div>
              <div class="heatmap__row">
                <div class="heatmap__meta"><span>ОФЗ</span><span style="color:var(--accent)">−4 б.п.</span></div>
                <div class="heatmap__track"><div class="heatmap__bar" style="--w:30%;background:var(--accent)"></div></div>
              </div>
              <div class="heatmap__row">
                <div class="heatmap__meta"><span>Металлы</span><span style="color:#ff7a45">+28 б.п.</span></div>
                <div class="heatmap__track"><div class="heatmap__bar" style="--w:80%;background:#ff7a45"></div></div>
              </div>
            </div>
            <div class="dip">
              <strong>Dip idea</strong>
              <p>Нефть −15% · эмитент −24% без новостей → turbo-entry на радаре</p>
            </div>
          </div>
        </div>
      </section>

      <section class="section shell" id="alerts">
        <div class="section__head reveal">
          <h2>События, которые нельзя проспать</h2>
          <p>
            Пут-оферта открылась — Telegram. Рейтинг просел — в очередь на
            продажу. Критичное приходит пушем, остальное остаётся в приложении.
          </p>
        </div>
        <div class="alert-grid">
          <article class="alert-card reveal">
            <div class="alert-card__icon" style="color:var(--blue)">P</div>
            <h3>Пут-оферта</h3>
            <p style="color:var(--text-muted);font-size:0.92rem">
              Напоминание строго в окне приёма заявок — вовремя, без лишнего шума.
            </p>
          </article>
          <article class="alert-card reveal">
            <div class="alert-card__icon" style="color:var(--danger)">R</div>
            <h3>Эскалация риска</h3>
            <p style="color:var(--text-muted);font-size:0.92rem">
              Базовый рейтинг зафиксирован. Если эмитент просел — сигнал продать
              попадает в очередь.
            </p>
          </article>
          <article class="alert-card reveal">
            <div class="alert-card__icon" style="color:var(--accent)">TG</div>
            <h3>Telegram</h3>
            <p style="color:var(--text-muted);font-size:0.92rem">
              Только критичное. Остальное — во вкладке «Сигналы» портфеля.
            </p>
          </article>
        </div>
      </section>

      <section class="section shell" id="compare">
        <div class="section__head reveal">
          <h2>Что входит в Bond Monitor</h2>
          <p>Скринер, исполнение и сигналы — в одном продукте.</p>
        </div>
        <div class="compare reveal">
          <table>
            <thead>
              <tr>
                <th></th>
                <th>Скринер</th>
                <th>Трекер</th>
                <th>Bond Monitor</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Фильтры и YTM</td>
                <td>Да</td>
                <td>Частично</td>
                <td>Да + риск-профили</td>
              </tr>
              <tr>
                <td>Связка со счётом</td>
                <td>—</td>
                <td>Да</td>
                <td>T-Invest + очередь</td>
              </tr>
              <tr>
                <td>План покупок</td>
                <td>—</td>
                <td>—</td>
                <td>Deploy Session</td>
              </tr>
              <tr>
                <td>Радар рынка</td>
                <td>Иногда</td>
                <td>—</td>
                <td>Спред / сектора / dip</td>
              </tr>
              <tr>
                <td>Пут-оферты и риск</td>
                <td>Календарь</td>
                <td>Вручную</td>
                <td>Алерты + Telegram</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="section shell" id="pricing">
        <div class="section__head reveal">
          <h2>Простой прайс</h2>
          <p>
            Начните бесплатно. Подписка — когда понадобится брокер, радар и алерты.
          </p>
        </div>
        <div class="pricing-grid">
          <article class="price-card reveal" data-testid="pricing-free">
            <div class="price-card__plan">Free</div>
            <div class="price-card__amount">0 ₽</div>
            <p class="price-card__desc">Чтобы разобраться с рынком</p>
            <ul class="bullets">
              <li>Скринер с риск-профилями</li>
              <li>Избранное и базовые фильтры</li>
              <li>Калькулятор портфеля</li>
            </ul>
            <a class="btn btn--ghost btn--block" href="#top">Открыть скринер</a>
          </article>
          <article class="price-card price-card--pro reveal" data-testid="pricing-pro">
            <div class="price-card__plan">Pro</div>
            <div class="price-card__amount">990 ₽ <span>/ мес</span></div>
            <p class="price-card__desc">Когда портфель уже в деле</p>
            <ul class="bullets">
              <li>Всё из Free</li>
              <li>T-Invest: очередь и заявки</li>
              <li>Deploy Session</li>
              <li>Market Radar + сигналы</li>
              <li>Telegram-алерты по пут-офертам</li>
            </ul>
            <a class="btn btn--primary btn--block" href="#top">Подключить Pro</a>
          </article>
        </div>
        <p class="pricing-note">
          Цены ориентировочные — для лендинга. Финальный тариф уточним перед запуском.
        </p>
      </section>

      <section class="final-cta shell">
        <div class="final-cta__card reveal">
          <h2>Соберите облигации в одном рабочем контуре</h2>
          <p>
            Подключите счёт, выберите риск-профиль — и держите портфель в одном
            месте: скринер, план, сигналы.
          </p>
          <div class="final-cta__actions">
            <a class="btn btn--primary" href="#pricing">Начать с скринера</a>
            <a class="btn btn--ghost" href="#pricing">Связать T-Invest</a>
          </div>
        </div>
      </section>
    </main>

    <footer class="footer">
      <div class="shell">
        <div class="footer__top">
          <a class="brand" href="#top">
            <span class="brand__mark" aria-hidden="true"></span>
            Bond Monitor
          </a>
          <div class="footer__links">
            <a href="#features">Скринер</a>
            <a href="#portfolio">Портфель</a>
            <a href="#radar">Радар</a>
            <a href="#pricing">Прайс</a>
          </div>
        </div>
        <p class="footer__legal">
          © 2026 Bond Monitor. Данные Мосбиржи и T-Invest. Не является
          индивидуальной инвестиционной рекомендацией.
        </p>
      </div>
    </footer>
  </div>
`;

const nav = document.querySelector<HTMLElement>("[data-nav]");
const onScroll = () => {
  nav?.classList.toggle("is-scrolled", window.scrollY > 8);
};
onScroll();
window.addEventListener("scroll", onScroll, { passive: true });

const revealTargets = document.querySelectorAll(".reveal, [data-heatmap]");
const io = new IntersectionObserver(
  (entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        entry.target.classList.add("is-inview");
        io.unobserve(entry.target);
      }
    }
  },
  { threshold: 0.15, rootMargin: "0px 0px -40px 0px" },
);
revealTargets.forEach((el) => io.observe(el));

document.querySelector("[data-menu]")?.addEventListener("click", () => {
  const links = document.querySelector(".nav__links");
  if (!links) return;
  const open = links.getAttribute("data-open") === "true";
  links.setAttribute("data-open", open ? "false" : "true");
  (links as HTMLElement).style.display = open ? "" : "flex";
  (links as HTMLElement).style.position = open ? "" : "absolute";
  (links as HTMLElement).style.top = open ? "" : "4rem";
  (links as HTMLElement).style.right = open ? "" : "var(--pad)";
  (links as HTMLElement).style.flexDirection = open ? "" : "column";
  (links as HTMLElement).style.padding = open ? "" : "1rem";
  (links as HTMLElement).style.background = open ? "" : "var(--surface)";
  (links as HTMLElement).style.border = open ? "" : "1px solid var(--border)";
  (links as HTMLElement).style.borderRadius = open ? "" : "12px";
  (links as HTMLElement).style.zIndex = open ? "" : "30";
});
