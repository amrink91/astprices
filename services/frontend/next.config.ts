import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "magnum.kz" },
      { protocol: "https", hostname: "arbuz.kz" },
      { protocol: "https", hostname: "small.kz" },
      { protocol: "https", hostname: "galmart.kz" },
      { protocol: "https", hostname: "astore.kz" },
      { protocol: "https", hostname: "anvar.kz" },
      { protocol: "https", hostname: "*.galmart.kz" },
    ],
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_URL}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
