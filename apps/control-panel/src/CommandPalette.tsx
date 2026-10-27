// SA-20: ⌘K "Jump to" -- type a few letters of a screen and press Enter.
// Arrow keys move, Escape closes.

import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CornerDownLeft, Search } from 'lucide-react';
import { NAV_ITEMS } from './navigation';

export default function CommandPalette({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? NAV_ITEMS.filter((i) => `${i.label} ${i.hint}`.toLowerCase().includes(q)) : NAV_ITEMS;
  }, [query]);

  useEffect(() => input.current?.focus(), []);

  const go = (to: string) => {
    navigate(to);
    onClose();
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') onClose();
    else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive((a) => Math.min(results.length - 1, a + 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((a) => Math.max(0, a - 1));
    } else if (e.key === 'Enter' && results[active]) go(results[active].to);
  };

  return (
    <div className="cmdk-backdrop" onMouseDown={onClose}>
      <div className="cmdk" role="dialog" aria-label="Jump to a screen" onMouseDown={(e) => e.stopPropagation()} onKeyDown={onKey}>
        <div className="cmdk-input">
          <Search size={16} />
          <input
            ref={input}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
            }}
            placeholder="Jump to a screen…"
            aria-label="Search screens"
          />
          <kbd>esc</kbd>
        </div>
        <div className="cmdk-list" role="listbox">
          {results.length === 0 && <div className="cmdk-empty">No screen matches “{query}”.</div>}
          {results.map((item, i) => (
            <button
              key={item.to}
              role="option"
              aria-selected={i === active}
              className={`cmdk-item${i === active ? ' on' : ''}`}
              onMouseEnter={() => setActive(i)}
              onClick={() => go(item.to)}
            >
              <span className="cmdk-icon">
                <item.icon size={15} strokeWidth={1.75} />
              </span>
              <span className="cmdk-label">{item.label}</span>
              <span className="cmdk-hint">{item.hint}</span>
              {i === active && <CornerDownLeft size={13} className="cmdk-enter" />}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
