// Commerce props for checkout_start and purchase, GA4-shaped. Clerk money is
// in minor units; value is what the chosen period actually charges, not the
// monthly equivalent the card displays.
type Money = { amount: number; currency: string } | null | undefined;
export type PlanLike = { id: string; name: string; fee: Money; annualFee?: Money; hasBaseFee: boolean };

// On a free plan: billing knows the payer, and none of its live items is a plan with a fee (a canceled one runs
// to its period's end still active, so it still counts as paid).
type Sub = { subscriptionItems?: { status?: string; plan?: { hasBaseFee?: boolean } | null }[] } | null | undefined;
export const onFreePlan = (sub: Sub) =>
  !!sub && !sub.subscriptionItems?.some((i) => i.plan?.hasBaseFee && (i.status === "active" || i.status === "past_due"));

export function commerceProps(plan: PlanLike, period: "month" | "annual", payerType: string, previousPlan?: string | null) {
  const charged = period === "annual" && plan.annualFee ? plan.annualFee : plan.fee;
  return {
    plan_id: plan.id,
    plan_name: plan.name,
    billing_period: period,
    value: charged ? charged.amount / 100 : 0,
    currency: charged?.currency || "USD",
    payer_type: payerType,
    is_free: !plan.hasBaseFee,
    ...(previousPlan && previousPlan !== plan.name ? { previous_plan: previousPlan } : {}),
  };
}
