// Commerce props for checkout_start and purchase, GA4-shaped. Clerk money is
// in minor units; value is what the chosen period actually charges, not the
// monthly equivalent the card displays.
type Money = { amount: number; currency: string } | null | undefined;
export type PlanLike = { id: string; name: string; fee: Money; annualFee?: Money; hasBaseFee: boolean };

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
