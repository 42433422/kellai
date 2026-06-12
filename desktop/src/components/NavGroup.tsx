import { useState, useEffect } from "react";
import { ChevronDown } from "lucide-react";
import { clsx } from "clsx";
import type { LucideIcon } from "lucide-react";
import NavItem from "./NavItem";

export interface NavGroupItem {
  to: string;
  icon: LucideIcon;
  label: string;
  end?: boolean;
  badge?: number;
  dataTour?: string;
}

interface NavGroupProps {
  id: string;
  label: string;
  icon: LucideIcon;
  items: NavGroupItem[];
  collapsed: boolean;
  defaultOpen?: boolean;
}

const STORAGE_PREFIX = "kellai:nav-group:";

export default function NavGroup({
  id,
  label,
  icon: GroupIcon,
  items,
  collapsed,
  defaultOpen = false,
}: NavGroupProps) {
  const [open, setOpen] = useState(() => {
    const stored = localStorage.getItem(STORAGE_PREFIX + id);
    if (stored === "0") return false;
    if (stored === "1") return true;
    return defaultOpen;
  });

  useEffect(() => {
    localStorage.setItem(STORAGE_PREFIX + id, open ? "1" : "0");
  }, [id, open]);

  if (collapsed) {
    return (
      <div className="space-y-1">
        {items.map((item) => (
          <NavItem
            key={item.to}
            to={item.to}
            icon={item.icon}
            label={item.label}
            end={item.end}
            collapsed
            badge={item.badge}
            dataTour={item.dataTour}
          />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-0.5">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-400 transition-colors hover:bg-slate-50 hover:text-slate-600 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-300"
        aria-expanded={open}
      >
        <GroupIcon className="h-3.5 w-3.5 shrink-0" />
        <span className="flex-1 truncate text-left">{label}</span>
        <ChevronDown
          className={clsx("h-3.5 w-3.5 transition-transform", open && "rotate-180")}
        />
      </button>
      {open && (
        <div className="space-y-0.5 pl-1">
          {items.map((item) => (
            <NavItem
              key={item.to}
              to={item.to}
              icon={item.icon}
              label={item.label}
              end={item.end}
              collapsed={false}
              badge={item.badge}
              dataTour={item.dataTour}
            />
          ))}
        </div>
      )}
    </div>
  );
}
