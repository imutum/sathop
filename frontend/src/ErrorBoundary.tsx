import { Component, type ReactNode } from "react";
import { ActionButton } from "./ui";

type Props = { children: ReactNode };
type State = { err: Error | null };

export class ErrorBoundary extends Component<Props, State> {
  state: State = { err: null };

  static getDerivedStateFromError(err: Error): State {
    return { err };
  }

  componentDidCatch(err: Error, info: { componentStack: string }) {
    console.error("[sathop] render crash:", err, info.componentStack);
  }

  reset = () => this.setState({ err: null });

  render() {
    if (!this.state.err) return this.props.children;
    const msg = this.state.err.message || String(this.state.err);
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="w-full max-w-lg rounded-2xl border border-danger/30 bg-danger/5 p-6 shadow-card">
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-danger">
            页面崩溃
          </div>
          <h2 className="font-display mt-2 text-lg font-semibold tracking-tight">
            渲染时抛出未捕获异常
          </h2>
          <p className="mt-2 text-xs text-muted">
            其他页面可能仍可访问；点击下方按钮重试或重新加载。
          </p>
          <pre className="mt-3 max-h-48 overflow-auto rounded-lg border border-border bg-bg p-3 font-mono text-[11px] text-danger whitespace-pre-wrap">
            {msg}
          </pre>
          <div className="mt-4 flex justify-end gap-2">
            <ActionButton onClick={() => window.location.reload()}>重新加载</ActionButton>
            <ActionButton tone="primary" onClick={this.reset}>重试当前页</ActionButton>
          </div>
        </div>
      </div>
    );
  }
}
