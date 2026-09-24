import { useEffect } from "react";

type Preference = 1 | 2 | 3 | 4 | 5;

type ShortcutOptions = {
  /** 回答画面(比較の試聴と回答)が表示されているときだけtrue。完了・一時停止・読込中・確認中は無効。 */
  enabled: boolean;
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

const TEXT_INPUT_EXEMPT = new Set(["checkbox", "radio", "range", "button", "submit", "reset"]);
const INTERACTIVE = "button, a[href], summary, input, [role='button'], [role='link'], [role='radio'], [role='checkbox'], [role='switch'], [role='slider']";

function isEditingText(target: Element): boolean {
  if (target instanceof HTMLInputElement) return !TEXT_INPUT_EXEMPT.has(target.type);
  if (target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) return true;
  return target instanceof HTMLElement && target.isContentEditable;
}

export function useDeckShortcuts(options: ShortcutOptions): void {
  useEffect(() => {
    if (!options.enabled) return;
    const handleShortcut = (event: KeyboardEvent) => {
      // ブラウザ・OSのショートカット(Cmd/Ctrl+0 のズーム等)を奪わない。
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey || event.isComposing) return;
      const target = event.target instanceof Element ? event.target : null;
      if (target && isEditingText(target)) return;
      // フォーカス中のボタン・リンク等では Space / Enter をその操作に任せる。
      // ただし選好(role=radio)ではネイティブのラジオと同じく Enter で記録する。
      const control = target?.closest(INTERACTIVE) ?? null;

      const key = event.key.toLowerCase();
      if (key === "?" || (event.key === "/" && event.shiftKey)) {
        event.preventDefault();
        options.onToggleHelp();
      } else if (key === "0") {
        if (event.repeat || !options.canSkip) return;
        event.preventDefault();
        options.onSkip();
      } else if (event.code === "Space" || event.key === " ") {
        if (control) return;
        event.preventDefault();
        if (!event.repeat) options.onSwitchSlot();
      } else if (/^[1-5]$/.test(key) && options.canAnswer) {
        event.preventDefault();
        options.onPreference(Number(key) as Preference);
      } else if ((key === "a" || key === "b") && options.preference !== null && options.canAnswer) {
        event.preventDefault();
        options.onToggleBlocker(key);
      } else if (key === "n" && options.preference !== null && options.canAnswer) {
        event.preventDefault();
        options.onFocusComment();
      } else if (event.key === "Enter") {
        if (control && control.getAttribute("role") !== "radio") return;
        if (event.repeat || !options.canSubmit) return;
        event.preventDefault();
        options.onSubmit();
      }
    };
    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, [options]);
}
