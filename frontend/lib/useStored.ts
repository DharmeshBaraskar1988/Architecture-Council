"use client";

import { useEffect, useRef, useState } from "react";

// useState that survives leaving the page and coming back (sessionStorage: per tab, gone when the tab closes).
// The stored value is restored after mount, so the server render and the first client render still match.
// `skip`: don't restore (e.g. the URL asked for a specific position), but keep saving.
export function useStored<T>(key: string, initial: T, skip = false): [T, React.Dispatch<React.SetStateAction<T>>] {
  const [value, setValue] = useState<T>(initial);
  const restored = useRef(false);

  useEffect(() => {
    if (!skip) {
      try {
        const raw = sessionStorage.getItem(key);
        if (raw !== null) setValue(JSON.parse(raw) as T);
      } catch { /* storage blocked or bad JSON: keep the default */ }
    }
    restored.current = true;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  useEffect(() => {
    if (!restored.current) return;          // don't overwrite the saved value with the default before it is restored
    try { sessionStorage.setItem(key, JSON.stringify(value)); } catch { /* storage blocked */ }
  }, [key, value]);

  return [value, setValue];
}
