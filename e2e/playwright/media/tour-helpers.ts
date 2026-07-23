import type { Locator, Page } from "@playwright/test";

const CURSOR_ID = "tour-promo-cursor";

/**
 * Install a visible CSS cursor overlay. Playwright does not record the system cursor.
 * Call once before any navigation; reinjected via addInitScript on every document.
 */
export async function installTourCursor(page: Page): Promise<void> {
  await page.addInitScript((id: string) => {
    const ensure = () => {
      if (document.getElementById(id)) return;
      const style = document.createElement("style");
      style.textContent = `
        #${id} {
          position: fixed;
          left: 0;
          top: 0;
          width: 22px;
          height: 22px;
          margin-left: -4px;
          margin-top: -4px;
          border-radius: 50%;
          border: 2px solid rgba(255, 92, 122, 0.95);
          background: rgba(255, 92, 122, 0.28);
          box-shadow:
            0 0 0 1px rgba(255, 255, 255, 0.55),
            0 4px 14px rgba(0, 0, 0, 0.35);
          pointer-events: none;
          z-index: 2147483647;
          transform: translate(-50%, -50%);
          transition: width 80ms ease, height 80ms ease, background 80ms ease;
          will-change: left, top;
        }
        #${id}[data-down="true"] {
          width: 16px;
          height: 16px;
          background: rgba(255, 92, 122, 0.55);
        }
      `;
      document.documentElement.appendChild(style);
      const el = document.createElement("div");
      el.id = id;
      el.setAttribute("aria-hidden", "true");
      document.documentElement.appendChild(el);

      window.addEventListener(
        "mousemove",
        (e) => {
          el.style.left = `${e.clientX}px`;
          el.style.top = `${e.clientY}px`;
        },
        { passive: true },
      );
      window.addEventListener(
        "mousedown",
        () => {
          el.dataset.down = "true";
        },
        { passive: true },
      );
      window.addEventListener(
        "mouseup",
        () => {
          el.dataset.down = "false";
        },
        { passive: true },
      );
    };
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", ensure);
    } else {
      ensure();
    }
  }, CURSOR_ID);
}

export async function dwell(page: Page, ms: number): Promise<void> {
  await page.waitForTimeout(ms);
}

export async function tourMove(page: Page, locator: Locator, steps = 18): Promise<void> {
  const box = await locator.boundingBox();
  if (!box) {
    await locator.scrollIntoViewIfNeeded();
  }
  const target = (await locator.boundingBox()) ?? box;
  if (!target) return;
  const x = target.x + target.width / 2;
  const y = target.y + Math.min(target.height / 2, 18);
  await page.mouse.move(x, y, { steps });
  await dwell(page, 180);
}

export async function tourClick(page: Page, locator: Locator): Promise<void> {
  await locator.scrollIntoViewIfNeeded();
  await tourMove(page, locator);
  await locator.click();
  await dwell(page, 280);
}

export async function tourFill(
  page: Page,
  locator: Locator,
  value: string,
): Promise<void> {
  await locator.scrollIntoViewIfNeeded();
  await tourMove(page, locator, 12);
  await locator.click();
  await locator.fill("");
  // Type slowly for a more promo-like feel
  await locator.pressSequentially(value, { delay: 45 });
  await dwell(page, 350);
}

/** Click a desktop sidebar NavLink by its visible label. */
export async function tourNav(page: Page, label: string): Promise<void> {
  const nav = page.getByRole("navigation", { name: /Основная навигация/i });
  const link = nav.getByRole("link", { name: label, exact: true });
  await tourClick(page, link);
}

export async function smoothScroll(
  page: Page,
  opts: { deltaY?: number; steps?: number; pauseMs?: number } = {},
): Promise<void> {
  const deltaY = opts.deltaY ?? 420;
  const steps = opts.steps ?? 1;
  const pauseMs = opts.pauseMs ?? 750;
  for (let i = 0; i < steps; i++) {
    await page.evaluate((dy) => {
      window.scrollBy({ top: dy, behavior: "smooth" });
    }, deltaY);
    await dwell(page, pauseMs);
  }
}

export async function smoothScrollTo(
  page: Page,
  locator: Locator,
  pauseMs = 900,
): Promise<void> {
  await locator.scrollIntoViewIfNeeded();
  await page.evaluate(() => {
    // Prefer smooth if the browser supports it after scrollIntoViewIfNeeded
    window.scrollBy({ top: -40, behavior: "smooth" });
  });
  await dwell(page, pauseMs);
}
