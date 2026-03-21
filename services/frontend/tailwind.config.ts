import type { Config } from "tailwindcss";

export default {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        bg:     "#0f1423",
        card:   "#19203a",
        accent: "#409cff",
        green:  "#2ed573",
        red:    "#ff4757",
      },
    },
  },
  plugins: [],
} satisfies Config;
