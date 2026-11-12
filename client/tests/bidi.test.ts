/**
 * Mixed Arabic and English reads the way most of its words go, as on the mobile app (src/lib/bidi.ts).
 */
import { test, expect } from "vitest";
import { dirOf, blockDir } from "../src/lib/bidi";

test("Arabic leads once a third of the words are Arabic, whatever comes first", () => {
  expect(dirOf("Python هي لغة برمجة سهلة")).toBe("rtl");
  expect(dirOf("استخدم Gmail لإرسال الرسالة")).toBe("rtl");
  expect(dirOf("Cycls سايكلز")).toBe("rtl");
  expect(dirOf("Press the زر button to continue")).toBe("ltr");
  expect(dirOf("مرحبا")).toBe("rtl");
  expect(dirOf("hello")).toBe("ltr");
  expect(dirOf("")).toBe("ltr");
});

test("code, math, links, paths and file names don't vote", () => {
  expect(dirOf("افتح https://example.com/a/very/long/path/to/somewhere")).toBe("rtl");
  expect(dirOf("عدّل src/components/message-list.tsx الآن")).toBe("rtl");
  expect(dirOf("شغّل `npm run build --production now` أولا")).toBe("rtl");
  expect(dirOf("راجع report-final-version.pdf")).toBe("rtl");
  expect(dirOf("هذا مثال:\n```python\nfor item in items:\n    print(item.name, item.value)\n```")).toBe("rtl");
  expect(dirOf("المعادلة $$x + y = z + w + v$$ صحيحة")).toBe("rtl");
  expect(dirOf("https://example.com")).toBe("ltr");
});

test("a block in one script reads its own way; a mixed one inherits its message's", () => {
  expect(blockDir("مرحبا بك")).toBe("rtl");
  expect(blockDir("Tinker notes")).toBe("ltr");
  expect(blockDir("Python هي لغة")).toBeUndefined();
  expect(blockDir("2027 — 42%")).toBeUndefined();
});
