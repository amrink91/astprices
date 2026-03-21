"use client";

import { useState, useEffect } from "react";
import { ArrowLeft, Trash2, ShoppingBag, Zap, ExternalLink } from "lucide-react";
import { optimizeCart, type CartResponse } from "@/lib/api";

interface CartItem {
  id: string;
  canonical_name: string;
  quantity: number;
  min_price: number;
}

function formatPrice(p: number) {
  return new Intl.NumberFormat("ru-KZ", {
    style: "currency", currency: "KZT", maximumFractionDigits: 0,
  }).format(p);
}

const STORE_COLORS: Record<string, string> = {
  magnum: "#e63946", arbuz: "#2a9d8f", small: "#e9c46a",
  galmart: "#264653", astore: "#f4a261", anvar: "#8338ec",
};

export default function CartPage() {
  const [cart, setCart] = useState<CartItem[]>([]);
  const [result, setResult] = useState<CartResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const saved = JSON.parse(localStorage.getItem("cart") || "[]");
    setCart(saved);
  }, []);

  const removeItem = (id: string) => {
    const updated = cart.filter((i) => i.id !== id);
    setCart(updated);
    localStorage.setItem("cart", JSON.stringify(updated));
  };

  const updateQty = (id: string, qty: number) => {
    if (qty < 1) return removeItem(id);
    const updated = cart.map((i) => i.id === id ? { ...i, quantity: qty } : i);
    setCart(updated);
    localStorage.setItem("cart", JSON.stringify(updated));
  };

  const optimize = async () => {
    if (cart.length === 0) return;
    setLoading(true);
    setError(null);
    try {
      const res = await optimizeCart({
        items: cart.map((i) => ({
          product_id: i.id,
          quantity: i.quantity,
          canonical_name: i.canonical_name,
        })),
        max_stores: 3,
      });
      setResult(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Ошибка оптимизации");
    } finally {
      setLoading(false);
    }
  };

  const naiveTotal = cart.reduce((s, i) => s + i.min_price * i.quantity, 0);

  return (
    <div className="min-h-screen bg-[#0f1423] pb-16">
      <header className="sticky top-0 z-50 bg-[#0f1423]/90 backdrop-blur border-b border-[#2d3561]">
        <div className="max-w-4xl mx-auto px-4 py-3 flex items-center gap-4">
          <a href="/" className="text-gray-400 hover:text-white transition-colors">
            <ArrowLeft className="w-5 h-5" />
          </a>
          <h1 className="text-lg font-semibold text-white">
            🛒 Умная корзина ({cart.length})
          </h1>
        </div>
      </header>

      <div className="max-w-4xl mx-auto px-4 pt-6 space-y-6">

        {/* Список товаров */}
        {cart.length === 0 ? (
          <div className="text-center py-20 text-gray-400">
            <ShoppingBag className="w-12 h-12 mx-auto mb-3 opacity-30" />
            <p className="text-lg">Корзина пуста</p>
            <a href="/" className="mt-3 inline-block text-[#409cff] hover:underline text-sm">
              Перейти к каталогу
            </a>
          </div>
        ) : (
          <>
            <section className="space-y-2">
              {cart.map((item) => (
                <div
                  key={item.id}
                  className="flex items-center gap-4 bg-[#19203a] rounded-xl px-4 py-3 border border-[#2d3561]"
                >
                  <div className="flex-1 min-w-0">
                    <p className="text-white text-sm font-medium line-clamp-1">
                      {item.canonical_name}
                    </p>
                    <p className="text-gray-400 text-xs mt-0.5">
                      {formatPrice(item.min_price)} × {item.quantity} = {formatPrice(item.min_price * item.quantity)}
                    </p>
                  </div>

                  {/* Количество */}
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => updateQty(item.id, item.quantity - 1)}
                      className="w-7 h-7 rounded-lg bg-[#2d3561] text-white hover:bg-[#3d4571] transition-colors text-sm font-bold"
                    >
                      −
                    </button>
                    <span className="w-6 text-center text-white text-sm">{item.quantity}</span>
                    <button
                      onClick={() => updateQty(item.id, item.quantity + 1)}
                      className="w-7 h-7 rounded-lg bg-[#2d3561] text-white hover:bg-[#3d4571] transition-colors text-sm font-bold"
                    >
                      +
                    </button>
                  </div>

                  <button
                    onClick={() => removeItem(item.id)}
                    className="text-gray-500 hover:text-red-400 transition-colors"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </section>

            {/* Итог и кнопка */}
            <div className="bg-[#19203a] rounded-2xl p-5 border border-[#2d3561]">
              <div className="flex justify-between mb-4">
                <span className="text-gray-400">Итого (без оптимизации):</span>
                <span className="text-white font-semibold">{formatPrice(naiveTotal)}</span>
              </div>

              {result && (
                <div className="mb-4 p-3 bg-[#2ed573]/10 rounded-xl border border-[#2ed573]/30">
                  <p className="text-[#2ed573] font-semibold">
                    💰 Экономия: {formatPrice(result.savings)} ({result.savings_pct}%)
                  </p>
                  <p className="text-white text-sm mt-1">
                    Итого с доставкой: {formatPrice(result.grand_total)}
                  </p>
                </div>
              )}

              <button
                onClick={optimize}
                disabled={loading || cart.length === 0}
                className="w-full flex items-center justify-center gap-2 bg-[#409cff] hover:bg-[#5aabff] disabled:opacity-50 text-white font-semibold py-3 rounded-xl transition-colors"
              >
                <Zap className="w-5 h-5" />
                {loading ? "Оптимизирую..." : "Оптимизировать корзину"}
              </button>

              {error && (
                <p className="text-red-400 text-sm mt-2 text-center">{error}</p>
              )}
            </div>

            {/* Результат оптимизации */}
            {result && (
              <section className="space-y-4">
                <h2 className="text-lg font-semibold text-white">
                  Разбивка по магазинам
                </h2>
                {result.assignments.map((a) => (
                  <div
                    key={a.store_slug}
                    className="bg-[#19203a] rounded-2xl p-5 border border-[#2d3561]"
                    style={{ borderLeftColor: STORE_COLORS[a.store_slug] ?? "#888", borderLeftWidth: 4 }}
                  >
                    <div className="flex items-center justify-between mb-3">
                      <h3 className="text-white font-semibold text-lg">{a.store_name}</h3>
                      <div className="text-right">
                        <p className="text-[#409cff] font-bold">{formatPrice(a.total)}</p>
                        {a.delivery_cost > 0 ? (
                          <p className="text-xs text-gray-400">доставка: {formatPrice(a.delivery_cost)}</p>
                        ) : (
                          <p className="text-xs text-[#2ed573]">доставка бесплатно</p>
                        )}
                      </div>
                    </div>

                    <div className="space-y-1.5 mb-4">
                      {a.items.map((item) => (
                        <div key={item.product_id} className="flex justify-between text-sm">
                          <span className="text-gray-300 line-clamp-1 flex-1">
                            {item.canonical_name} × {item.quantity}
                          </span>
                          <span className="text-white ml-3 shrink-0">
                            {formatPrice(item.total_price)}
                          </span>
                        </div>
                      ))}
                    </div>

                    {a.checkout_url && (
                      <a
                        href={a.checkout_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center justify-center gap-2 bg-[#409cff] hover:bg-[#5aabff] text-white text-sm font-semibold py-2.5 rounded-xl transition-colors w-full"
                      >
                        <ExternalLink className="w-4 h-4" />
                        Открыть корзину в {a.store_name}
                      </a>
                    )}
                  </div>
                ))}

                {result.not_found.length > 0 && (
                  <div className="bg-yellow-500/10 rounded-xl p-4 border border-yellow-500/20">
                    <p className="text-yellow-400 text-sm font-medium">
                      ⚠️ Не найдены в магазинах:
                    </p>
                    <ul className="mt-2 space-y-1">
                      {result.not_found.map((n) => (
                        <li key={n} className="text-gray-300 text-sm">• {n}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </section>
            )}
          </>
        )}
      </div>
    </div>
  );
}
