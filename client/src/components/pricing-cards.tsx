import { useState } from "react";
import { Show, useUser } from "@clerk/react";
import { usePlans, useSubscription, CheckoutButton, SubscriptionDetailsButton } from "@clerk/react/experimental";
import { t, getLang } from "../lib/i18n";
import { track } from "../lib/analytics";
import { convertReferral } from "../lib/affiliate";
import { commerceProps } from "../lib/commerce";
import { cn } from "../lib/utils";
import { Icon } from "./icon";
import type { AppConfig, Part } from "../hooks/use-chat";
import applePay from "../assets/pay/apple-pay.svg";
import googlePay from "../assets/pay/google-pay.svg";
import visa from "../assets/pay/visa.svg";
import mastercard from "../assets/pay/mastercard.svg";

type Money = { amount: number; currency: string } | null | undefined;
type Setup = NonNullable<AppConfig["plans"]>;

// Each brand's own artwork, unaltered. Apple's and Google's marks carry their frame; a card brand sits in one of
// the same height, so no mark is smaller than another.
const MARKS: Record<string, { src: string; alt: string; framed?: boolean }> = {
  apple_pay: { src: applePay, alt: "Apple Pay", framed: true },
  google_pay: { src: googlePay, alt: "Google Pay", framed: true },
  visa: { src: visa, alt: "Visa" },
  mastercard: { src: mastercard, alt: "Mastercard" },
};

const money = (amount: number, currency: string, whole = false) =>
  new Intl.NumberFormat(getLang() === "ar" ? "ar" : "en-US", {
    style: "currency", currency, currencyDisplay: "narrowSymbol",
    minimumFractionDigits: whole || amount % 1 === 0 ? 0 : 2, maximumFractionDigits: whole ? 0 : 2,
  }).format(amount);
const price = (m: Money) => (m ? money(m.amount / 100, m.currency) : "");
// About the same in the deployment's local currency, at its fixed rate; checkout still charges the plan's own.
const local = (m: Money, setup?: Setup | null) =>
  (m && setup?.currency ? money((m.amount / 100) * setup.currency[1], setup.currency[0], true) : "");

const GO = "flex min-h-[52px] w-full cursor-pointer items-center justify-center rounded-2xl bg-foreground px-5 text-base font-semibold text-background transition hover:opacity-90";

// The plans window: why it opened, one button, how to pay, then the choice of plan and what it includes. Opened by
// an agent's limit it thanks the person first; the plan on offer is already chosen, so the button can lead.
export function PricingCards({ payerType = "user", why, usage, agent, setup, onSelect, onLater }: {
  payerType?: "user" | "organization";
  why?: string;              // "limit": the agent's limit opened it
  usage?: Part | null;       // that limit, for the thank-you
  agent?: string;
  setup?: Setup | null;      // Web.plans: the ways to pay, a local currency, plan words in other languages
  onSelect: () => void;      // checkout or a plan's details opened: the window steps aside
  onLater?: () => void;      // "Not now"
}) {
  const { data: plansData, isLoading } = usePlans({ for: payerType });
  const { data: sub } = useSubscription({ for: payerType });
  const { user } = useUser();
  const [period, setPeriod] = useState<"month" | "annual">("month");
  const [picked, setPicked] = useState<string | null>(null);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="size-5 border-2 border-muted-foreground/30 border-t-foreground rounded-full animate-spin" />
      </div>
    );
  }

  const plans = plansData?.filter((p) => p.publiclyVisible) ?? [];
  const activePlanId = sub?.subscriptionItems?.[0]?.plan?.id;
  const previousPlan = sub?.subscriptionItems?.[0]?.plan?.name ?? null;
  const offer = plans.find((p) => p.hasBaseFee && p.id !== activePlanId) ?? plans[0];   // the first paid plan they don't have
  const plan = plans.find((p) => p.id === picked) ?? offer;
  if (!plan) return null;

  const lang = getLang();
  const say = (slug: string | undefined, key: "name" | "description", own: string) =>
    (slug && setup?.words?.[slug]?.[lang]?.[key]) || own;
  const name = (p: typeof plan) => say(p.slug, "name", p.name);
  const yearly = period === "annual" && !!plan.annualFee;
  const charged = yearly ? plan.annualFee : plan.fee;
  const save = plan.fee?.amount && plan.annualMonthlyFee ? Math.round((1 - plan.annualMonthlyFee.amount / plan.fee.amount) * 100) : 0;
  const limited = why === "limit";
  const per = usage?.per === "month" ? t("usageThisMonth") : usage?.per === "quarter" ? t("usageThisQuarter") : t("usageYour");
  const fine = plan.hasBaseFee ? [
    name(plan),
    plan.freeTrialEnabled && plan.freeTrialDays ? `${plan.freeTrialDays}${t("freeTrialDays")}` : "",
    t(yearly ? "plansAYear" : "plansAMonth").replace("{price}", price(charged)),
    local(charged, setup) && t("plansAbout").replace("{price}", local(charged, setup)),
    t("cancelAnytime"),
  ].filter(Boolean).join(" · ") : "";

  return (
    <div className="grid gap-4">
      <div className="grid gap-1.5">
        <h2 dir="auto" className="text-[22px] font-bold leading-tight text-foreground">
          {limited ? (agent ? t("usageThanks").replace("{agent}", agent) : t("usageThanksPlain")) : t("plansChoose")}
        </h2>
        <p dir="auto" className="text-sm leading-relaxed text-muted-foreground">
          {limited && usage?.limit
            ? t("usageUsedUp").replace("{period}", per).replace("{limit}", String(usage.limit))
            : say(plan.slug, "description", plan.description || "")}
        </p>
      </div>

      <div className="grid gap-2.5">
        <Show when="signed-in">
          {plan.id === activePlanId ? (
            <SubscriptionDetailsButton for={payerType}>
              <button
                onClick={() => {
                  track("plan_manage_clicked", { plan_id: plan.id, plan_name: plan.name, payer_type: payerType });
                  onSelect();
                }}
                className={GO}
              >
                {t("managePlan")}
              </button>
            </SubscriptionDetailsButton>
          ) : (
            <CheckoutButton
              planId={plan.id}
              planPeriod={period}
              for={payerType}
              onSubscriptionComplete={() => {
                // A paid checkout is a purchase; a free plan is not revenue. transaction_id dedupes a double-fired callback.
                if (plan.hasBaseFee) track("purchase", {
                  ...commerceProps(plan, period, payerType, previousPlan),
                  transaction_id: `${user?.id || "anon"}-${plan.id}-${period}-${new Date().toISOString().slice(0, 10)}`,
                });
                // Affiliate referral attribution, paid plans only. The email must match the Stripe customer (Clerk uses
                // the user's primary email). No-op if affiliate isn't enabled.
                const email = user?.primaryEmailAddress?.emailAddress;
                if (plan.hasBaseFee && email) convertReferral(email);
                onSelect();
              }}
            >
              <button
                onClick={() => {
                  track("checkout_start", { ...commerceProps(plan, period, payerType, previousPlan), why: why || "menu" });
                  onSelect();
                }}
                className={GO}
              >
                {!plan.hasBaseFee ? t("getStarted") : limited ? t("subscribeKeepGoing") : t("subscribeTo").replace("{plan}", name(plan))}
              </button>
            </CheckoutButton>
          )}
        </Show>
        {fine && <p dir="auto" className="text-center text-[12.5px] text-muted-foreground">{fine}</p>}
      </div>

      {plan.hasBaseFee && !!setup?.pay?.length && (
        <div className="flex flex-wrap items-center justify-center gap-2">
          {setup.pay.map((k) => {
            const m = MARKS[k];
            if (!m) return null;
            return m.framed
              ? <img key={k} src={m.src} alt={m.alt} className="h-[26px] w-auto" />
              : <span key={k} className="flex h-[26px] items-center rounded-[5px] border border-[#d0d0d5] bg-white px-1"><img src={m.src} alt={m.alt} className="h-[22px] w-auto" /></span>;
          })}
          <span className="flex w-full items-center justify-center gap-1 text-xs text-muted-foreground">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" className="size-3" aria-hidden>
              <rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" />
            </svg>
            {t("securePayment")}
          </span>
        </div>
      )}

      {(plans.length > 1 || plans.some((p) => p.annualFee)) && (
        <div className="grid gap-2.5 border-t border-border pt-4">
          {plans.some((p) => p.annualFee) && (
            <div className="flex w-fit gap-0.5 rounded-full bg-secondary p-1">
              {(["month", "annual"] as const).map((p) => (
                <button
                  key={p}
                  onClick={() => setPeriod(p)}
                  aria-pressed={period === p}
                  className={cn("flex cursor-pointer items-center gap-1.5 rounded-full px-3.5 py-1.5 text-[13px] font-medium transition-colors",
                                period === p ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}
                >
                  {t(p === "month" ? "monthly" : "annual")}
                  {p === "annual" && save > 0 && (
                    <span className="rounded-full bg-emerald-500/10 px-1.5 py-0.5 text-[11px] font-semibold text-emerald-700 dark:text-emerald-400">
                      {t("plansSave").replace("{n}", String(save))}
                    </span>
                  )}
                </button>
              ))}
            </div>
          )}
          {plans.length > 1 && (
            <div role="radiogroup" className="grid gap-2">
              {plans.map((p) => {
                const on = p.id === plan.id;
                const each = period === "annual" && p.annualMonthlyFee ? p.annualMonthlyFee : p.fee;
                return (
                  <button
                    key={p.id}
                    role="radio"
                    aria-checked={on}
                    onClick={() => setPicked(p.id)}
                    className={cn("grid cursor-pointer grid-cols-[auto_1fr_auto] items-center gap-3 rounded-2xl border px-4 py-3 text-start transition-colors",
                                  on ? "border-foreground ring-1 ring-foreground" : "border-border hover:bg-secondary/50")}
                  >
                    <span className={cn("size-4 rounded-full border", on ? "border-[5px] border-foreground" : "border-muted-foreground/40")} />
                    <span className="flex flex-wrap items-center gap-2 text-[15px] font-semibold text-foreground">
                      {name(p)}
                      {p.id === offer.id && p.id !== activePlanId && (
                        <span className="rounded-full bg-foreground px-2 py-0.5 text-[11px] font-semibold text-background">{t("plansRecommended")}</span>
                      )}
                      {p.id === activePlanId && (
                        <span className="rounded-full bg-secondary px-2 py-0.5 text-[11px] font-medium text-muted-foreground">{t("active")}</span>
                      )}
                    </span>
                    <span className="text-end tabular-nums">
                      <span className="text-[15px] font-semibold text-foreground">{p.hasBaseFee ? price(each) : t("free")}</span>
                      {p.hasBaseFee && <span className="text-xs text-muted-foreground"> {t("perMonth")}</span>}
                      {p.hasBaseFee && local(each, setup) && (
                        <span className="block text-xs text-muted-foreground">{t("plansAbout").replace("{price}", local(each, setup))}</span>
                      )}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}

      {plan.features.length > 0 && (
        <div className="grid gap-2">
          <p className="text-[13px] font-semibold text-foreground">{t("plansYouGet")}</p>
          <ul className="grid gap-1.5">
            {plan.features.map((f) => (
              <li key={f.id} className="flex items-start gap-2 text-[13.5px] text-foreground/90">
                <Icon name="check" className="mt-0.5 size-3.5 shrink-0 text-emerald-600 dark:text-emerald-400" />
                <span dir="auto">{say(f.slug, "name", f.name)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {onLater && (
        <button onClick={onLater} className="cursor-pointer justify-self-center rounded-full px-3 py-2 text-[13.5px] text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground">
          {t("notNow")}
        </button>
      )}
    </div>
  );
}
