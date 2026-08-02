"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

import { formValue } from "../lib/api";
import type { Dashboard, ProductSuggestion, Supply, SupplyAutomationTiming } from "../lib/types";

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

function BeneficiariesPanel({ dashboard, busy, onCreate, onToggle }: Props) {
  return (
    <div className="content-grid">
      <section className="card stack">
        <div><h2>Add someone</h2><p className="hint">Choose “Self” when these supplies are for you.</p></div>
        <form className="stack compact" onSubmit={(event) => onCreate(event, "/setup/beneficiaries", {
          name: formValue(event.currentTarget, "name"),
          relationship_label: formValue(event.currentTarget, "relationship"),
        })}>
          <label>Name<input name="name" autoComplete="name" required maxLength={120} /></label>
          <label>Relationship<select name="relationship" defaultValue="Self" required><option>Self</option><option>Parent</option><option>Partner</option><option>Family member</option><option>Other</option></select></label>
          <button disabled={busy}>Add beneficiary</button>
        </form>
      </section>
      <section className="card stack">
        <h2>Your beneficiaries</h2>
        {!dashboard.beneficiaries.length && <p className="empty-state">No one has been added yet.</p>}
        <div className="people-list">{dashboard.beneficiaries.map((item) => <article key={item.id} className="person-row"><div className="avatar" aria-hidden>{item.name.slice(0, 1).toUpperCase()}</div><div><strong>{item.name}</strong><small>{item.relationship_label}</small></div><button className="quiet" disabled={busy} onClick={() => onToggle(`/setup/beneficiaries/${item.id}`, { is_active: !item.is_active })}>{item.is_active ? "Active" : "Paused"}</button></article>)}</div>
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
        {!dashboard.beneficiaries.some((item) => item.is_active) ? <p className="empty-state">Add an active beneficiary first.</p> : <form className="stack supply-form" onReset={resetSupplyForm} onSubmit={(event) => {
          onCreate(event, `/setup/beneficiaries/${formValue(event.currentTarget, "beneficiary")}/supplies`, {
            name: supplyName,
            product_requirements: requirements || null,
            unit,
            daily_consumption: Number(daily),
            quantity_on_hand: Number(onHand),
            safety_buffer_quantity: Number(buffer),
            preferred_pack_quantity: preferredPack ? Number(preferredPack) : null,
          });
        }}>
          <Field label="Who is it for?" help="Keeps every person's supplies and transactions separate."><select name="beneficiary" required defaultValue=""><option value="" disabled>Select a beneficiary</option>{dashboard.beneficiaries.filter((item) => item.is_active).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field>
          <Field label="Supply name" help="Start typing an ordinary name. Recommendations come from your selected merchants' live catalogs."><input name="supply" value={supplyName} onChange={(event) => { selectedName.current = ""; searchSequence.current += 1; setSupplyName(event.target.value); setSuggestions([]); setSearchedQuery(""); setSearching(false); }} placeholder="For example, Ashwagandha" required maxLength={160} autoComplete="off" /></Field>
          {(searching || suggestions.length > 0 || (searchedQuery === supplyName.trim() && searchedQuery.length >= 3)) && <div className="catalog-suggestions" aria-live="polite">
            <div className="suggestion-heading"><strong>Live product recommendations</strong>{searching && <span>Searching catalogs…</span>}</div>
            {!searching && suggestions.map((suggestion) => <button type="button" className="catalog-suggestion" key={`${suggestion.merchant_key}:${suggestion.variant_id}`} onClick={() => chooseSuggestion(suggestion)}><span><b>{suggestion.product_title}</b><small>{suggestion.variant_title && suggestion.variant_title !== "Default Title" ? suggestion.variant_title : `${suggestion.pack_quantity} ${suggestion.pack_unit}s`}</small></span><span><b>{formatMoney(suggestion.unit_price, suggestion.currency)}</b><small>{suggestion.merchant_name}</small></span></button>)}
            {!searching && !suggestions.length && <p>No live matching products were found at your selected merchants.</p>}
          </div>}
          <Field label="Specific product preference (optional)" help="Leave blank to let Health Guard choose. Selecting a recommendation fills this for you."><textarea name="requirements" value={requirements} onChange={(event) => setRequirements(event.target.value)} placeholder="For example, Himalaya Organic Ashwagandha caplets" maxLength={1000} rows={3} /></Field>
          <Field label="How is it counted?" help="The unit used when tracking what remains. Selecting a recommendation sets this from the catalog."><select name="unit" value={unit} onChange={(event) => { selectedName.current = ""; setUnit(event.target.value); }} required><option value="tablet">Tablets</option><option value="capsule">Capsules</option><option value="strip">Strips</option><option value="sachet">Sachets</option><option value="packet">Packets</option><option value="swab">Swabs</option><option value="bottle">Bottles</option><option value="gram">Grams</option><option value="kilogram">Kilograms</option><option value="milliliter">Milliliters</option><option value="liter">Liters</option><option value="unit">Units</option></select></Field>
          <div className="split"><Field label="Used each day" help="How many units are consumed per day."><input name="daily" value={daily} onChange={(event) => setDaily(event.target.value)} type="number" min="0.001" step="0.001" required /></Field><Field label="Amount on hand" help="The units available today."><input name="onHand" value={onHand} onChange={(event) => setOnHand(event.target.value)} type="number" min="0" step="0.001" required /></Field></div>
          <div className="split"><Field label="Reorder at" help="A check becomes due when estimated stock reaches this number."><input name="buffer" value={buffer} onChange={(event) => setBuffer(event.target.value)} type="number" min="0" step="0.001" required /></Field><Field label="Preferred pack size (optional)" help="Leave blank to let Health Guard choose from available pack sizes."><input name="preferredPack" value={preferredPack} onChange={(event) => setPreferredPack(event.target.value)} type="number" min="0.001" step="0.001" /></Field></div>
          {timeline && <div className={`inventory-timeline ${timeline.due ? "due" : ""}`}><span>Estimated reorder timeline</span><strong>{timeline.label}</strong><small>(amount on hand − reorder at) ÷ used each day</small></div>}
          <button disabled={busy}>Add recurring supply</button>
        </form>}
      </section>
      <section className="card stack supply-overview"><h2>Your recurring supplies</h2>{!supplies.length && <p className="empty-state">Your supplies will appear here.</p>}{supplies.map(({ supply, beneficiary }) => <SupplyCard key={supply.id} supply={supply} timing={timings.get(supply.id)} beneficiaryName={beneficiary.name} busy={busy} onToggle={onToggle} onRetry={onRetryProductSetup} onDelete={onDeleteSupply} onUpdateStock={onUpdateStock} />)}</section>
    </div>
  );
}

function Field({ label, help, children }: { label: string; help: string; children: React.ReactNode }) {
  return <label>{label}<small>{help}</small>{children}</label>;
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
    <div className="supply-stats"><span><b>{supply.estimated_quantity_on_hand}</b> estimated {supply.unit}s on hand</span><span><b>{supply.daily_consumption}</b> used each day</span><span>Reorder at <b>{supply.safety_buffer_quantity}</b></span>{purchasedTotal > 0 && <span><b>+{purchasedTotal}</b> added by orders</span>}</div>
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
