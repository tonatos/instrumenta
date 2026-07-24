"use client";

import type { ReactNode } from "react";
import { HelpCircle } from "lucide-react";
import { Tooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export function FieldHelp({
  content,
  label = "Подробнее",
  side = "top",
  className,
  stopPropagation = false,
}: {
  content: ReactNode;
  /** Accessible name for the help button */
  label?: string;
  side?: "top" | "right" | "bottom" | "left";
  className?: string;
  /** Use in sortable table headers so clicking ? does not toggle sort */
  stopPropagation?: boolean;
}) {
  return (
    <Tooltip
      content={<span className="leading-relaxed">{content}</span>}
      side={side}
    >
      <button
        type="button"
        className={cn(
          "inline-flex size-10 shrink-0 items-center justify-center rounded-sm text-muted-foreground/60",
          "hover:text-muted-foreground focus:outline-none focus-visible:ring-1 focus-visible:ring-ring",
          "-my-2.5 -mx-2",
          className,
        )}
        aria-label={label}
        onClick={stopPropagation ? (e) => e.stopPropagation() : undefined}
        onPointerDown={stopPropagation ? (e) => e.stopPropagation() : undefined}
      >
        <HelpCircle className="h-3.5 w-3.5" aria-hidden />
      </button>
    </Tooltip>
  );
}
