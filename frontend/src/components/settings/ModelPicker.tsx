import { Check, ChevronDown } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

interface ModelPickerProps {
  value: string;
  options: string[];
  onChange: (value: string) => void;
  ariaLabel: string;
  optionsAriaLabel: string;
}

export function ModelPicker({
  value,
  options,
  onChange,
  ariaLabel,
  optionsAriaLabel,
}: ModelPickerProps) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const rootRef = useRef<HTMLDivElement>(null);
  const listId = useId();
  const uniqueOptions = Array.from(new Set(options.filter(Boolean)));

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, []);

  const openList = () => {
    setOpen(true);
    setActiveIndex(uniqueOptions.indexOf(value));
  };

  const select = (model: string) => {
    onChange(model);
    setOpen(false);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      setOpen(false);
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (uniqueOptions.length === 0) return;
      if (!open) {
        openList();
        return;
      }
      const direction = event.key === "ArrowDown" ? 1 : -1;
      setActiveIndex((current) => {
        if (current < 0) return direction > 0 ? 0 : uniqueOptions.length - 1;
        return (current + direction + uniqueOptions.length) % uniqueOptions.length;
      });
      return;
    }
    if (event.key === "Enter" && open && activeIndex >= 0) {
      event.preventDefault();
      const activeModel = uniqueOptions[activeIndex];
      if (activeModel) select(activeModel);
    }
  };

  return (
    <div ref={rootRef} className="relative min-w-0 flex-1">
      <div className="relative">
        <input
          value={value}
          onChange={(event) => {
            onChange(event.target.value);
            setActiveIndex(-1);
          }}
          onClick={openList}
          onFocus={openList}
          onKeyDown={onKeyDown}
          className="w-full rounded-md border bg-background py-2 pl-3 pr-10 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20"
          role="combobox"
          aria-label={ariaLabel}
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={open && activeIndex >= 0 ? `${listId}-${activeIndex}` : undefined}
          required
        />
        <button
          type="button"
          onClick={() => open ? setOpen(false) : openList()}
          className="absolute inset-y-0 right-0 inline-flex w-10 items-center justify-center rounded-r-md text-muted-foreground transition hover:bg-muted/70 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary/40"
          aria-label={optionsAriaLabel}
          aria-expanded={open}
          aria-controls={listId}
        >
          <ChevronDown className={`h-4 w-4 transition-transform duration-150 ${open ? "rotate-180" : ""}`} />
        </button>
      </div>

      {open && uniqueOptions.length > 0 && (
        <div
          id={listId}
          role="listbox"
          aria-label={optionsAriaLabel}
          className="absolute z-50 mt-1.5 max-h-64 w-full overflow-y-auto rounded-md border bg-card p-1.5 shadow-lg ring-1 ring-black/5"
        >
          {uniqueOptions.map((model, index) => {
            const selected = model === value;
            const active = index === activeIndex;
            return (
              <button
                key={model}
                id={`${listId}-${index}`}
                type="button"
                role="option"
                aria-selected={selected}
                onMouseEnter={() => setActiveIndex(index)}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => select(model)}
                className={`flex w-full items-center justify-between gap-3 rounded px-2.5 py-2 text-left text-sm transition-colors ${
                  active ? "bg-muted text-foreground" : "text-foreground hover:bg-muted/70"
                }`}
              >
                <span className="min-w-0 truncate font-medium">{model}</span>
                <Check className={`h-4 w-4 shrink-0 text-primary ${selected ? "opacity-100" : "opacity-0"}`} />
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
