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
};

export type EquivalenceSet = { id: string; name: string; notes: string | null; approved_variants: Variant[] };

export type Supply = {
  id: string;
  name: string;
  unit: string;
  daily_consumption: string;
  quantity_on_hand: string;
  safety_buffer_quantity: string;
  is_enabled: boolean;
  equivalence_sets: EquivalenceSet[];
};

export type Beneficiary = {
  id: string;
  name: string;
  relationship_label: string;
  is_active: boolean;
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
  mandate_synced_at: string | null;
};

export type Dashboard = { beneficiaries: Beneficiary[]; merchant_authorizations: MerchantAuthorization[] };

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
  outcome: "wait" | "reorder" | "sandbox_settled" | "blocked" | null;
  explanation: string | null;
  policy_version: string;
  days_until_stockout: string;
  projected_stockout_at: string;
  created_at: string;
  completed_at: string | null;
  steps: AgentStep[];
  offer_snapshots: OfferSnapshot[];
};
