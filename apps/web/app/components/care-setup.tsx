"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

import { formValue } from "../lib/api";
import type { Beneficiary, Dashboard, ProductSuggestion, Supply, SupplyAutomationTiming } from "../lib/types";

type Props = {
  dashboard: Dashboard;
  automationTimings: SupplyAutomationTiming[];
  busy: boolean;
  view: "beneficiaries" | "supplies" | "merchants";
  onCreate: (event: FormEvent<HTMLFormElement>, path: string, body: object) => void;
  onToggle: (path: string, body: object) => void;
  onRetryProductSetup: (supplyId: string) => void;
  onDeleteSupply: (supplyId: string, supplyName: string) => void;
  onUpdateStock: (supplyId: string, quantityOnHand: number) => void;
  onSearchProducts: (query: string) => Promise<ProductSuggestion[]>;
};

const supportedMerchants = [
  { key: "himalaya", name: "Himalaya Wellness", description: "OTC wellness and personal-care supplies" },
  { key: "oziva", name: "Oziva", description: "Nutrition and wellness products" },
  { key: "zandu", name: "Zandu Care", description: "Traditional wellness and OTC products" },
];

export function CareSetup(props: Props) {
  if (props.view === "beneficiaries") return <BeneficiariesPanel {...props} />;
  if (props.view === "merchants") return <MerchantsPanel {...props} />;
  return <SuppliesPanel {...props} />;
}

function addressBody(form: HTMLFormElement) {
  return {
    delivery_recipient: formValue(form, "recipient") || null,
    delivery_line1: formValue(form, "line1") || null,
    delivery_line2: formValue(form, "line2") || null,
    delivery_city: formValue(form, "city") || null,
    delivery_region: formValue(form, "region") || null,
    delivery_postal_code: formValue(form, "postal") || null,
    delivery_country: formValue(form, "country") || "IN",
    delivery_phone: formValue(form, "phone") || null,
    delivery_email: formValue(form, "email") || null,
  };
}

const RELATIONSHIPS = ["Self", "Parent", "Partner", "Family member", "Other"];

/** The delivery address, grouped by what a courier actually needs rather than one flat column. */
function AddressFields({ person }: { person?: Beneficiary }) {
  return (
    <>
      <label>Who should the courier ask for?<input name="recipient" defaultValue={person?.delivery_recipient ?? person?.name ?? ""} maxLength={160} placeholder="Full name" /></label>
      <label>House and street<input name="line1" placeholder="For example, 12 Rose Lane" defaultValue={person?.delivery_line1 ?? ""} maxLength={255} /></label>
      <label>Apartment or landmark<small>Optional</small><input name="line2" defaultValue={person?.delivery_line2 ?? ""} maxLength={255} /></label>
      <div className="split">
        <label>City<input name="city" defaultValue={person?.delivery_city ?? ""} maxLength={120} /></label>
        <label>State<input name="region" defaultValue={person?.delivery_region ?? ""} maxLength={120} /></label>
      </div>
      <div className="split">
        <label>PIN code<input name="postal" inputMode="numeric" defaultValue={person?.delivery_postal_code ?? ""} maxLength={24} /></label>
        <label>Country<input name="country" defaultValue={person?.delivery_country ?? "IN"} maxLength={2} pattern="[A-Z]{2}" /></label>
      </div>
      <div className="split">
        <label>Phone<input name="phone" type="tel" inputMode="tel" defaultValue={person?.delivery_phone ?? ""} maxLength={32} placeholder="+91 …" /></label>
        <label>Email<input name="email" type="email" inputMode="email" defaultValue={person?.delivery_email ?? ""} maxLength={320} /></label>
      </div>
    </>
  );
}

function BeneficiariesPanel({ dashboard, busy, onCreate, onToggle }: Props) {
  const [relationship, setRelationship] = useState("Self");
  return (
    <div className="content-grid">
      <section className="card stack">
        <div><h2>Add someone</h2><p className="hint">Choose “Self” when these supplies are for you.</p></div>
        <form className="supply-form" onSubmit={(event) => onCreate(event, "/setup/beneficiaries", {
          name: formValue(event.currentTarget, "name"),
          relationship_label: relationship,
          ...addressBody(event.currentTarget),
        })}>
          <Step n={1} title="Who are we helping?" help="Their name, and how they relate to you.">
            <label>Name<input name="name" autoComplete="name" required maxLength={120} placeholder="For example, Sushila" /></label>
            <div className="chip-row">
              {RELATIONSHIPS.map((r) => (
                <Chip key={r} active={relationship === r} onClick={() => setRelationship(r)}>{r}</Chip>
              ))}
            </div>
          </Step>
          <Step n={2} title="Where do deliveries go?" help="Orders for this person ship here. You can add it later.">
            <AddressFields />
          </Step>
          <button className="submit-cta" disabled={busy}>Add beneficiary</button>
        </form>
      </section>
      <section className="card stack">
        <h2>Your beneficiaries</h2>
        {!dashboard.beneficiaries.length && <p className="empty-state">No one has been added yet.</p>}
        <div className="people-list">{dashboard.beneficiaries.map((item) => <article key={item.id} className="supply-card">
          <header><div><strong>{item.name}</strong><small>{item.relationship_label}</small></div><span className={`status-pill ${item.has_delivery_address ? "approved" : "needs_attention"}`}>{item.has_delivery_address ? "Address saved" : "Address needed"}</span></header>
          {item.has_delivery_address
            ? <p className="hint">Ships to {[item.delivery_line1, item.delivery_city, item.delivery_postal_code].filter(Boolean).join(", ")}</p>
            : <p className="hint">Add a delivery address before automatic orders can be placed for {item.name}.</p>}
          <details className="stock-manager">
            <summary><span>Delivery address</span><small>Where {item.name}’s orders are shipped</small></summary>
            <div className="stock-manager-body">
              <form className="stack compact" onSubmit={(event) => { event.preventDefault(); onToggle(`/setup/beneficiaries/${item.id}`, addressBody(event.currentTarget)); }}>
                <AddressFields person={item} />
                <button className="quiet" disabled={busy}>Save address</button>
              </form>
            </div>
          </details>
          <div className="card-actions"><button className="quiet" disabled={busy} onClick={() => onToggle(`/setup/beneficiaries/${item.id}`, { is_active: !item.is_active })}>{item.is_active ? "Active" : "Paused"}</button></div>
        </article>)}</div>
      </section>
    </div>
  );
}

function MerchantsPanel({ dashboard, busy, onCreate, onToggle }: Props) {
  const selected = new Map(dashboard.merchant_authorizations.map((item) => [item.merchant_key, item]));
  return (
    <section className="stack page-section">
      <div className="plain-heading"><h2>Where Health Guard may shop</h2><p>Select only stores you trust. A separate Prava mandate sets the spending limit for each one.</p></div>
      <div className="merchant-grid">{supportedMerchants.map((merchant, index) => {
        const authorization = selected.get(merchant.key);
        return <article className={`merchant-card ${authorization?.is_enabled ? "selected" : ""}`} key={merchant.key}><div className="merchant-mark">{merchant.name.slice(0, 1)}</div><div><h3>{merchant.name}</h3><p>{merchant.description}</p></div>{authorization ? <button className="quiet" disabled={busy} onClick={() => onToggle(`/setup/merchant-authorizations/${authorization.id}`, { is_enabled: !authorization.is_enabled })}>{authorization.is_enabled ? "Selected" : "Select again"}</button> : <form onSubmit={(event) => onCreate(event, "/setup/merchant-authorizations", { merchant_key: merchant.key, preference_rank: dashboard.merchant_authorizations.length + index + 1 })}><button disabled={busy}>Select merchant</button></form>}</article>;
      })}</div>
    </section>
  );
}

function SuppliesPanel({ dashboard, automationTimings, busy, onCreate, onToggle, onRetryProductSetup, onDeleteSupply, onUpdateStock, onSearchProducts }: Props) {
  const supplies = dashboard.beneficiaries.flatMap((beneficiary) => beneficiary.supplies.map((supply) => ({ supply, beneficiary })));
  const timings = new Map(automationTimings.map((timing) => [timing.supply_id, timing]));
  const [beneficiaryId, setBeneficiaryId] = useState("");
  const [supplyName, setSupplyName] = useState("");
  const [requirements, setRequirements] = useState("");
  const [unit, setUnit] = useState("tablet");
  const [daily, setDaily] = useState("");
  const [onHand, setOnHand] = useState("");
  const [buffer, setBuffer] = useState("");
  const [preferredPack, setPreferredPack] = useState("");
  const [suggestions, setSuggestions] = useState<ProductSuggestion[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchedQuery, setSearchedQuery] = useState("");
  const searchSequence = useRef(0);
  const selectedName = useRef("");

  useEffect(() => {
    const query = supplyName.trim();
    if (query.length < 3 || query === selectedName.current) return;
    const sequence = ++searchSequence.current;
    const timer = window.setTimeout(async () => {
      setSearching(true);
      try {
        const results = await onSearchProducts(query);
        if (sequence === searchSequence.current) {
          setSuggestions(results);
          setSearchedQuery(query);
        }
      } catch {
        if (sequence === searchSequence.current) {
          setSuggestions([]);
          setSearchedQuery(query);
        }
      } finally {
        if (sequence === searchSequence.current) setSearching(false);
      }
    }, 450);
    return () => window.clearTimeout(timer);
  }, [onSearchProducts, supplyName]);

  const resetSupplyForm = () => {
    searchSequence.current += 1;
    selectedName.current = "";
    setBeneficiaryId("");
    setSupplyName("");
    setRequirements("");
    setUnit("tablet");
    setDaily("");
    setOnHand("");
    setBuffer("");
    setPreferredPack("");
    setSuggestions([]);
    setSearchedQuery("");
    setSearching(false);
  };

  const chooseSuggestion = (suggestion: ProductSuggestion) => {
    const variant = suggestion.variant_title && suggestion.variant_title !== "Default Title" ? `, ${suggestion.variant_title}` : "";
    selectedName.current = suggestion.product_title;
    searchSequence.current += 1;
    setSupplyName(suggestion.product_title);
    setRequirements(`${suggestion.product_title}${variant}`);
    setUnit(suggestion.pack_unit);
    setPreferredPack(suggestion.pack_quantity);
    setSuggestions([]);
    setSearchedQuery("");
    setSearching(false);
  };

  const timeline = inventoryTimeline(onHand, daily, buffer);
  return (
    <div className="content-grid supplies-layout">
      <section className="card stack">
        <div><h2>Add a recurring supply</h2><p className="hint">Use an ordinary product name. Health Guard searches live catalogs and safely chooses the product and pack.</p></div>
        {!dashboard.beneficiaries.some((item) => item.is_active) ? <p className="empty-state">Add an active beneficiary first.</p> : <form className="supply-form" onReset={resetSupplyForm} onSubmit={(event) => {
          onCreate(event, `/setup/beneficiaries/${beneficiaryId}/supplies`, {
            name: supplyName,
            product_requirements: requirements || null,
            unit,
            daily_consumption: Number(daily),
            quantity_on_hand: Number(onHand),
            safety_buffer_quantity: Number(buffer),
            preferred_pack_quantity: preferredPack ? Number(preferredPack) : null,
          });
        }}>
          <Step n={1} title="Who is it for?" help="Keeps every person's supplies and transactions separate.">
            <div className="person-picker">
              {dashboard.beneficiaries.filter((item) => item.is_active).map((item) => (
                <button
                  type="button" key={item.id}
                  className={`person-chip ${beneficiaryId === item.id ? "chip-on" : ""}`}
                  aria-pressed={beneficiaryId === item.id}
                  onClick={() => setBeneficiaryId(item.id)}
                >
                  <span className="avatar" aria-hidden>{item.name.slice(0, 1).toUpperCase()}</span>
                  <span><b>{item.name}</b><small>{item.relationship_label}</small></span>
                </button>
              ))}
            </div>
          </Step>

          <Step n={2} title="What should never run out?" help="Type an ordinary name — we search your shops' live catalogues.">
            <input
              name="supply" value={supplyName}
              onChange={(event) => { selectedName.current = ""; searchSequence.current += 1; setSupplyName(event.target.value); setSuggestions([]); setSearchedQuery(""); setSearching(false); }}
              placeholder="For example, Ashwagandha" required maxLength={160} autoComplete="off"
            />
            {(searching || suggestions.length > 0 || (searchedQuery === supplyName.trim() && searchedQuery.length >= 3)) && <div className="catalog-suggestions" aria-live="polite">
              <div className="suggestion-heading"><strong>Live recommendations</strong>{searching && <span>Searching…</span>}</div>
              {!searching && suggestions.map((suggestion) => <button type="button" className="catalog-suggestion" key={`${suggestion.merchant_key}:${suggestion.variant_id}`} onClick={() => chooseSuggestion(suggestion)}><span><b>{suggestion.product_title}</b><small>{suggestion.variant_title && suggestion.variant_title !== "Default Title" ? suggestion.variant_title : `${suggestion.pack_quantity} ${suggestion.pack_unit}s`}</small></span><span><b>{formatMoney(suggestion.unit_price, suggestion.currency)}</b><small>{suggestion.merchant_name}</small></span></button>)}
              {!searching && !suggestions.length && <p>No matching products at your selected shops.</p>}
            </div>}
            <details className="opt-block">
              <summary><span>Want a specific brand or pack?</span><small>Optional</small></summary>
              <div className="opt-body">
                <textarea name="requirements" value={requirements} onChange={(event) => setRequirements(event.target.value)} placeholder="For example, Himalaya Organic Ashwagandha caplets" maxLength={1000} rows={3} />
                <small className="hint">Leave blank and Health Guard picks the best match itself.</small>
              </div>
            </details>
          </Step>

          <Step n={3} title="How is it counted?" help="Tap the unit you'd use when counting what's left.">
            <div className="chip-row">
              {UNITS.map((u) => (
                <Chip key={u.value} active={unit === u.value} onClick={() => { selectedName.current = ""; setUnit(u.value); }}>{u.label}</Chip>
              ))}
            </div>
          </Step>

          <Step n={4} title="How much?" help="Use − and + , or type the number.">
            <div className="stepper-grid">
              <Stepper label="Used each day" help="How many per day" value={daily} onChange={setDaily} step={1} min={0} suffix={unit ? `${unit}s / day` : undefined} />
              <Stepper label="Amount on hand" help="Available today" value={onHand} onChange={setOnHand} step={1} min={0} suffix={unit ? `${unit}s` : undefined} />
              <Stepper label="Reorder at" help="Reorder when it drops to this" value={buffer} onChange={setBuffer} step={1} min={0} suffix={unit ? `${unit}s` : undefined} />
            </div>
            <details className="opt-block">
              <summary><span>Prefer a particular pack size?</span><small>Optional</small></summary>
              <div className="opt-body">
                <input name="preferredPack" value={preferredPack} onChange={(event) => setPreferredPack(event.target.value)} type="number" inputMode="decimal" min="0.001" step="0.001" placeholder="For example, 60" />
                <small className="hint">Leave blank to let Health Guard choose from available packs.</small>
              </div>
            </details>
          </Step>

          {timeline && <div className={`inventory-timeline ${timeline.due ? "due" : ""}`}><span>Estimated reorder timeline</span><strong>{timeline.label}</strong><small>(amount on hand − reorder at) ÷ used each day</small></div>}
          <button className="submit-cta" disabled={busy || !beneficiaryId}>{beneficiaryId ? "Add recurring supply" : "Choose who it's for first"}</button>
        </form>}
      </section>
      <section className="card stack supply-overview"><h2>Your recurring supplies</h2>{!supplies.length && <p className="empty-state">Your supplies will appear here.</p>}{supplies.map(({ supply, beneficiary }) => <SupplyCard key={supply.id} supply={supply} timing={timings.get(supply.id)} beneficiaryName={beneficiary.name} busy={busy} onToggle={onToggle} onRetry={onRetryProductSetup} onDelete={onDeleteSupply} onUpdateStock={onUpdateStock} />)}</section>
    </div>
  );
}

function Field({ label, help, children }: { label: string; help: string; children: React.ReactNode }) {
  return <label>{label}<small>{help}</small>{children}</label>;
}

/** One numbered section of the setup flow. Breaking the form into steps stops it reading as an
 *  intimidating wall of eight identical inputs. */
function Step({ n, title, help, children }: { n: number; title: string; help?: string; children: React.ReactNode }) {
  return (
    <section className="fstep">
      <header><span className="fstep-n">{n}</span><div><h3>{title}</h3>{help && <small>{help}</small>}</div></header>
      <div className="fstep-body">{children}</div>
    </section>
  );
}

/** A tap target instead of a dropdown. Native selects on a phone open a full-screen wheel that
 *  hides the rest of the form; chips keep every option visible and are far easier to hit. */
function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" className={`chip ${active ? "chip-on" : ""}`} aria-pressed={active} onClick={onClick}>
      {children}
    </button>
  );
}

/** Big −/+ buttons around the value. Phone number-spinners are a few pixels tall and unusable
 *  for anyone with reduced dexterity; these are full 52px targets. */
function Stepper({
  label, help, value, onChange, step = 1, min = 0, suffix,
}: { label: string; help: string; value: string; onChange: (v: string) => void; step?: number; min?: number; suffix?: string }) {
  const nudge = (delta: number) => {
    const next = Math.max(min, Number((Number(value || 0) + delta).toFixed(3)));
    onChange(String(next));
  };
  return (
    <div className="stepper-field">
      <span className="stepper-label">{label}</span>
      <small>{help}</small>
      <div className="stepper">
        <button type="button" onClick={() => nudge(-step)} aria-label={`Decrease ${label}`}>−</button>
        <input
          value={value}
          onChange={(event) => onChange(event.target.value)}
          type="number" inputMode="decimal" min={min} step="0.001" required
          aria-label={label}
        />
        <button type="button" onClick={() => nudge(step)} aria-label={`Increase ${label}`}>+</button>
      </div>
      {suffix && <small className="stepper-suffix">{suffix}</small>}
    </div>
  );
}

const UNITS = [
  { value: "tablet", label: "Tablets" }, { value: "capsule", label: "Capsules" },
  { value: "strip", label: "Strips" }, { value: "sachet", label: "Sachets" },
  { value: "packet", label: "Packets" }, { value: "swab", label: "Swabs" },
  { value: "bottle", label: "Bottles" }, { value: "gram", label: "Grams" },
  { value: "kilogram", label: "Kilograms" }, { value: "milliliter", label: "Millilitres" },
  { value: "liter", label: "Litres" }, { value: "unit", label: "Units" },
];

/** How much is left, as a plain-English state rather than a number to interpret.
 *  Full = comfortably above the reorder level; the bar empties as stock approaches it. */
function StockMeter({ supply }: { supply: Supply }) {
  const onHand = Number(supply.estimated_quantity_on_hand);
  const reorderAt = Number(supply.safety_buffer_quantity);
  const daily = Number(supply.daily_consumption);
  if (!Number.isFinite(onHand) || !Number.isFinite(reorderAt) || !Number.isFinite(daily) || daily <= 0) return null;

  // A full bar is two weeks of cover above the reorder level — long enough that "full" means
  // genuinely relaxed, short enough that the bar visibly moves week to week.
  const headroom = Math.max(onHand - reorderAt, 0);
  const percent = Math.max(2, Math.min(100, Math.round((headroom / (daily * 14)) * 100)));
  const daysLeft = headroom / daily;

  const tone = daysLeft <= 0 ? "critical" : daysLeft <= 3 ? "warn" : "";
  const state = daysLeft <= 0 ? "Reorder due" : daysLeft <= 3 ? "Running low" : "Well stocked";
  const plain =
    daysLeft <= 0
      ? "Stock has reached the reorder level."
      : `About ${daysLeft < 1 ? "less than a day" : `${Math.round(daysLeft)} day${Math.round(daysLeft) === 1 ? "" : "s"}`} before the reorder level.`;

  return (
    <div className="meter">
      <div className="meter-head">
        <span className="meter-label">Supply level</span>
        <span className="meter-value">{supply.estimated_quantity_on_hand} {supply.unit}s left</span>
      </div>
      <div
        className="meter-track"
        role="meter"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        aria-valuetext={`${state}. ${plain}`}
      >
        <div className={`meter-fill ${tone}`} style={{ width: `${percent}%` }} />
      </div>
      <span className={`meter-state ${tone}`}>{state}<span className="hint" style={{ fontWeight: 500 }}> · {plain}</span></span>
    </div>
  );
}

function inventoryTimeline(onHandValue: string, dailyValue: string, bufferValue: string) {
  const onHand = Number(onHandValue);
  const daily = Number(dailyValue);
  const buffer = Number(bufferValue);
  if (!onHandValue || !dailyValue || !bufferValue || !Number.isFinite(onHand) || !Number.isFinite(daily) || !Number.isFinite(buffer) || daily <= 0 || onHand < 0 || buffer < 0) return null;
  const days = Math.max(0, (onHand - buffer) / daily);
  if (days === 0) return { due: true, label: "Due immediately because stock is already at or below the reorder level." };
  const formatted = days < 1 ? `${Math.round(days * 24)} hours` : `${Number(days.toFixed(2))} days`;
  return { due: false, label: `The reorder level will be reached in about ${formatted}.` };
}

function formatDateTime(value: string) {
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" });
}

function formatMoney(value: string, currency: string) {
  return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(Number(value));
}

function Countdown({ value }: { value: string }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const remaining = Math.max(0, new Date(value).getTime() - now);
  if (remaining === 0) return <span className="countdown">Checking now</span>;
  const seconds = Math.floor(remaining / 1000);
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  const label = days > 0 ? `${days}d ${hours}h ${minutes}m` : hours > 0 ? `${hours}h ${minutes}m ${remainder}s` : `${minutes}m ${remainder}s`;
  return <span className="countdown">in {label}</span>;
}

function SupplyCard({ supply, timing, beneficiaryName, busy, onToggle, onRetry, onDelete, onUpdateStock }: { supply: Supply; timing: SupplyAutomationTiming | undefined; beneficiaryName: string; busy: boolean; onToggle: Props["onToggle"]; onRetry: Props["onRetryProductSetup"]; onDelete: Props["onDeleteSupply"]; onUpdateStock: Props["onUpdateStock"] }) {
  const ready = supply.setup_status === "ready";
  const frequencyWaiting = timing?.payment_eligibility_state === "frequency_wait";
  const label = ready ? "Ready" : supply.setup_status === "discovering" ? "Checking product" : supply.setup_status === "needs_attention" ? "Needs attention" : "Waiting for merchant";
  const purchasedTotal = supply.stock_movements.filter((item) => item.movement_type === "automatic_purchase").reduce((total, item) => total + Number(item.quantity_delta), 0);
  const timingText = timing?.state === "paused" ? "Paused" : timing?.state === "scheduler_off" ? "Automatic scheduler is off" : timing?.state === "setup_required" ? "Product setup must finish first" : timing?.next_automatic_check_at ? formatDateTime(timing.next_automatic_check_at) : "Synchronizing schedule…";
  return <article className="supply-card">
    <header><div><strong>{supply.name}</strong><small>For {beneficiaryName}</small></div><span className={`status-pill ${ready ? "approved" : supply.setup_status}`}>{label}</span></header>
    <p>{supply.setup_message}</p>
    {supply.agent_summary && <p className="agent-note">{supply.agent_summary}</p>}
    <StockMeter supply={supply} />
    <div className="supply-stats"><span><b>{supply.daily_consumption}</b> used each day</span><span>Reorder at <b>{supply.safety_buffer_quantity}</b></span>{purchasedTotal > 0 && <span><b>+{purchasedTotal}</b> added by orders</span>}</div>
    {ready && <div className={`payment-readiness ${frequencyWaiting ? "waiting" : ""}`}>
      <div className="chargeable-price"><small>Current chargeable price</small><strong>{timing?.chargeable_price && timing.chargeable_currency ? formatMoney(timing.chargeable_price, timing.chargeable_currency) : "Price is being verified"}</strong><span>{timing?.merchant_name ?? "Approved merchant"}{timing?.price_checked_at ? ` · checked ${formatDateTime(timing.price_checked_at)}` : ""}</span></div>
      <div className="mandate-readiness"><small>Payment permission</small><strong>{timing?.mandate_frequency ? `Once ${timing.mandate_frequency === "weekly" ? "a week" : timing.mandate_frequency === "monthly" ? "a month" : "a year"}` : "Mandate not ready"}</strong><span>{timing?.payment_eligibility_message ?? "Checking mandate status…"}</span></div>
      {frequencyWaiting && timing?.next_payment_eligible_at && <div className="frequency-wait-notice"><strong>No payment will be attempted yet</strong><span>Next eligible: {formatDateTime(timing.next_payment_eligible_at)}</span><Countdown value={timing.next_payment_eligible_at} /></div>}
    </div>}
    <details className="stock-manager">
      <summary><span>Stock management</span><small>Counts and automatic purchases</small></summary>
      <div className="stock-manager-body">
        <form className="stock-count-form" onSubmit={(event) => { event.preventDefault(); const quantity = Number(formValue(event.currentTarget, "stockCount")); if (Number.isFinite(quantity) && quantity >= 0) onUpdateStock(supply.id, quantity); }}>
          <label>Current physical stock<small>Use this when you count what is actually available.</small><input key={supply.inventory_observed_at} name="stockCount" type="number" min="0" step="0.001" defaultValue={supply.estimated_quantity_on_hand} required /></label>
          <button className="quiet" disabled={busy}>Update stock</button>
        </form>
        <div className="stock-history"><strong>Recent stock history</strong>{!supply.stock_movements.length && <small>No stock changes recorded yet.</small>}{supply.stock_movements.slice(0, 5).map((movement) => <div className="stock-movement" key={movement.id}><span className={Number(movement.quantity_delta) >= 0 ? "stock-in" : "stock-out"}>{Number(movement.quantity_delta) >= 0 ? "+" : ""}{movement.quantity_delta} {movement.unit}s</span><span><b>{movement.movement_type === "automatic_purchase" ? "Automatic purchase" : movement.movement_type === "initial_balance" ? "Starting stock" : "Stock count"}</b><small>{formatDateTime(movement.occurred_at)} · balance {movement.balance_after}</small></span></div>)}</div>
      </div>
    </details>
    {ready && <div className={`next-order ${supply.order_due ? "due" : ""}`}><div><span>Next automatic payment check</span><strong>{timingText}</strong>{timing?.next_automatic_check_at && <Countdown value={timing.next_automatic_check_at} />}</div><small>{frequencyWaiting ? "Waiting for mandate renewal" : supply.order_due ? "Reorder level reached" : `Reorder level expected ${formatDateTime(supply.next_order_at)}`}</small><p>{frequencyWaiting ? "The product needs replenishment, but Health Guard will wait for the next mandate cycle instead of sending a payment that Prava would decline." : "A purchase is attempted at this check only if the product, mandate, availability, and spending rules still pass."}</p></div>}
    <div className="card-actions">{ready && <button className="quiet" disabled={busy} onClick={() => onToggle(`/setup/supplies/${supply.id}`, { is_enabled: !supply.is_enabled })}>{supply.is_enabled ? "Pause automatic orders" : "Resume automatic orders"}</button>}{supply.setup_status === "needs_attention" && (supply.product_requirements || supply.preferred_pack_quantity) && <button className="quiet" disabled={busy} onClick={() => onToggle(`/setup/supplies/${supply.id}`, { product_requirements: null, preferred_pack_quantity: null })}>Let Health Guard choose</button>}{supply.setup_status === "needs_attention" && <button className="quiet" disabled={busy} onClick={() => onRetry(supply.id)}>Try product check again</button>}<button className="danger-outline" disabled={busy} onClick={() => onDelete(supply.id, supply.name)}>Delete supply</button></div>
  </article>;
}
