import { useEffect, useRef } from "react";

type Props = {
  open: boolean;
  onClose: () => void;
};

const VIDEO_SRC = "/media/product-tour.webm";
const POSTER_SRC = "/media/product-tour-poster.jpg";

export function ScreencastModal({ open, onClose }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    const video = videoRef.current;
    if (video) {
      void video.play().catch(() => undefined);
    }
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="video-modal"
      role="dialog"
      aria-modal="true"
      aria-label="Демо Instrumenta"
      data-testid="screencast-modal"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="video-modal__panel">
        <div className="video-modal__bar">
          <span>Как работает стратегия · ~40 сек</span>
          <button
            type="button"
            className="video-modal__close"
            onClick={onClose}
            aria-label="Закрыть"
            data-testid="screencast-close"
          >
            ✕
          </button>
        </div>
        <video
          ref={videoRef}
          controls
          playsInline
          poster={POSTER_SRC}
          src={VIDEO_SRC}
        >
          <track kind="captions" />
        </video>
      </div>
    </div>
  );
}
