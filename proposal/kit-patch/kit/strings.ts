// The kit's own words, in both languages. Apps keep theirs in their own dictionary, but
// REUSE these for the shared concepts (glossary, docs/critique/arabic-rtl.md § 5):
// loadExample / loadedExample, fictional, prompt (= «التعليمة», never «الطلب», which is the
// business object in requests/forms/bids), unreadable*, verifiedOn / toVerify, addedByUser.
import { useT, translate, type Dicts, type Lang } from "./i18n";

export const KIT_STRINGS = {
  en: {
    close: "Close", cancel: "Cancel", loading: "Loading…", language: "Language", theme: "Theme",
    light: "Light", dark: "Dark", switchToAr: "العربية", switchToEn: "English",
    demoBanner: "Example — sample data, changes are not saved",
    demoNoShim: "Opened outside Cycls",
    demoGallery: "Shared preview",
    demoNoAnswer: "Data is not available in this app on this device",
    demoToast: "Example only — this change is not saved",
    crashTitle: "Something went wrong", crashBody: "The app hit an error and stopped. Your saved data is safe.", reload: "Reload",
    search: "Search", noResults: "Nothing matches", sortAsc: "sorted ascending", sortDesc: "sorted descending",
    today: "Today", clear: "Clear", pickDate: "Pick a date", businessDaysFromToday: "Business days from today",
    prevMonth: "Previous month", nextMonth: "Next month", weekend: "Weekend", holiday: "Holiday",
    copied: "Copied", copyFailed: "Copy it by hand: select the text", tryPrompt: "Try this prompt", copyPrompt: "Copy prompt",
    askedAgent: "Prompt placed in the chat — press send", examples: "Examples", all: "All", result: "Result", prompt: "Prompt",
    dragHint: "Press Space to pick a card up, the arrow keys to move it, Space again to drop it, or Escape to cancel.",
    picked: "Picked up card {item}.", movedOver: "Card {item} is over column {column}.", dropped: "Card {item} dropped in column {column}.", cancelled: "Move cancelled.",
    estimated: "estimated",
    // shared concepts: one word per concept in every app
    loadExample: "Add example data", loadedExample: "Example data added",
    fictional: "Fictional", fictionalNote: "Fictional data, for illustration",
    notifications: "Notifications", toggleSidebar: "Show or hide the sidebar", commandPalette: "Command palette",
    unreadableValue: "Unreadable value", unreadableHint: "Stored as {raw} — the app could not read it. Edit it, or ask the agent to fix the row.",
    unreadableRows: { one: "{count} row could not be read", other: "{count} rows could not be read" },
    verifiedOn: "Verified on {date}", toVerify: "To verify", addedByUser: "Added by a user", addedByAgent: "Added by {agent}",
    whatAgentDid: "What the agent did", sources: "Sources",
  },
  ar: {
    close: "إغلاق", cancel: "إلغاء", loading: "جارٍ التحميل…", language: "اللغة", theme: "المظهر",
    light: "فاتح", dark: "داكن", switchToAr: "العربية", switchToEn: "English",
    demoBanner: "مثال — بيانات تجريبية، والتعديلات لا تُحفظ",
    demoNoShim: "مفتوح خارج Cycls",
    demoGallery: "معاينة مشتركة",
    demoNoAnswer: "البيانات غير متاحة في هذا التطبيق على هذا الجهاز",
    demoToast: "مثال فقط — لن يُحفظ هذا التعديل",
    crashTitle: "حدث خطأ", crashBody: "توقف التطبيق بسبب خطأ. بياناتك المحفوظة سليمة.", reload: "إعادة التحميل",
    search: "بحث", noResults: "لا توجد نتائج مطابقة", sortAsc: "مرتّب تصاعديًا", sortDesc: "مرتّب تنازليًا",
    today: "اليوم", clear: "مسح", pickDate: "اختر تاريخًا", businessDaysFromToday: "أيام عمل من اليوم",
    prevMonth: "الشهر السابق", nextMonth: "الشهر التالي", weekend: "عطلة نهاية الأسبوع", holiday: "إجازة رسمية",
    copied: "تم النسخ", copyFailed: "انسخ النص يدويًا بتحديده", tryPrompt: "جرّب هذه التعليمة", copyPrompt: "نسخ التعليمة",
    askedAgent: "وُضعت التعليمة في المحادثة — اضغط إرسال", examples: "أمثلة", all: "الكل", result: "النتيجة", prompt: "التعليمة",
    dragHint: "اضغط مفتاح المسافة لالتقاط البطاقة، ثم الأسهم لتحريكها، ثم المسافة لإفلاتها، أو Esc للإلغاء.",
    picked: "التُقطت البطاقة {item}.", movedOver: "البطاقة {item} فوق عمود {column}.", dropped: "أُفلتت البطاقة {item} في عمود {column}.", cancelled: "أُلغي النقل.",
    estimated: "تقديري",
    loadExample: "إضافة بيانات تجريبية", loadedExample: "أُضيفت البيانات التجريبية",
    fictional: "افتراضية", fictionalNote: "بيانات افتراضية للتوضيح",
    notifications: "الإشعارات", toggleSidebar: "إظهار الشريط الجانبي أو إخفاؤه", commandPalette: "لوحة الأوامر",
    unreadableValue: "قيمة غير مقروءة", unreadableHint: "القيمة المحفوظة {raw} — تعذّرت قراءتها. عدّلها، أو اطلب من الوكيل تصحيح الصف.",
    unreadableRows: { zero: "تعذّرت قراءة {count} صف", one: "تعذّرت قراءة صف واحد", two: "تعذّرت قراءة صفّين", few: "تعذّرت قراءة {count} صفوف", many: "تعذّرت قراءة {count} صفًّا", other: "تعذّرت قراءة {count} صف" },
    verifiedOn: "تاريخ التحقق: {date}", toVerify: "بحاجة إلى تحقق", addedByUser: "أضافه مستخدم", addedByAgent: "أضافه {agent}",
    whatAgentDid: "ما الذي فعله الوكيل", sources: "المصادر",
  },
} satisfies Dicts<string>;

export type KitKey = keyof typeof KIT_STRINGS.en;
export function useKitT() { return useT(KIT_STRINGS as Dicts<KitKey>); }

/** A kit word outside React context (shadcn ui/ files, error screens): the language is read
 *  from <html lang>, which the kit sets before the first paint. */
export function kitWord(key: KitKey, vars?: Record<string, string | number>, lang?: Lang): string {
  const l: Lang = lang ?? (typeof document !== "undefined" && document.documentElement.lang === "ar" ? "ar" : "en");
  return translate(KIT_STRINGS as Dicts<KitKey>, l, key, vars);
}
