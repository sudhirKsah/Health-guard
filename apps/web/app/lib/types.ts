export type User = { id: string; email: string; display_name: string | null };
export type Session = { access_token: string; expires_at: string; user: User };

export type Variant = {
  id: string;
  merchant_authorization_id: string;
  merchant_product_id: string;
  merchant_variant_id: string;
  display_name: string;
  pack_quantity: string;
  pack_unit: string;
  latest_unit_price: string | null;
  latest_currency: string | null;
  price_checked_at: string | null;
};

export type EquivalenceSet = { id: string; name: string; notes: string | null; approved_variants: Variant[] };

export type StockMovement = {
  id: string;
  purchase_order_id: string | null;
  movement_type: "initial_balance" | "automatic_purchase" | "manual_count" | string;
  quantity_delta: string;
  balance_after: string;
  unit: string;
  note: string;
  occurred_at: string;
};

export type Supply = {
  id: string;
  name: string;
  unit: string;
  daily_consumption: string;
  quantity_on_hand: string;
  safety_buffer_quantity: string;
  is_enabled: boolean;
  product_requirements: string | null;
  preferred_pack_quantity: string | null;
  setup_status: "waiting_for_merchant" | "discovering" | "ready" | "needs_attention" | string;
  setup_message: string | null;
  agent_summary: string | null;
  configured_at: string | null;
  inventory_observed_at: string;
  payment_deferred_until: string | null;
  estimated_quantity_on_hand: string;
  next_order_at: string;
  order_due: boolean;
  equivalence_sets: EquivalenceSet[];
  stock_movements: StockMovement[];
};

export type Beneficiary = {
  id: string;
  name: string;
  relationship_label: string;
  is_active: boolean;
  delivery_recipient: string | null;
  delivery_email: string | null;
  delivery_phone: string | null;
  delivery_line1: string | null;
  delivery_line2: string | null;
  delivery_city: string | null;
  delivery_region: string | null;
  delivery_postal_code: string | null;
  delivery_country: string;
  has_delivery_address: boolean;
  supplies: Supply[];
};

export type MerchantAuthorization = {
  id: string;
  merchant_key: string;
  merchant_name: string;
  merchant_domain: string;
  preference_rank: number;
  is_enabled: boolean;
  prava_mandate_id: string | null;
  mandate_status: string | null;
  mandate_approved_amount: string | null;
  mandate_remaining_amount: string | null;
  mandate_currency: string | null;
  mandate_frequency: string | null;
  mandate_max_charges: number | null;
  health_guard_stop_after: string | null;
  mandate_valid_until: string | null;
  mandate_renews_at: string | null;
  mandate_last_charge_at: string | null;
  mandate_last_charge_status: string | null;
  mandate_synced_at: string | null;
};

export type Dashboard = { beneficiaries: Beneficiary[]; merchant_authorizations: MerchantAuthorization[] };

export type SupplyAutomationTiming = {
  supply_id: string;
  scheduler_enabled: boolean;
  interval_minutes: number;
  reorder_threshold_at: string;
  next_automatic_check_at: string | null;
  state: "scheduled" | "paused" | "setup_required" | "scheduler_off" | string;
  chargeable_price: string | null;
  chargeable_currency: string | null;
  price_checked_at: string | null;
  merchant_name: string | null;
  mandate_frequency: string | null;
  next_payment_eligible_at: string | null;
  payment_eligibility_state: "eligible" | "frequency_wait" | "cycle_sync_required" | "mandate_missing" | "mandate_inactive" | string;
  payment_eligibility_message: string;
};

export type ProductSuggestion = {
  merchant_key: string;
  merchant_name: string;
  product_id: string;
  variant_id: string;
  product_title: string;
  variant_title: string | null;
  pack_quantity: string;
  pack_unit: string;
  available: boolean;
  unit_price: string;
  currency: string;
};

export type MandateSetupSession = {
  merchant_authorization: MerchantAuthorization;
  iframe_url: string;
  expires_at: string | null;
};

export type AgentStep = {
  id: string;
  sequence: number;
  stage: string;
  tool_name: string;
  status: string;
  input_summary: Record<string, unknown>;
  output_summary: Record<string, unknown>;
  created_at: string;
};

export type OfferSnapshot = {
  id: string;
  merchant_authorization_id: string;
  merchant_product_id: string;
  merchant_variant_id: string;
  product_title: string;
  variant_title: string | null;
  available: boolean;
  currency: string;
  unit_price: string;
  shipping_price: string;
  landed_price: string;
  estimated_arrival_days: string | null;
  quote_id: string | null;
  quote_expires_at: string | null;
  source_status: string;
  created_at: string;
};

export type AgentRun = {
  id: string;
  supply_id: string;
  trigger_id: string;
  goal: string;
  state: string;
  status: string;
  outcome: "wait" | "reorder" | "purchased" | "checkout_declined" | "frequency_wait" | "blocked" | null;
  explanation: string | null;
  policy_version: string;
  days_until_stockout: string;
  projected_stockout_at: string;
  created_at: string;
  completed_at: string | null;
  steps: AgentStep[];
  offer_snapshots: OfferSnapshot[];
};

export type LedgerEvent = { id: string; event_type: string; title: string; detail: string; severity: "info" | "success" | "warning"; agent_run_id: string | null; supply_id: string | null; purchase_order_id: string | null; metadata_safe: Record<string, unknown>; read_at: string | null; created_at: string };

export type TransactionActivity = {
  id: string;
  occurred_at: string;
  beneficiary_name: string;
  supply_name: string;
  merchant_name: string;
  amount: string;
  currency: string;
  status: "approved" | "declined" | "pending";
  title: string;
  detail: string;
};
