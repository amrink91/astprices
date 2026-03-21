"use client";

import { useEffect, useState } from "react";
import { use } from "react";
import { ArrowLeft, ShoppingCart, TrendingDown, ExternalLink } from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend,
} from "recharts";
import { getProduct, getPriceHistory, type ProductDetail } from "@/lib/api";

function formatPrice(p: number) {
  return new Intl.NumberFormat("ru-KZ", {
    style: "currency", currency: "KZT", maximumFractionDigits: 0,
  }).format(p);
}

const STORE_COLORS: Record<string, string> = {
  magnum: "#e63946", arbuz: "#2a9d8f", small: "#e9c46a",
  galmart: "#264653", astore: "#f4a261", anvar: "#8338ec",
};

export default function ProductPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [history, setHistory] = useState<{ recorded_at: string; price_tenge: number; store_name: string }[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([getProduct(id), getPriceHistory(id, 30)])
      .then(([p, h]) => { setProduct(p); setHistory(h); })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [id]);

  const addToCart = (productId: string, name: string, price: number) => {
    const cart = JSON.parse(localStorage.getItem("cart") || "[]");
    const exists = cart.find((i: { id: string }) => i.id === productId);
    if (!exists) {
      cart.push({ id: productId, canonical_name: name, quantity: 1, min_price: price });
      localStorage.setItem("cart", JSON.stringify(cart));
    }
    window.location.href = "/cart";
  };

  if (loading) return (
    <div className="min-h-screen bg-[#0f1423] flex items-center justify-center">
      <div className="text-gray-400 animate-pulse">Загрузка...</div>
    </div>
  );

  if (!product) return (
    <div className="min-h-screen bg-[#0f1423] flex items-center justify-center text-gray-400">
      Товар не найден
    </div>
  );

  // Группируем историю по магазинам для графика
  const stores = [...new Set(history.map(h => h.store_name))];
  const chartData = history
    .reduce((acc: Record<string, Record<string, number | string>>, h) => {
      const date = h.recorded_at.slice(0, 10);
      if (!acc[date]) acc[date] = { date };
      acc[date][h.store_name] = h.price_tenge;
      return acc;
    }, {});
  const chartArr = Object.values(chartData).sort((a, b) =>
    String(a.date).localeCompare(String(b.date))
  );

  return (
    <div className="min-h-screen bg-[#0f1423] pb-16">
      {/* Header */}
      <header className="sticky top-0 z-50 bg-[#0f1423]/90 backdrop-blur border-b border-[#2d3561]">
        <div className="max-w-4xl mx-auto px-4 py-3 flex items-center gap-4">
          <a href="/" className="text-gray-400 hover:text-white transition-colors">
            <ArrowLeft className="w-5 h-5" />
          </a>
          <h1 className="flex-1 text-sm font-medium text-white line-clamp-1">
            {product.canonical_name}
          </h1>
        </div>
      </header>

      <div className="max-w-4xl mx-auto px-4 pt-6 space-y-6">

        {/* Заголовок */}
        <div className="flex items-start gap-4">
          <span className="text-5xl">{product.category_emoji ?? "🛒"}</span>
          <div>
            <h1 className="text-2xl font-bold text-white">{product.canonical_name}</h1>
            {product.brand && <p className="text-gray-400 mt-0.5">{product.brand}</p>}
            {product.unit && (
              <p className="text-sm text-gray-500 mt-0.5">
                {product.unit}{product.unit_size ? ` × ${product.unit_size}` : ""}
              </p>
            )}
          </div>
        </div>

        {/* Кнопка корзины */}
        <button
          onClick={() => addToCart(product.id, product.canonical_name, product.min_price ?? 0)}
          className="flex items-center gap-2 bg-[#409cff] hover:bg-[#5aabff] text-white font-semibold px-6 py-3 rounded-xl transition-colors"
        >
          <ShoppingCart className="w-5 h-5" />
          Добавить в умную корзину
        </button>

        {/* Цены по магазинам */}
        <section>
          <h2 className="text-lg font-semibold text-white mb-3">Цены в магазинах</h2>
          <div className="space-y-2">
            {product.prices.map((p) => (
              <div
                key={p.store_slug}
                className="flex items-center justify-between bg-[#19203a] rounded-xl px-4 py-3 border border-[#2d3561]"
              >
                <div className="flex items-center gap-3">
                  <div
                    className="w-3 h-3 rounded-full"
                    style={{ background: STORE_COLORS[p.store_slug] ?? "#888" }}
                  />
                  <span className="text-white font-medium">{p.store_name}</span>
                  {p.is_promoted && (
                    <TrendingDown className="w-4 h-4 text-[#2ed573]" />
                  )}
                  {!p.in_stock && (
                    <span className="text-xs text-red-400 bg-red-400/10 px-2 py-0.5 rounded">
                      Нет в наличии
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-3">
                  {p.old_price_tenge && (
                    <span className="text-sm text-gray-400 line-through">
                      {formatPrice(p.old_price_tenge)}
                    </span>
                  )}
                  <span className="text-lg font-bold text-[#409cff]">
                    {formatPrice(p.price_tenge)}
                  </span>
                  {p.discount_pct != null && p.discount_pct >= 5 && (
                    <span className="bg-[#2ed573] text-black text-xs font-bold px-2 py-0.5 rounded-full">
                      −{Math.round(p.discount_pct)}%
                    </span>
                  )}
                  {p.store_url && (
                    <a
                      href={p.store_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-gray-400 hover:text-white transition-colors"
                    >
                      <ExternalLink className="w-4 h-4" />
                    </a>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* График истории цен */}
        {chartArr.length > 1 && (
          <section>
            <h2 className="text-lg font-semibold text-white mb-3">История цен (30 дней)</h2>
            <div className="bg-[#19203a] rounded-2xl p-4 border border-[#2d3561]">
              <ResponsiveContainer width="100%" height={280}>
                <LineChart data={chartArr}>
                  <XAxis
                    dataKey="date"
                    tick={{ fill: "#9ca3af", fontSize: 11 }}
                    tickFormatter={(v: string) => v.slice(5)}
                  />
                  <YAxis
                    tick={{ fill: "#9ca3af", fontSize: 11 }}
                    tickFormatter={(v: number) => `${Math.round(v / 1000)}k`}
                  />
                  <Tooltip
                    contentStyle={{ background: "#0f1423", border: "1px solid #2d3561", borderRadius: 8 }}
                    labelStyle={{ color: "#9ca3af" }}
                    formatter={(v: number) => [formatPrice(v), ""]}
                  />
                  <Legend
                    wrapperStyle={{ color: "#9ca3af", fontSize: 12 }}
                  />
                  {stores.map((store) => (
                    <Line
                      key={store}
                      type="monotone"
                      dataKey={store}
                      stroke={STORE_COLORS[store.toLowerCase()] ?? "#888"}
                      strokeWidth={2}
                      dot={false}
                      connectNulls
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </section>
        )}

      </div>
    </div>
  );
}
