import { Component, type ReactNode } from "react";

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
        <div className="w-[520px] rounded-lg border border-rose-900/60 bg-rose-950/30 p-6 text-sm">
          <h2 className="mb-2 text-base font-semibold text-rose-300">页面渲染出错</h2>
          <p className="mb-3 text-xs text-muted">
            该页面遇到未处理的异常。其他页面可能仍可正常访问；如需恢复当前页面请点击重试。
          </p>
          <pre className="mb-3 max-h-48 overflow-auto rounded border border-border bg-bg p-3 font-mono text-[11px] text-rose-300 whitespace-pre-wrap">
            {msg}
          </pre>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="rounded border border-border bg-bg px-3 py-1.5 text-xs text-muted hover:text-text"
            >
              重新加载
            </button>
            <button
              type="button"
              onClick={this.reset}
              className="rounded bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-600"
            >
              重试
            </button>
          </div>
        </div>
      </div>
    );
  }
}
