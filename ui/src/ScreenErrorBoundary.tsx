import { Component, type ReactNode } from "react";

export class ScreenErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <main className="centered error-panel">
        <h1>画面を表示できません</h1>
        <p>再読み込みしてください。開発中の更新後も続く場合は、ABARサーバーを再起動してください。</p>
        <button type="button" onClick={() => window.location.reload()}>再読み込み</button>
      </main>
    );
  }
}
