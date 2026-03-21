import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin", "cyrillic"] });

export const metadata: Metadata = {
  title: "Astana Prices — сравнение цен на продукты в Астане",
  description:
    "Сравниваем цены в Magnum, Arbuz, Small, Galmart, A-Store и Анвар. " +
    "Умная корзина: купите дешевле, разделив список по магазинам.",
  keywords: "цены Астана, Magnum, Arbuz, продукты, сравнение цен, акции",
  openGraph: {
    title: "Astana Prices",
    description: "Сравнение цен на продукты в Астане",
    locale: "ru_KZ",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ru">
      <body className={inter.className}>{children}</body>
    </html>
  );
}
