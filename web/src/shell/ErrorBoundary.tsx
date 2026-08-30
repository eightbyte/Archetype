/**
 * One failing region must not blank the workspace (P1-13).
 *
 * A render error inside the outline panel takes the outline panel, and leaves the editor and the
 * agent panel working — which matters most in the case that actually happens: a panel that
 * cannot draw something while there is unsaved writing in the editor beside it. Wrapping each
 * region separately is what makes that true.
 *
 * A class component because React offers no hook for this; `componentDidCatch` is the whole API.
 * The error goes to the console, where a developer will look, and its message goes on screen,
 * because "something went wrong" is not a bug report.
 */

import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';

export interface ErrorBoundaryProps {
  /** Names the region in the fallback, so it is obvious which part failed. */
  region: string;
  children: ReactNode;
  /** Tests assert on this rather than on the console. */
  onError?: (error: Error, info: ErrorInfo) => void;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  override state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    // eslint-disable-next-line no-console -- the console is where a developer will look.
    console.error(`${this.props.region} panel failed`, error, info.componentStack);
    this.props.onError?.(error, info);
  }

  private readonly retry = () => this.setState({ error: null });

  override render(): ReactNode {
    const { error } = this.state;
    if (!error) {
      return this.props.children;
    }
    return (
      <div className="region-error" role="alert">
        <p>
          <strong>{this.props.region}</strong> could not be drawn.
        </p>
        <p className="region-error-detail">{error.message}</p>
        <button type="button" onClick={this.retry}>
          Try again
        </button>
      </div>
    );
  }
}
