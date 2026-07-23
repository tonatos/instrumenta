type Props = {
  onPlay: () => void;
};

/** CSS product mock of a managed portfolio (not screener). */
export function PortfolioHeroMock({ onPlay }: Props) {
  return (
    <div className="hero-play-wrap">
      <div className="product-mock" data-testid="product-mock">
        <div className="product-mock__chrome">
          <div className="product-mock__dots" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
          instrumenta.trade / portfolio
        </div>
        <div className="product-mock__body">
          <aside className="product-mock__side" aria-hidden="true">
            <div className="side-link">Скринер</div>
            <div className="side-link is-active">Портфель</div>
            <div className="side-link">Радар</div>
            <div className="side-link">Калькулятор</div>
            <div className="side-link">Аккаунт</div>
          </aside>
          <div className="product-mock__main">
            <div className="mock-toolbar">
              <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
                <h3>Стратегия · Normal</h3>
                <span className="chip chip--profile">Горизонт 18 мес</span>
              </div>
              <div className="chips">
                <span className="chip">Короткие</span>
                <span className="chip">≥ ruA−</span>
                <span className="chip">Реинвест</span>
              </div>
            </div>

            <div className="mock-metrics">
              <div className="mock-metric">
                <div className="mock-metric__label">Капитал</div>
                <div className="mock-metric__value">312 400 ₽</div>
              </div>
              <div className="mock-metric">
                <div className="mock-metric__label">Мод. XIRR</div>
                <div className="mock-metric__value" style={{ color: "var(--accent)" }}>
                  18.4%
                </div>
              </div>
              <div className="mock-metric">
                <div className="mock-metric__label">Позиций</div>
                <div className="mock-metric__value">8</div>
              </div>
              <div className="mock-metric">
                <div className="mock-metric__label">Свободно</div>
                <div className="mock-metric__value">24 800 ₽</div>
              </div>
            </div>

            <div style={{ overflowX: "auto" }}>
              <table className="mock-table">
                <thead>
                  <tr>
                    <th>Позиция</th>
                    <th>YTM</th>
                    <th>Дней</th>
                    <th>Скор</th>
                    <th>Статус</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>ОФЗ 26238</td>
                    <td className="ytm">14.2%</td>
                    <td>118</td>
                    <td className="score">91</td>
                    <td>—</td>
                  </tr>
                  <tr>
                    <td>Сбербанк 002P</td>
                    <td className="ytm">16.8%</td>
                    <td>94</td>
                    <td className="score">88</td>
                    <td className="signal--put">Put 12д</td>
                  </tr>
                  <tr>
                    <td>Газпром Кап 1P</td>
                    <td className="ytm">17.4%</td>
                    <td>156</td>
                    <td className="score">84</td>
                    <td>—</td>
                  </tr>
                  <tr>
                    <td>МТС 002P-06</td>
                    <td className="ytm">18.1%</td>
                    <td>72</td>
                    <td className="score">79</td>
                    <td className="signal--spread">Реинвест</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div className="mock-alert">
              <div>
                <strong>План закупок зафиксирован</strong>
                {" · "}3 покупки · Deploy Session 24ч
              </div>
              <span className="btn btn--primary" aria-hidden="true">
                К очереди
              </span>
            </div>
          </div>
        </div>
      </div>

      <button
        type="button"
        className="hero-play"
        onClick={onPlay}
        aria-label="Смотреть демо"
        data-testid="hero-play"
      >
        <span className="hero-play__btn" aria-hidden="true">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
            <path d="M8 5.14v13.72L19 12 8 5.14z" />
          </svg>
        </span>
      </button>
    </div>
  );
}
