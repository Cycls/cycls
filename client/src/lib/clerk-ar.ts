// @clerk/localizations ships ar-SA with the whole `billing` tree undefined —
// 125 of its 135 keys — so a paying Arabic customer read the checkout drawer in
// English. The drawer draws from the top level of `billing` as much as from
// `billing.checkout`, so both are filled in here. Terms follow the pricing cards
// in i18n.ts (باقة, اشتراك, تُدفع سنوياً) so the two pages agree.
//
// Card number / expiry / CVC inside the drawer come from Stripe's own iframe,
// not from here — they stay English until Stripe is given a locale.
import { arSA } from "@clerk/localizations";

export const arCheckout = {
  ...arSA,
  billing: {
    ...arSA.billing,

    free: "مجاني",
    alwaysFree: "مجاني دائماً",
    month: "شهر",
    months: "أشهر",
    monthly: "شهري",
    monthAbbreviation: "شهر",
    year: "سنة",
    years: "سنوات",
    annually: "سنوي",
    yearAbbreviation: "سنة",
    monthPerUnit: "شهرياً لكل {{unitName}}",
    yearPerUnit: "سنوياً لكل {{unitName}}",

    billedMonthly: "تُدفع شهرياً",
    billedAnnually: "تُدفع سنوياً",
    billedMonthlyOnly: "تُدفع شهرياً فقط",
    billedAnnuallyOnly: "تُدفع سنوياً فقط",

    subscribe: "اشتراك",
    reSubscribe: "إعادة الاشتراك",
    getStarted: "ابدأ الآن",
    manage: "إدارة",
    manageSubscription: "إدارة الاشتراك",
    switchPlan: "التبديل إلى هذه الباقة",
    switchToAnnual: "التبديل إلى السنوي",
    switchToMonthly: "التبديل إلى الشهري",
    switchToAnnualWithAnnualPrice: "التبديل إلى السنوي {{price}} / سنة",
    switchToMonthlyWithPrice: "التبديل إلى الشهري {{price}} / شهر",
    defaultFreePlanActive: "أنت على الباقة المجانية حالياً",
    highlightedPlanBadge: "الأكثر شيوعاً",
    availableFeatures: "المزايا المتاحة",
    seeAllFeatures: "عرض كل المزايا",
    viewFeatures: "عرض المزايا",
    viewPayment: "عرض الدفعة",

    startFreeTrial: "ابدأ التجربة المجانية",
    startFreeTrial__days: "ابدأ تجربة مجانية لمدة {{days}} يوم",
    keepFreeTrial: "الإبقاء على التجربة المجانية",
    cancelFreeTrial: "إلغاء التجربة المجانية",
    cancelFreeTrialTitle: "إلغاء التجربة المجانية لباقة {{plan}}؟",
    cancelFreeTrialAccessUntil: "ستبقى تجربتك فعّالة حتى {{ date | longDate('ar-SA') }}. بعد ذلك ستفقد الوصول إلى مزايا التجربة، ولن يتم خصم أي مبلغ منك.",

    keepSubscription: "الإبقاء على الاشتراك",
    cancelSubscription: "إلغاء الاشتراك",
    cancelSubscriptionTitle: "إلغاء اشتراك {{plan}}؟",
    cancelSubscriptionNoCharge: "لن يتم خصم أي مبلغ مقابل هذا الاشتراك.",
    cancelSubscriptionAccessUntil: "يمكنك الاستمرار في استخدام مزايا '{{plan}}' حتى {{ date | longDate('ar-SA') }}، وبعدها لن يكون لديك وصول إليها.",
    cancelSubscriptionPastDue: "سينتهي اشتراكك فوراً وستفقد الوصول إلى كل مزايا الباقة. سيُطلب منك سداد المبلغ المتأخر عند اشتراكك القادم.",
    cannotSubscribeMonthly: "لا يمكنك الاشتراك في هذه الباقة بالدفع الشهري. للاشتراك فيها، اختر الدفع السنوي.",
    cannotSubscribeUnrecoverable: "لا يمكنك الاشتراك في هذه الباقة. اشتراكك الحالي أعلى سعراً منها.",
    pastDue: "متأخر السداد",

    seats: "المقاعد",
    seatsWithLimit: "المقاعد (حتى {{limit}})",
    seatBreakdownSingular: "مقعد واحد بسعر {{rate}}/شهر",
    seatBreakdownPlural: "{{chargeable}} مقعد بسعر {{rate}}/شهر",
    seatBreakdownIncludedSingular: "مقعد واحد بسعر {{rate}}/شهر ({{totalSeats}} إجمالاً - {{included}} مشمولة)",
    seatBreakdownIncludedPlural: "{{chargeable}} مقعد بسعر {{rate}}/شهر ({{totalSeats}} إجمالاً - {{included}} مشمولة)",

    paymentMethods__label: "طرق الدفع",
    addPaymentMethod__label: "إضافة طريقة دفع",
    pay: "ادفع {{amount}}",

    credit: "رصيد",
    accountCredit: "رصيد الحساب",
    prorationCredit: "رصيد تناسبي",
    proratedDiscount: "خصم تناسبي",
    creditRemainder: "رصيد مقابل الفترة المتبقية من اشتراكك الحالي.",
    payerCreditRemainder: "رصيد من رصيد الحساب.",
    discountAmount: "خصم {{amount}}",
    discountDuration: "خصم {{amount}} لأول {{cycles}} {{period}}",
    discountCyclesRemaining: "{{cycles}} {{period}} متبقية",

    subtotal: "المجموع الفرعي",
    subtotalRenewal: "المجموع الفرعي لكل فترة",
    totalDue: "الإجمالي المستحق",
    totalDueToday: "الإجمالي المستحق اليوم",
    totalDuePerPeriod: "الإجمالي لكل فترة",

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
