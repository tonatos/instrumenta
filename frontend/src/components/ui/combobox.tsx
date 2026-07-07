"use client";

import * as React from "react";
import { Check, ChevronDown, Search } from "lucide-react";
import { PopoverRoot, PopoverTrigger, PopoverContent } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export interface ComboboxOption {
  value: string;
  label: string;
  description?: string;
}

interface ComboboxProps {
  options: ComboboxOption[];
  value: string | null;
  onChange: (value: string | null) => void;
  placeholder?: string;
  searchPlaceholder?: string;
  className?: string;
  disabled?: boolean;
  emptyText?: string;
  allowDeselect?: boolean;
}

export function Combobox({
  options,
  value,
  onChange,
  placeholder = "Выбрать…",
  searchPlaceholder = "Поиск…",
  className,
  disabled,
  emptyText = "Ничего не найдено",
  allowDeselect = true,
}: ComboboxProps) {
  const [open, setOpen] = React.useState(false);
  const [search, setSearch] = React.useState("");

  const filtered = React.useMemo(() => {
    if (!search.trim()) return options;
    const q = search.toLowerCase();
    return options.filter(
      (o) =>
        o.label.toLowerCase().includes(q) ||
        o.value.toLowerCase().includes(q) ||
        (o.description?.toLowerCase().includes(q) ?? false),
    );
  }, [options, search]);

  const selected = options.find((o) => o.value === value);

  return (
    <PopoverRoot open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          disabled={disabled}
          className={cn(
            "flex h-9 w-full items-center justify-between rounded-md border border-border bg-card px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
            className,
          )}
        >
          <span className={cn("truncate", !selected && "text-muted-foreground")}>
            {selected ? selected.label : placeholder}
          </span>
          <ChevronDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-[var(--radix-popover-trigger-width)] p-0" align="start">
        <div className="flex items-center border-b border-border px-3">
          <Search className="mr-2 h-4 w-4 shrink-0 text-muted-foreground" />
          <input
            autoFocus
            className="flex h-9 w-full bg-transparent py-2 text-sm outline-none placeholder:text-muted-foreground"
            placeholder={searchPlaceholder}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="max-h-60 overflow-y-auto">
          {allowDeselect && value && (
            <button
              type="button"
              className="flex w-full items-center px-3 py-2 text-sm text-muted-foreground hover:bg-muted/50"
              onClick={() => {
                onChange(null);
                setOpen(false);
                setSearch("");
              }}
            >
              Сбросить выбор
            </button>
          )}
          {filtered.length === 0 ? (
            <p className="px-3 py-4 text-center text-sm text-muted-foreground">{emptyText}</p>
          ) : (
            filtered.map((opt) => (
              <button
                key={opt.value}
                type="button"
                className={cn(
                  "flex w-full items-start gap-2 px-3 py-2 text-left text-sm hover:bg-muted/50",
                  value === opt.value && "bg-accent",
                )}
                onClick={() => {
                  if (allowDeselect && opt.value === value) {
                    onChange(null);
                  } else {
                    onChange(opt.value);
                  }
                  setOpen(false);
                  setSearch("");
                }}
              >
                <Check
                  className={cn(
                    "mt-0.5 h-4 w-4 shrink-0",
                    value === opt.value ? "opacity-100" : "opacity-0",
                  )}
                />
                <div className="min-w-0">
                  <div className="truncate font-medium">{opt.label}</div>
                  {opt.description && (
                    <div className="truncate text-xs text-muted-foreground">{opt.description}</div>
                  )}
                </div>
              </button>
            ))
          )}
        </div>
      </PopoverContent>
    </PopoverRoot>
  );
}
