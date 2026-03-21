"use client";

import { useState, useEffect, useCallback } from "react";
import { Search, ShoppingCart, TrendingDown, Store } from "lucide-react";
import { getProducts, getCategories, type ProductListItem, type Category } from "@/lib/api";

const STORE_COLORS: Record<string, string> = {
  magnum: "#e63946",
  arbuz:  "#2a9d8f",
  small:  "#e9c46a",
  galmart:"#264653",
  astore: "#f4a261",
  anvar:  "#8338ec",
};

function formatPrice(p: number) {
  return new Intl.NumberFormat("ru-KZ", {
    style: "currency",
    currency: "KZT",
    maximumFractionDigits: 0,
  }).format(p);
}

function ProductCard({ product }: { product: ProductListItem }) {
  return (
    <a
      href={`/product/${product.id}`}
      className="block bg-[#19203a] rounded-2xl p-4 hover:bg-[#1f2a47] transition-colors border border-[#2d3561] hover:border-[#409cff]/50"
    >
      <div className="flex items-start gap-3">
        <span className="text-3xl">{product.category_emoji ?? "🛒"}</span>
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-sm leading-snug line-clamp-2 text-white">
            {product.canonical_name}
          </h3>
          {product.brand && (
            <p className="text-xs text-gray-400 mt-0.5">{product.brand}</p>
          )}
        </div>
      </div>

      <div className="mt-3 flex items-end justify-between">
        <div>
          {product.min_price != null && (
            <p className="text-lg font-bold text-[#409cff]">
              {formatPrice(product.min_price)}
            </p>
          )}
          {product.best_store && (
            <p className="text-xs text-gray-400">{product.best_store}</p>
          )}
        </div>
        {product.discount_pct != null && product.discount_pct >= 5 && (
          <span className="bg-[#2ed573] text-black text-xs font-bold px-2 py-0.5 rounded-full">
            −{Math.round(product.discount_pct)}%
          </span>
        )}
      </div>

      {!product.in_stock && (
        <p className="text-xs text-red-400 mt-1">Нет в наличии</p>
      )}
    </a>
  );
}

export default function HomePage() {
  const [products, setProducts] = useState<ProductListItem[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [selectedCat, setSelectedCat] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [showPromo, setShowPromo] = useState(false);

  const fetchProducts = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getProducts({
        category: selectedCat ?? undefined,
        search: searchQuery || undefined,
        promoted: showPromo || undefined,
        limit: 48,
      });
      setProducts(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [selectedCat, searchQuery, showPromo]);

  useEffect(() => {
    getCategories().then(setCategories).catch(console.error);
  }, []);

  useEffect(() => {
    const t = setTimeout(fetchProducts, 300);
    return () => clearTimeout(t);
  }, [fetchProducts]);

  const rootCats = categories.filter((c) => !c.parent_id);

  return (
    <div className="min-h-screen">
      {/* Header */}
      <header className="sticky top-0 z-50 bg-[#0f1423]/90 backdrop-blur border-b border-[#2d3561]">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center gap-4">
          <a href="/" className="text-xl font-bold text-white whitespace-nowrap">
            🛒 <span className="text-[#409cff]">Astana</span> Prices
          </a>

          {/* Поиск */}
          <div className="flex-1 relative max-w-lg">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 w-4 h-4" />
            <input
              type="text"
              placeholder="Поиск товаров..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-[#19203a] border border-[#2d3561] rounded-xl pl-9 pr-4 py-2 text-sm text-white placeholder-gray-400 focus:outline-none focus:border-[#409cff]"
            />
          </div>

          <a
            href="/cart"
            className="flex items-center gap-2 bg-[#409cff] hover:bg-[#5aabff] text-white text-sm font-semibold px-4 py-2 rounded-xl transition-colors"
          >
            <ShoppingCart className="w-4 h-4" />
            Корзина
          </a>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-4 py-6 flex gap-6">
        {/* Sidebar — категории */}
        <aside className="hidden lg:block w-52 shrink-0">
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
            Категории
          </h2>
          <nav className="flex flex-col gap-1">
            <button
              onClick={() => setSelectedCat(null)}
              className={`text-left px-3 py-2 rounded-lg text-sm transition-colors ${
                selectedCat === null
                  ? "bg-[#409cff]/20 text-[#409cff] font-semibold"
                  : "text-gray-300 hover:bg-[#19203a]"
              }`}
            >
              🏪 Все товары
            </button>
            {rootCats.map((cat) => (
              <button
                key={cat.id}
                onClick={() => setSelectedCat(cat.slug)}
                className={`text-left px-3 py-2 rounded-lg text-sm transition-colors ${
                  selectedCat === cat.slug
                    ? "bg-[#409cff]/20 text-[#409cff] font-semibold"
                    : "text-gray-300 hover:bg-[#19203a]"
                }`}
              >
                {cat.icon_emoji} {cat.name}
              </button>
            ))}
          </nav>

          {/* Фильтр акций */}
          <div className="mt-6 pt-4 border-t border-[#2d3561]">
            <button
              onClick={() => setShowPromo(!showPromo)}
              className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
                showPromo
                  ? "bg-[#2ed573]/20 text-[#2ed573] font-semibold"
                  : "text-gray-300 hover:bg-[#19203a]"
              }`}
            >
              <TrendingDown className="w-4 h-4" />
              Только акции
            </button>
          </div>

          {/* Ссылка на магазины */}
          <a
            href="/stores"
            className="mt-4 flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-gray-300 hover:bg-[#19203a] transition-colors"
          >
            <Store className="w-4 h-4" />
            Магазины
          </a>
        </aside>

        {/* Основной контент */}
        <main className="flex-1 min-w-0">
          {/* Мобильные фильтры */}
          <div className="lg:hidden flex gap-2 mb-4 overflow-x-auto pb-1">
            <button
              onClick={() => setSelectedCat(null)}
              className={`shrink-0 px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
                selectedCat === null
                  ? "bg-[#409cff] text-white"
                  : "bg-[#19203a] text-gray-300"
              }`}
            >
              Все
            </button>
            {rootCats.map((cat) => (
              <button
                key={cat.id}
                onClick={() => setSelectedCat(cat.slug)}
                className={`shrink-0 px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
                  selectedCat === cat.slug
                    ? "bg-[#409cff] text-white"
                    : "bg-[#19203a] text-gray-300"
                }`}
              >
                {cat.icon_emoji} {cat.name}
              </button>
            ))}
          </div>

          {/* Результаты */}
          {loading ? (
            <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-4 gap-3">
              {Array.from({ length: 12 }).map((_, i) => (
                <div
                  key={i}
                  className="bg-[#19203a] rounded-2xl p-4 h-36 animate-pulse"
                />
              ))}
            </div>
          ) : products.length === 0 ? (
            <div className="text-center py-20 text-gray-400">
              <p className="text-4xl mb-3">🔍</p>
              <p className="text-lg">Товары не найдены</p>
              <p className="text-sm mt-1">Попробуйте другой поиск или категорию</p>
            </div>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-4 gap-3">
              {products.map((p) => (
                <ProductCard key={p.id} product={p} />
              ))}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
