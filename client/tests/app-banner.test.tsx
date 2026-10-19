// Phone visitors are pointed to the app the browser's own way first (Safari's banner, Chrome's
// install sheet); the bar is the fallback, once per page load, resting two weeks once answered.
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";

const track = vi.hoisted(() => vi.fn());
vi.mock("../src/lib/analytics", () => ({ track }));

import { AppBanner, platform } from "../src/components/app-banner";

const SAFARI = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1";
const IOS_CHROME = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/129.0.6668.69 Mobile/15E148 Safari/604.1";
const ANDROID = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Mobile Safari/537.36";
const MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15";
const IOS = "https://apps.apple.com/app/cycls/id6802279454";
const PLAY = "https://play.google.com/store/apps/details?id=com.cycls.app";

function on(ua: string, mobile_app: Record<string, string> | null = { ios: IOS, android: PLAY }) {
  Object.defineProperty(navigator, "userAgent", { value: ua, configurable: true });
  (window as { __CONFIG__?: unknown }).__CONFIG__ = { mobile_app };
}

beforeEach(() => { localStorage.clear(); track.mockClear(); });
afterEach(cleanup);

describe("app banner", () => {
  test("Chrome on an iPhone gets the App Store link, reported once however many pages mount it", () => {
    on(IOS_CHROME);
    render(<><AppBanner /><AppBanner /></>);
    const [open] = screen.getAllByRole("link", { name: "Open" });
    expect(open.getAttribute("href")).toBe(IOS);
    expect(track.mock.calls).toEqual([["app_banner_shown", { platform: "ios" }]]);
  });

  test("Safari draws Apple's own banner, so the bar stays out of its way", () => {
    on(SAFARI);
    render(<AppBanner />);
    expect(screen.queryByTestId("app-banner")).toBeNull();
    expect(track).not.toHaveBeenCalled();
  });

  test("nothing on a desktop, nor on a phone whose store the agent didn't give", () => {
    on(MAC);
    render(<AppBanner />);
    on(ANDROID, { ios: IOS });
    render(<AppBanner />);
    on(IOS_CHROME, null);
    render(<AppBanner />);
    expect(screen.queryByTestId("app-banner")).toBeNull();
  });

  test("dismissed, it stays away for two weeks, then comes back", () => {
    on(ANDROID);
    const first = render(<AppBanner />);
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(track).toHaveBeenLastCalledWith("app_banner_dismissed", { platform: "android" });
    expect(screen.queryByTestId("app-banner")).toBeNull();
    first.unmount();

    render(<AppBanner />);
    expect(screen.queryByTestId("app-banner")).toBeNull();
    localStorage.setItem("cycls_app_banner", String(Date.now() - 15 * 864e5));
    render(<AppBanner />);
    expect(screen.getByTestId("app-banner")).toBeTruthy();
  });

  test("without Chrome's sheet, Open leaves for the store and rests the bar the same way", () => {
    on(IOS_CHROME);
    render(<AppBanner />);
    fireEvent.click(screen.getByRole("link", { name: "Open" }));
    expect(track).toHaveBeenLastCalledWith("app_banner_clicked", { platform: "ios", via: "store" });
    expect(screen.queryByTestId("app-banner")).toBeNull();
  });

  test("on Android Chrome, Open brings up Google's install sheet, once", () => {
    on(ANDROID);
    const prompt = vi.fn(async () => {});
    const offer = Object.assign(new Event("beforeinstallprompt", { cancelable: true }), { prompt });
    window.dispatchEvent(offer);
    expect(offer.defaultPrevented).toBe(true);
    render(<AppBanner />);
    const open = screen.getByRole("link", { name: "Open" });
    expect(fireEvent.click(open)).toBe(false);                       // the store link is not followed
    expect(prompt).toHaveBeenCalledOnce();
    expect(track).toHaveBeenLastCalledWith("app_banner_clicked", { platform: "android", via: "prompt" });

    localStorage.clear();
    render(<AppBanner />);
    expect(fireEvent.click(screen.getByRole("link", { name: "Open" }))).toBe(true);   // the sheet was spent: the store
    expect(prompt).toHaveBeenCalledOnce();
  });

  test("an iPad asking for the desktop site is still iOS; a Mac is not", () => {
    expect(platform(MAC, 5)).toBe("ios");
    expect(platform(MAC, 0)).toBeNull();
  });
});
