# Porting the React Client to Expo

## Overview

The React web client is well-structured for sharing a common base with an Expo (React Native) app. Roughly 50% of the codebase can be shared as-is, with platform-specific implementations for rendering and auth.

## What Shares Directly

- **`use-chat.ts` hook** — Pure React + fetch, zero DOM APIs. Works as-is in React Native.
- **Types** — `Part`, `Message`, `AppConfig`, `PlanInfo`, `UserInfo`.
- **Component prop contracts** — `Chat`, `MessageBubble`, and all part components have clean interfaces.
- **Message parsing logic** — The SSE stream parser in `send()`.

## Recommended Monorepo Structure

```
packages/
  shared/               # shared package (pure React, no react-dom or react-native)
    hooks/
      use-chat.ts           # as-is
    types.ts                # Part, Message, AppConfig, etc.
  web/                  # current client, imports from shared
    components/
      chat.tsx              # web-specific (HTML elements, Tailwind)
      parts/                # ReactMarkdown, Shiki, KaTeX
  expo/                 # new app, imports from shared
    components/
      chat.tsx              # RN-specific (View, Text, NativeWind)
      parts/                # react-native-markdown, syntax highlighter
```

Use npm/pnpm workspaces or turborepo. The `shared` package depends only on `react`.

## Platform-Specific Implementations

Each platform implements the same component interfaces with different primitives:

| Shared Contract | Web | Expo |
|---|---|---|
| `TextPart({ text })` | ReactMarkdown + KaTeX | react-native-markdown-display |
| `CodeBlockCode({ code, lang })` | Shiki + dangerouslySetInnerHTML | react-native-syntax-highlighter |
| `Chat({ messages, ... })` | `<div>` + `<textarea>` | `<View>` + `<TextInput>` |
| Dark mode hook | `document.body.classList` | `Appearance.getColorScheme()` |
| Auth | `@clerk/clerk-react` | `@clerk/clerk-expo` |
| Auto-scroll | `use-stick-to-bottom` | `FlatList` + `onContentSizeChange` |
| Animations | `framer-motion` | `react-native-reanimated` |
| Clipboard | `navigator.clipboard` | `expo-clipboard` |
| SVG icons | Inline `<svg>` | `react-native-svg` |

## Key Porting Notes

### Styling
All web styling uses Tailwind classes. For Expo, use NativeWind v4 (supports most of the current usage) or rewrite to `StyleSheet`. NativeWind is the lower-friction option.

### Code Highlighting
`codeToHtml` + `dangerouslySetInnerHTML` won't work in RN. Replace with `react-native-syntax-highlighter` or render in a WebView.

### Markdown Rendering
`react-markdown` renders HTML elements. Use `react-native-markdown-display` or similar. Custom renderers for code blocks, tables, and math will need reimplementation.

### KaTeX / Math
No native KaTeX in RN. Use `react-native-math-view` or render math blocks in a WebView.

### Clerk Auth
`@clerk/clerk-expo` provides equivalent hooks (`useAuth`, `useUser`, etc.), but the OAuth redirect flow differs (uses `expo-auth-session` or `expo-web-browser`). The `PricingTable` component likely won't work natively — consider a WebView or custom implementation.

### DOM APIs to Replace
- `document.body.classList` (dark mode) -> `Appearance.getColorScheme()`
- `navigator.clipboard` -> `expo-clipboard`
- `window.matchMedia("(pointer: coarse)")` -> not needed (always touch on mobile)
- `h-dvh`, fixed positioning -> `SafeAreaView` + flex layout

## Steps to Start

1. Extract `use-chat.ts` and types into `packages/shared`
2. Move current `client/` to `packages/web`
3. Create `packages/expo` with `npx create-expo-app`
4. Import shared hook, implement platform-specific components

The hook is the hard part and it's already done. The part components are small enough that maintaining two implementations (web HTML vs. RN Views) is more practical than trying to abstract over both with a universal renderer.
