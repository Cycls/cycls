import { useState } from "react";
import { SignedIn } from "@clerk/clerk-react";
import { usePlans, useSubscription, CheckoutButton, SubscriptionDetailsButton } from "@clerk/clerk-react/experimental";
import { t, getLang } from "../lib/i18n";
import { track } from "../lib/posthog";

function formatPrice(money: { amount: number; currencySymbol: string; currency: string }) {
  const value = money.amount / 100;
  return new Intl.NumberFormat(getLang() === "ar" ? "ar" : "en-US", {
    style: "currency",
    currency: money.currency,
    minimumFractionDigits: value % 1 === 0 ? 0 : 2,
  }).format(value);
}

export function PricingCards({ payerType = "user", onSelect }: { payerType?: "user" | "organization"; onSelect: () => void }) {
  const { data: plansData, isLoading } = usePlans({ for: payerType });
  const { data: sub } = useSubscription({ for: payerType });
  const [period, setPeriod] = useState<"month" | "annual">("month");

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="size-5 border-2 border-muted-foreground/30 border-t-foreground rounded-full animate-spin" />
      </div>
    );
  }

  const plans = plansData?.filter(p => p.publiclyVisible) ?? [];
  const hasAnnual = plans.some(p => p.annualFee);
  const activePlanId = sub?.subscriptionItems?.[0]?.plan?.id;

  return (
    <div>
      {hasAnnual && (
        <div className="flex items-center justify-center gap-1 mb-4 sticky top-0 z-10 bg-background py-1 border-b border-border pb-3">
          <button
            onClick={() => setPeriod("month")}
            className={`px-3 py-1 text-xs rounded-full transition-colors cursor-pointer ${period === "month" ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground"}`}
          >
            {t("monthly")}
          </button>
          <button
            onClick={() => setPeriod("annual")}
            className={`px-3 py-1 text-xs rounded-full transition-colors cursor-pointer ${period === "annual" ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground"}`}
          >
            {t("annual")}
          </button>
        </div>
      )}
      <div className="flex flex-col sm:flex-row gap-3 sm:flex-nowrap">
        {plans.map(plan => {
          const isActive = plan.id === activePlanId;
          const price = period === "annual" && plan.annualMonthlyFee ? plan.annualMonthlyFee : plan.fee;
          const isFreePlan = !plan.hasBaseFee;
          return (
            <div
              key={plan.id}
              className={`relative flex flex-col rounded-xl border p-4 w-full sm:w-[320px] sm:shrink-0 ${isActive ? "border-muted-foreground/50 bg-muted/50" : "border-border"}`}
            >
              <div className="mb-3">
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-semibold text-foreground">{plan.name}</h3>
                  {isActive && <span className="px-1.5 py-0.5 text-[10px] font-medium rounded-full bg-muted text-muted-foreground">{t("active")}</span>}
                </div>
                {plan.description && (
                  <p className="text-xs text-muted-foreground mt-0.5">{plan.description}</p>
                )}
              </div>
              <div className="mb-4 h-12">
                {isFreePlan ? (
                  <span className="text-2xl font-bold text-foreground">{t("free")}</span>
                ) : (
                  <>
                    <div className="flex items-baseline gap-1">
                      <span className="text-2xl font-bold text-foreground">
                        {formatPrice(price)}
                      </span>
                      <span className="text-xs text-muted-foreground">{t("perMonth")}</span>
                    </div>
                    {period === "annual" && plan.annualFee ? (
                      <p className="text-[10px] text-muted-foreground mt-0.5">
                        {formatPrice(plan.annualFee)} {t("billedAnnually")}
                      </p>
                    ) : plan.freeTrialEnabled && plan.freeTrialDays ? (
                      <p className="text-[10px] text-muted-foreground mt-0.5">
                        {plan.freeTrialDays}{t("freeTrialDays")}
                      </p>
                    ) : null}
                  </>
                )}
              </div>
              {plan.features.length > 0 && (
                <ul className="mb-4 space-y-1.5 flex-1">
                  {plan.features.map(f => (
                    <li key={f.id} className="flex items-start gap-2 text-xs text-muted-foreground">
                      <svg className="w-3.5 h-3.5 mt-0.5 shrink-0 text-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                      </svg>
                      {f.name}
                    </li>
                  ))}
                </ul>
              )}
              <div className="mt-auto">
                {isActive ? (
                  <SignedIn>
                    <SubscriptionDetailsButton for={payerType}>
                      <button
                        onClick={() => {
                          track("plan_manage_clicked", {
                            plan_id: plan.id,
                            plan_name: plan.name,
                            payer_type: payerType,
                          });
                          onSelect();
                        }}
                        className="w-full py-1.5 text-xs font-medium rounded-lg border border-border hover:bg-secondary/80 transition-colors cursor-pointer"
                      >
                        {t("managePlan")}
                      </button>
                    </SubscriptionDetailsButton>
                  </SignedIn>
                ) : (
                  <SignedIn>
                    <CheckoutButton
                      planId={plan.id}
                      planPeriod={period}
                      for={payerType}
                      onSubscriptionComplete={() => {
                        track("plan_subscription_completed", {
                          plan_id: plan.id,
                          plan_name: plan.name,
                          plan_period: period,
                          plan_price: price,
                          payer_type: payerType,
                          is_free: isFreePlan,
                        });
                        onSelect();
                      }}
                    >
                      <button
                        onClick={() => {
                          track("plan_checkout_clicked", {
                            plan_id: plan.id,
                            plan_name: plan.name,
                            plan_period: period,
                            plan_price: price,
                            payer_type: payerType,
                            is_free: isFreePlan,
                          });
                          onSelect();
                        }}
                        className="w-full py-1.5 text-xs font-medium rounded-lg border border-border hover:bg-secondary/80 transition-colors cursor-pointer"
                      >
                        {isFreePlan ? t("getStarted") : t("subscribe")}
                      </button>
                    </CheckoutButton>
                  </SignedIn>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
