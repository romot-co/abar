export function variantKindLabel(kind: string | null | undefined): string {
  return ({ candidate: "候補", current_best: "現在最良", baseline: "基準版", control: "対照", reference: "基準音", ablation: "アブレーション", tap: "段の出力", symptom_region: "症状区間" } as Record<string, string>)[kind ?? ""] ?? "";
}
