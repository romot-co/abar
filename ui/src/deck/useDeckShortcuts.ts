import { useEffect } from "react";

type Preference = 1 | 2 | 3 | 4 | 5;

type ShortcutOptions = {
  deliveryPresent: boolean;
  canAnswer: boolean;
  canSkip: boolean;
  canSubmit: boolean;
  preference: Preference | null;
  onToggleHelp: () => void;
  onSkip: () => void;
  onSwitchSlot: () => void;
  onPreference: (value: Preference) => void;
  onToggleBlocker: (slot: "a" | "b") => void;
  onFocusComment: () => void;
  onSubmit: () => void;
};

export function useDeckShortcuts(options: ShortcutOptions): void {
  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      const target = event.target;
      const editingText =
        target instanceof HTMLInputElement &&
        !["checkbox", "range", "radio"].includes(target.type);
      if (editingText) return;

      const key = event.key.toLowerCase();
      if (key === "?" || (event.key === "/" && event.shiftKey)) {
        event.preventDefault();
        options.onToggleHelp();
      } else if (key === "0" && options.canSkip) {
        event.preventDefault();
        options.onSkip();
      } else if (event.code === "Space" && options.deliveryPresent) {
        event.preventDefault();
        options.onSwitchSlot();
      } else if (/^[1-5]$/.test(key) && options.deliveryPresent && options.canAnswer) {
        event.preventDefault();
        options.onPreference(Number(key) as Preference);
      } else if (
        (key === "a" || key === "b") &&
        options.preference !== null &&
        options.deliveryPresent &&
        options.canAnswer
      ) {
        event.preventDefault();
        options.onToggleBlocker(key);
      } else if (key === "n" && options.deliveryPresent && options.preference !== null) {
        event.preventDefault();
        options.onFocusComment();
      } else if (event.key === "Enter" && options.canSubmit) {
        event.preventDefault();
        options.onSubmit();
      }
    };
    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, [options]);
}
