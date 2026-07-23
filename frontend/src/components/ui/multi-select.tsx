"use client";

import * as React from "react";
import { Check, ChevronDown, Search, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { PopoverRoot, PopoverTrigger, PopoverContent } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export interface MultiSelectOption {
  value: string;
  label: string;
}

interface MultiSelectProps {
  options: MultiSelectOption[];
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  className?: string;
  disabled?: boolean;
  /** Enable search when options list is long. */
  searchable?: boolean;
  "aria-label"?: string;
  "data-testid"?: string;
}

export function MultiSelect({
  options,
  values,
  onChange,
  placeholder = "Все",
  searchPlaceholder = "Поиск…",
  emptyText = "Ничего не найдено",
  className,
  disabled,
  searchable = false,
  "aria-label": ariaLabel,
  "data-testid": testId,
}: MultiSelectProps) {
  const [open, setOpen] = React.useState(false);
  const [search, setSearch] = React.useState("");

  const filtered = React.useMemo(() => {
    if (!searchable || !search.trim()) return options;
    const q = search.toLowerCase();
    return options.filter(
      (o) => o.label.toLowerCase().includes(q) || o.value.toLowerCase().includes(q),
    );
  }, [options, search, searchable]);

  const selectedLabels = React.useMemo(() => {
    const set = new Set(values);
    return options.filter((o) => set.has(o.value)).map((o) => o.label);
  }, [options, values]);

  const triggerLabel = (() => {
    if (selectedLabels.length === 0) return placeholder;
    if (selectedLabels.length === 1) return selectedLabels[0];
    return `${selectedLabels.length} выбрано`;
  })();

  const toggle = (value: string) => {
    if (values.includes(value)) {
      onChange(values.filter((v) => v !== value));
    } else {
      onChange([...values, value]);
    }
  };

  return (
    <PopoverRoot
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setSearch("");
      }}
    >
      <PopoverTrigger asChild>
        <button
          type="button"
          disabled={disabled}
          aria-label={ariaLabel}
          aria-expanded={open}
          data-testid={testId}
          className={cn(
            "flex h-9 w-full min-h-10 items-center justify-between gap-2 rounded-md border border-border bg-card px-3 py-2 text-sm shadow-sm",
            "focus:outline-none focus:ring-1 focus:ring-ring",
            "disabled:cursor-not-allowed disabled:opacity-50",
            className,
          )}
        >
          <span
            className={cn(
              "min-w-0 truncate text-left",
              selectedLabels.length === 0 && "text-muted-foreground",
            )}
          >
            {triggerLabel}
          </span>
          <span className="flex shrink-0 items-center gap-1">
            {values.length > 0 && (
              <Badge variant="secondary" className="h-5 px-1.5 text-[10px] font-medium tabular-nums">
                {values.length}
              </Badge>
            )}
            <ChevronDown className="h-4 w-4 opacity-50" aria-hidden />
          </span>
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="w-[var(--radix-popover-trigger-width)] min-w-[14rem] p-0"
        align="start"
      >
        {searchable && (
          <div className="flex items-center border-b border-border px-3">
            <Search className="mr-2 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
            <input
              autoFocus
              className="flex h-10 w-full bg-transparent py-2 text-sm outline-none placeholder:text-muted-foreground"
              placeholder={searchPlaceholder}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label={searchPlaceholder}
            />
          </div>
        )}
        <div className="max-h-60 overflow-y-auto py-1" role="listbox" aria-multiselectable>
          {filtered.length === 0 ? (
            <p className="px-3 py-4 text-center text-sm text-muted-foreground">{emptyText}</p>
          ) : (
            filtered.map((opt) => {
              const checked = values.includes(opt.value);
              return (
                <button
                  key={opt.value}
                  type="button"
                  role="option"
                  aria-selected={checked}
                  className={cn(
                    "flex min-h-10 w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted/50",
                    checked && "bg-accent/40",
                  )}
                  onClick={() => toggle(opt.value)}
                >
                  <span
                    className={cn(
                      "flex h-4 w-4 shrink-0 items-center justify-center rounded-sm border border-border",
                      checked && "border-primary bg-primary text-primary-foreground",
                    )}
                    aria-hidden
                  >
                    {checked && <Check className="h-3 w-3" />}
                  </span>
                  <span className="truncate">{opt.label}</span>
                </button>
              );
            })
          )}
        </div>
        {values.length > 0 && (
          <div className="border-t border-border p-1">
            <button
              type="button"
              className="flex min-h-10 w-full items-center justify-center gap-1.5 rounded-sm px-3 text-sm text-muted-foreground hover:bg-muted/50 hover:text-foreground"
              onClick={() => onChange([])}
            >
              <X className="h-3.5 w-3.5" aria-hidden />
              Сбросить
            </button>
          </div>
        )}
      </PopoverContent>
    </PopoverRoot>
  );
}
