// Stub posthog-js so hooks that call `track(...)` don't need a live
// instance. The real client is initialized in App.tsx; tests bypass it.
import { vi } from "vitest";

vi.mock("posthog-js", () => ({
  default: {
    init: vi.fn(),
    capture: vi.fn(),
    identify: vi.fn(),
    reset: vi.fn(),
    register: vi.fn(),
    persistence: { props: {} },
  },
}));
