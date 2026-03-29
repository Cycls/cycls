const ICONS = {
  summary: (
    <svg className="size-4" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
    </svg>
  ),
  code: (
    <svg className="size-4" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d="M17.25 6.75 22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3-4.5 16.5" />
    </svg>
  ),
  research: (
    <svg className="size-4" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z" />
    </svg>
  ),
  creative: (
    <svg className="size-4" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d="M9.53 16.122a3 3 0 0 0-5.78 1.128 2.25 2.25 0 0 1-2.4 2.245 4.5 4.5 0 0 0 8.4-2.245c0-.399-.078-.78-.22-1.128Zm0 0a15.998 15.998 0 0 0 3.388-1.62m-5.043-.025a15.994 15.994 0 0 1 1.622-3.395m3.42 3.42a15.995 15.995 0 0 0 4.764-4.648l3.876-5.814a1.151 1.151 0 0 0-1.597-1.597L14.146 6.32a15.996 15.996 0 0 0-4.649 4.763m3.42 3.42a6.776 6.776 0 0 0-3.42-3.42" />
    </svg>
  ),
  analyze: (
    <svg className="size-4" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 3v11.25A2.25 2.25 0 0 0 6 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0 1 18 16.5h-2.25m-7.5 0h7.5m-7.5 0-1 3m8.5-3 1 3m0 0 .5 1.5m-.5-1.5h-9.5m0 0-.5 1.5m.75-9 3-3 2.148 2.148A12.061 12.061 0 0 1 16.5 7.605" />
    </svg>
  ),
};

export interface SuggestionCategory {
  label: string;
  highlight: string;
  icon: React.ReactNode;
  items: string[];
}

export const SUGGESTIONS: Record<string, SuggestionCategory[]> = {
  en: [
    { label: "Summary", highlight: "Summarize", icon: ICONS.summary, items: [
      "Summarize this article into 3 key points",
      "Summarize the main arguments of this text",
      "Summarize this meeting transcript into action items",
      "Summarize this document in one paragraph",
    ]},
    { label: "Code", highlight: "Write", icon: ICONS.code, items: [
      "Write a Python function that sorts a list",
      "Write a regex to validate email addresses",
      "Write a REST API endpoint in FastAPI",
      "Write unit tests for this function",
    ]},
    { label: "Research", highlight: "Research", icon: ICONS.research, items: [
      "Research the pros and cons of microservices vs monoliths",
      "Research best practices for API authentication",
      "Research the latest trends in AI agents",
      "Research how to optimize database queries",
    ]},
    { label: "Creative", highlight: "Create", icon: ICONS.creative, items: [
      "Create a catchy tagline for a tech startup",
      "Create an outline for a blog post about AI",
      "Create a product description for an app",
      "Create a story prompt for a sci-fi setting",
    ]},
    { label: "Analyze", highlight: "Analyze", icon: ICONS.analyze, items: [
      "Analyze this data and identify key trends",
      "Analyze the performance bottlenecks in this code",
      "Analyze the sentiment of these customer reviews",
      "Analyze this business model and find weaknesses",
    ]},
  ],
  ar: [
    { label: "تلخيص", highlight: "لخّص", icon: ICONS.summary, items: [
      "لخّص هذا المقال في 3 نقاط رئيسية",
      "لخّص الحجج الأساسية في هذا النص",
      "لخّص محضر هذا الاجتماع إلى مهام",
      "لخّص هذا المستند في فقرة واحدة",
    ]},
    { label: "برمجة", highlight: "اكتب", icon: ICONS.code, items: [
      "اكتب دالة بايثون لترتيب قائمة",
      "اكتب تعبير منتظم للتحقق من البريد الإلكتروني",
      "اكتب نقطة نهاية REST API باستخدام FastAPI",
      "اكتب اختبارات وحدة لهذه الدالة",
    ]},
    { label: "بحث", highlight: "ابحث", icon: ICONS.research, items: [
      "ابحث عن إيجابيات وسلبيات الخدمات المصغرة مقابل المتراصة",
      "ابحث عن أفضل ممارسات مصادقة الـ API",
      "ابحث عن أحدث التوجهات في وكلاء الذكاء الاصطناعي",
      "ابحث عن طرق تحسين استعلامات قواعد البيانات",
    ]},
    { label: "إبداع", highlight: "أنشئ", icon: ICONS.creative, items: [
      "أنشئ شعارًا جذابًا لشركة تقنية ناشئة",
      "أنشئ مخططًا لمقال عن الذكاء الاصطناعي",
      "أنشئ وصفًا لمنتج تطبيق",
      "أنشئ فكرة قصة في عالم خيال علمي",
    ]},
    { label: "تحليل", highlight: "حلّل", icon: ICONS.analyze, items: [
      "حلّل هذه البيانات وحدد الاتجاهات الرئيسية",
      "حلّل اختناقات الأداء في هذا الكود",
      "حلّل مشاعر تقييمات العملاء هذه",
      "حلّل نموذج العمل هذا وابحث عن نقاط الضعف",
    ]},
  ],
};
