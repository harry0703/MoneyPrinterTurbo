import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  async rewrites() {
    return [{
      source: "/api/:path*",
      destination: "http://127.0.0.1:8080/api/v1/:path*",
    }];
  },
};

export default nextConfig;
