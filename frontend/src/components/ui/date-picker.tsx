"use client";

import * as React from "react";
import { CalendarIcon } from "lucide-react";
import { ru } from "react-day-picker/locale";

import { cn, formatDate, isoToDate, dateToIso, todayIsoDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { PopoverContent, PopoverRoot, PopoverTrigger } from "@/components/ui/popover";

export function DatePicker({
  value,
  onChange,
  min,
  id,
  className,
  placeholder = "Выберите дату",
  disabled = false,
}: {
  value: string;
  onChange: (value: string) => void;
  min?: string;
  id?: string;
  className?: string;
  placeholder?: string;
  disabled?: boolean;
}) {
  const [open, setOpen] = React.useState(false);
  const selected = isoToDate(value);
  const minDate = min ? isoToDate(min) : isoToDate(todayIsoDate());

  return (
    <PopoverRoot open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          disabled={disabled}
          data-empty={!selected}
          className={cn(
            "h-9 w-full justify-start gap-2 px-3 font-normal data-[empty=true]:text-muted-foreground",
            className,
          )}
        >
          <CalendarIcon className="size-4 shrink-0 text-muted-foreground" />
          {selected ? formatDate(value) : <span>{placeholder}</span>}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="start">
        <Calendar
          mode="single"
          locale={ru}
          selected={selected}
          defaultMonth={selected ?? minDate}
          captionLayout="dropdown"
          fromYear={minDate?.getFullYear() ?? new Date().getFullYear()}
          toYear={(minDate?.getFullYear() ?? new Date().getFullYear()) + 20}
          disabled={minDate ? { before: minDate } : undefined}
          onSelect={(date) => {
            if (!date) return;
            onChange(dateToIso(date));
            setOpen(false);
          }}
        />
      </PopoverContent>
    </PopoverRoot>
  );
}
