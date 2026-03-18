import { useState, useEffect } from "react";

const translations = {
  en: {
    sendMessage: "Send a message...",
    newChat: "New chat",
    share: "Share",
    shareConversation: "Share conversation",
    anyoneCanView: "Anyone with the link can view.",
    title: "Title",
    untitled: "Untitled",
    createLink: "Create link",
    creatingLink: "Creating share link...",
    manageShares: "Manage shares",
    sessions: "Sessions",
    files: "Files",
    shares: "Shares",
    noShares: "No shared links yet",
    noSharesSub: "Share a conversation to see it here",
    noSessions: "No sessions yet",
    noSessionsSub: "Start a conversation to see it here",
    uploadFile: "Upload file",
    browseFiles: "Browse files",
    darkMode: "Dark mode",
    lightMode: "Light mode",
    account: "Account",
    plans: "Plans",
    manageAccount: "Manage account",
    organization: "Organization",
    personal: "Personal",
    manageOrg: "Manage organization",
    createOrg: "+ Create organization",
    signOut: "Sign out",
    back: "Back",
    monthly: "Monthly",
    annual: "Annual",
    active: "Active",
    managePlan: "Manage plan",
    subscribe: "Subscribe",
    getStarted: "Get started",
    free: "Free",
    orgPlans: "Organization Plans",
    orgPlansFor: "Org plans for",
    personalPlans: "Personal Plans",
    billedAnnually: "billed annually",
    freeTrialDays: "-day free trial",
    perMonth: "/ mo",
    explore: "Explore agents",
    language: "العربية",
    noFiles: "No files yet",
    noFilesSub: "Upload files or create a folder",
    refresh: "Refresh",
    newFolder: "New folder",
    upload: "Upload",
    download: "Download",
    rename: "Rename",
    delete: "Delete",
  },
  ar: {
    sendMessage: "أرسل رسالة...",
    newChat: "محادثة جديدة",
    share: "مشاركة",
    shareConversation: "مشاركة المحادثة",
    anyoneCanView: "أي شخص لديه الرابط يمكنه المشاهدة.",
    title: "العنوان",
    untitled: "بدون عنوان",
    createLink: "إنشاء رابط",
    creatingLink: "جاري إنشاء رابط المشاركة...",
    manageShares: "إدارة المشاركات",
    sessions: "الجلسات",
    files: "الملفات",
    shares: "المشاركات",
    noShares: "لا توجد روابط مشاركة",
    noSharesSub: "شارك محادثة لرؤيتها هنا",
    noSessions: "لا توجد جلسات",
    noSessionsSub: "ابدأ محادثة لرؤيتها هنا",
    uploadFile: "رفع ملف",
    browseFiles: "تصفح الملفات",
    darkMode: "الوضع الداكن",
    lightMode: "الوضع الفاتح",
    account: "الحساب",
    plans: "الباقات",
    manageAccount: "إدارة الحساب",
    organization: "المنظمة",
    personal: "شخصي",
    manageOrg: "إدارة المنظمة",
    createOrg: "+ إنشاء منظمة",
    signOut: "تسجيل الخروج",
    back: "رجوع",
    monthly: "شهري",
    annual: "سنوي",
    active: "فعّال",
    managePlan: "إدارة الباقة",
    subscribe: "اشتراك",
    getStarted: "ابدأ الآن",
    free: "مجاني",
    orgPlans: "باقات المنظمة",
    orgPlansFor: "باقات منظمة",
    personalPlans: "الباقات الشخصية",
    billedAnnually: "تُدفع سنوياً",
    freeTrialDays: " يوم تجربة مجانية",
    perMonth: "/ شهر",
    explore: "استكشف الوكلاء",
    language: "English",
    noFiles: "لا توجد ملفات",
    noFilesSub: "ارفع ملفات أو أنشئ مجلد",
    refresh: "تحديث",
    newFolder: "مجلد جديد",
    upload: "رفع",
    download: "تحميل",
    rename: "إعادة تسمية",
    delete: "حذف",
  },
} as const;

export type Lang = keyof typeof translations;

export function getLang(): Lang {
  return document.documentElement.lang === "ar" ? "ar" : "en";
}

export function setLang(lang: Lang) {
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
  window.dispatchEvent(new Event("langchange"));
}

export function t(key: keyof typeof translations.en): string {
  return translations[getLang()][key];
}

export function useLang(): Lang {
  const [lang, set] = useState(getLang);
  useEffect(() => {
    const handler = () => set(getLang());
    window.addEventListener("langchange", handler);
    return () => window.removeEventListener("langchange", handler);
  }, []);
  return lang;
}
