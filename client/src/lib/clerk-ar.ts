// @clerk/localizations ships ar-SA with the whole `billing` tree undefined —
// 125 of its 135 keys — so the checkout drawer falls back to English. These are
// the checkout strings a paying customer actually reads; the terms match the
// pricing cards in i18n.ts (باقة, اشتراك, تُدفع سنوياً) so the two agree.
import { arSA } from "@clerk/localizations";

export const arCheckout = {
  ...arSA,
  billing: {
    ...arSA.billing,
    checkout: {
      title: "إتمام الشراء",
      addPromoCode: "إضافة رمز خصم",
      applyPromoCode: "تطبيق",
      promoCodePlaceholder: "أدخل رمز الخصم",
      removePromoCode: "إزالة رمز الخصم",
      discount: "الخصم",
      perMonth: "شهرياً",
      totalDuePerPeriod: "الإجمالي المستحق لكل فترة",
      totalDueAfterTrial: "الإجمالي المستحق بعد انتهاء التجربة خلال {{days}} يوم",
      title__paymentSuccessful: "تم الدفع بنجاح!",
      description__paymentSuccessful: "تمت عملية الدفع بنجاح.",
      title__subscriptionSuccessful: "تم بنجاح!",
      description__subscriptionSuccessful: "اشتراكك الجديد جاهز.",
      title__trialSuccess: "بدأت التجربة المجانية بنجاح!",
      downgradeNotice: "ستحتفظ باشتراكك الحالي ومزاياه حتى نهاية دورة الفوترة، ثم يتم تحويلك إلى هذا الاشتراك.",
      pastDueNotice: "اشتراكك السابق كان متأخر السداد، دون أي دفعة.",
      emailForm: {
        title: "إضافة بريد إلكتروني",
        subtitle: "قبل إتمام الشراء، يجب إضافة بريد إلكتروني لإرسال الإيصالات إليه.",
      },
      lineItems: {
        title__paymentMethod: "طريقة الدفع",
        title__subscriptionBegins: "يبدأ الاشتراك في",
        title__freeTrialEndsAt: "تنتهي التجربة في",
        title__statementId: "رقم كشف الحساب",
        title__totalPaid: "الإجمالي المدفوع",
      },
    },
  },
};
