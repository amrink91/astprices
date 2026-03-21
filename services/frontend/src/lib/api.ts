/**
 * API клиент — обёртка над fetch для Astana Prices.
 */

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

export interface ProductListItem {
  id: string;
  canonical_name: string;
  brand?: string;
  category_emoji?: string;
  min_price?: number;
  best_store?: string;
  discount_pct?: number;
  in_stock: boolean;
}

export interface PricePoint {
  store_name: string;
  store_slug: string;
  price_tenge: number;
  old_price_tenge?: number;
  discount_pct?: number;
  in_stock: boolean;
  is_promoted: boolean;
  store_url?: string;
  store_image_url?: string;
}

export interface ProductDetail extends ProductListItem {
  unit?: string;
  unit_size?: number;
  category_slug?: string;
  category_name?: string;
  prices: PricePoint[];
  min_price?: number;
  max_price?: number;
}

export interface Category {
  id: string;
  slug: string;
  name: string;
  icon_emoji?: string;
  parent_id?: string;
  sort_order: number;
}

export interface Store {
  id: string;
  slug: string;
  display_name: string;
  logo_url?: string;
  delivery_cost_tenge?: number;
  delivery_free_threshold?: number;
  min_order_tenge?: number;
  avg_delivery_minutes?: number;
  scrape_health_score: number;
  products_count?: number;
}

export interface CartOptimizeRequest {
  items: { product_id: string; quantity: number; canonical_name: string }[];
  max_stores?: number;
}

export interface CartResponse {
  assignments: {
    store_slug: string;
    store_name: string;
    items: { product_id: string; canonical_name: string; quantity: number; unit_price: number; total_price: number; store_url?: string }[];
    items_subtotal: number;
    delivery_cost: number;
    total: number;
    checkout_url?: string;
  }[];
  grand_total: number;
  baseline_total: number;
  savings: number;
  savings_pct: number;
  strategy: string;
  not_found: string[];
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`API ${res.status}: ${err}`);
  }
  return res.json();
}

// ── Products ────────────────────────────────────────────────────
export const getProducts = (params?: {
  category?: string;
  search?: string;
  store?: string;
  promoted?: boolean;
  limit?: number;
  offset?: number;
}) => {
  const qs = new URLSearchParams();
  if (params?.category) qs.set("category", params.category);
  if (params?.search)   qs.set("search", params.search);
  if (params?.store)    qs.set("store", params.store);
  if (params?.promoted) qs.set("promoted", "true");
  if (params?.limit)    qs.set("limit", String(params.limit));
  if (params?.offset)   qs.set("offset", String(params.offset));
  return apiFetch<ProductListItem[]>(`/api/v1/products?${qs}`);
};

export const searchProducts = (q: string, limit = 20) =>
  apiFetch<ProductListItem[]>(`/api/v1/products/search?q=${encodeURIComponent(q)}&limit=${limit}`);

export const getProduct = (id: string) =>
  apiFetch<ProductDetail>(`/api/v1/products/${id}`);

export const getPriceHistory = (id: string, days = 30, store?: string) => {
  const qs = new URLSearchParams({ days: String(days) });
  if (store) qs.set("store", store);
  return apiFetch<{ recorded_at: string; price_tenge: number; store_name: string }[]>(
    `/api/v1/products/${id}/history?${qs}`
  );
};

// ── Categories ──────────────────────────────────────────────────
export const getCategories = () =>
  apiFetch<Category[]>("/api/v1/categories");

// ── Stores ──────────────────────────────────────────────────────
export const getStores = () =>
  apiFetch<Store[]>("/api/v1/stores");

// ── Cart ────────────────────────────────────────────────────────
export const optimizeCart = (req: CartOptimizeRequest) =>
  apiFetch<CartResponse>("/api/v1/cart/optimize", {
    method: "POST",
    body: JSON.stringify(req),
  });

// ── Auth ────────────────────────────────────────────────────────
export const telegramLogin = (data: Record<string, string | number>) =>
  apiFetch<{ access_token: string; user_id: string; username?: string }>(
    "/api/v1/auth/telegram",
    { method: "POST", body: JSON.stringify(data) }
  );
