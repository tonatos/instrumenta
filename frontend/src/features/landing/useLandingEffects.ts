import { useEffect } from "react";

/** Sticky nav scroll state + reveal-on-intersect for landing sections. */
export function useLandingEffects(root: HTMLElement | null) {
  useEffect(() => {
    if (!root) return;

    const nav = root.querySelector<HTMLElement>("[data-nav]");
    const onScroll = () => {
      nav?.classList.toggle("is-scrolled", window.scrollY > 8);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });

    const revealTargets = root.querySelectorAll(".reveal, [data-heatmap]");
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

    return () => {
      window.removeEventListener("scroll", onScroll);
      io.disconnect();
    };
  }, [root]);
}
