"use client";

import { FormEvent } from "react";

import { formValue } from "../lib/api";
import type { Dashboard, Supply } from "../lib/types";

type Props = {
  dashboard: Dashboard;
  busy: boolean;
  onCreate: (event: FormEvent<HTMLFormElement>, path: string, body: object) => void;
  onToggle: (path: string, body: object) => void;
};

export function CareSetup({ dashboard, busy, onCreate, onToggle }: Props) {
  const supplies = dashboard.beneficiaries.flatMap((beneficiary) => beneficiary.supplies);
  const equivalenceSets = supplies.flatMap((supply) => supply.equivalence_sets);
  return (
    <div className="dashboard-grid">
      <section className="card stack">
        <h2>1. People receiving care</h2>
        <form className="stack compact" onSubmit={(event) => onCreate(event, "/setup/beneficiaries", { name: formValue(event.currentTarget, "name"), relationship_label: formValue(event.currentTarget, "relationship") })}>
          <label>Name <input name="name" required maxLength={120} /></label>
          <label>Relationship <input name="relationship" placeholder="Self, mother, father…" required maxLength={80} /></label>
          <button disabled={busy}>Add beneficiary</button>
        </form>
        <ul className="items">{dashboard.beneficiaries.map((item) => <li key={item.id}><span><strong>{item.name}</strong><small>{item.relationship_label}</small></span><button className="quiet" disabled={busy} onClick={() => onToggle(`/setup/beneficiaries/${item.id}`, { is_active: !item.is_active })}>{item.is_active ? "Active" : "Paused"}</button></li>)}</ul>
      </section>

      <section className="card stack">
        <h2>2. Approved merchants</h2>
        <form className="stack compact" onSubmit={(event) => onCreate(event, "/setup/merchant-authorizations", { merchant_key: formValue(event.currentTarget, "merchant"), preference_rank: Number(formValue(event.currentTarget, "rank")) })}>
          <label>Merchant <select name="merchant" required defaultValue=""><option value="" disabled>Select a supported merchant</option><option value="himalaya">Himalaya Wellness</option><option value="oziva">Oziva</option><option value="zandu">Zandu Care</option></select></label>
          <label>Preference rank <input name="rank" type="number" min="1" max="99" defaultValue="1" required /></label>
          <button disabled={busy}>Approve merchant</button>
        </form>
        <ul className="items">{dashboard.merchant_authorizations.map((item) => <li key={item.id}><span><strong>{item.merchant_name}</strong><small>#{item.preference_rank} · {item.merchant_domain}</small></span><button className="quiet" disabled={busy} onClick={() => onToggle(`/setup/merchant-authorizations/${item.id}`, { is_enabled: !item.is_enabled })}>{item.is_enabled ? "Approved" : "Paused"}</button></li>)}</ul>
      </section>

      <section className="card stack">
        <h2>3. Recurring supplies</h2>
        <form className="stack compact" onSubmit={(event) => onCreate(event, `/setup/beneficiaries/${formValue(event.currentTarget, "beneficiary")}/supplies`, { name: formValue(event.currentTarget, "supply"), unit: formValue(event.currentTarget, "unit"), daily_consumption: Number(formValue(event.currentTarget, "daily")), quantity_on_hand: Number(formValue(event.currentTarget, "onHand")), safety_buffer_quantity: Number(formValue(event.currentTarget, "buffer")) })}>
          <label>Beneficiary <select name="beneficiary" required defaultValue=""><option value="" disabled>Select a person</option>{dashboard.beneficiaries.filter((item) => item.is_active).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <label>Supply name <input name="supply" placeholder="e.g. glucose test strips" required maxLength={160} /></label>
          <label>Unit <input name="unit" placeholder="strips, tablets, swabs" required maxLength={40} /></label>
          <div className="split"><label>Used each day <input name="daily" type="number" min="0.001" step="0.001" required /></label><label>On hand <input name="onHand" type="number" min="0" step="0.001" required /></label></div>
          <label>Safety buffer (same unit) <input name="buffer" type="number" min="0" step="0.001" required /></label>
          <button disabled={busy}>Add supply (starts paused)</button>
        </form>
      </section>

      <section className="card stack">
        <h2>4. Explicit equivalence</h2><p className="hint">A substitution is never inferred. Define the allowed product group, then approve only exact merchant product and variant IDs.</p>
        <form className="stack compact" onSubmit={(event) => onCreate(event, `/setup/supplies/${formValue(event.currentTarget, "supply")}/equivalence-sets`, { name: formValue(event.currentTarget, "setName"), notes: formValue(event.currentTarget, "notes") || null })}>
          <label>Supply <select name="supply" required defaultValue=""><option value="" disabled>Select a supply</option>{supplies.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <label>Equivalence set name <input name="setName" placeholder="Same approved formula and strength" required maxLength={160} /></label>
          <label>Notes <input name="notes" maxLength={1000} /></label><button disabled={busy}>Create equivalence set</button>
        </form>
        <form className="stack compact top-gap" onSubmit={(event) => onCreate(event, `/setup/equivalence-sets/${formValue(event.currentTarget, "set")}/approved-variants`, { merchant_authorization_id: formValue(event.currentTarget, "authorization"), merchant_product_id: formValue(event.currentTarget, "productId"), merchant_variant_id: formValue(event.currentTarget, "variantId"), display_name: formValue(event.currentTarget, "displayName"), pack_quantity: Number(formValue(event.currentTarget, "packQuantity")), pack_unit: formValue(event.currentTarget, "packUnit") })}>
          <h3>Approve an exact variant</h3>
          <label>Equivalence set <select name="set" required defaultValue=""><option value="" disabled>Select a set</option>{equivalenceSets.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <label>Merchant <select name="authorization" required defaultValue=""><option value="" disabled>Select approved merchant</option>{dashboard.merchant_authorizations.filter((item) => item.is_enabled).map((item) => <option key={item.id} value={item.id}>{item.merchant_name}</option>)}</select></label>
          <label>Exact product ID <input name="productId" required maxLength={255} /></label><label>Exact variant ID <input name="variantId" required maxLength={255} /></label><label>Display name <input name="displayName" required maxLength={255} /></label>
          <div className="split"><label>Pack quantity <input name="packQuantity" type="number" min="0.001" step="0.001" required /></label><label>Pack unit <input name="packUnit" placeholder="tablets" required maxLength={40} /></label></div><button disabled={busy}>Approve exact variant</button>
        </form>
      </section>
      <ConfiguredInventory dashboard={dashboard} busy={busy} onToggle={onToggle} />
    </div>
  );
}

function ConfiguredInventory({ dashboard, busy, onToggle }: Pick<Props, "dashboard" | "busy" | "onToggle">) {
  return <section className="card configured"><h2>Configured care inventory</h2>{!dashboard.beneficiaries.length && <p className="muted">No care inventory has been added yet.</p>}{dashboard.beneficiaries.map((beneficiary) => <article key={beneficiary.id} className="beneficiary"><h3>{beneficiary.name} <span>{beneficiary.relationship_label}</span></h3>{!beneficiary.supplies.length && <p className="muted">No supplies configured.</p>}<ul className="supply-list">{beneficiary.supplies.map((supply: Supply) => <li key={supply.id}><div><strong>{supply.name}</strong><small>{supply.quantity_on_hand} {supply.unit} on hand · {supply.daily_consumption}/{supply.unit}/day · buffer {supply.safety_buffer_quantity}</small>{supply.equivalence_sets.map((set) => <div className="equivalence" key={set.id}><b>{set.name}</b>{set.approved_variants.length ? <ul>{set.approved_variants.map((variant) => <li key={variant.id}>{variant.display_name} — product {variant.merchant_product_id}, variant {variant.merchant_variant_id}</li>)}</ul> : <small>No exact variants approved.</small>}</div>)}</div><button className="quiet" disabled={busy} onClick={() => onToggle(`/setup/supplies/${supply.id}`, { is_enabled: !supply.is_enabled })}>{supply.is_enabled ? "Enabled" : "Paused"}</button></li>)}</ul></article>)}</section>;
}
