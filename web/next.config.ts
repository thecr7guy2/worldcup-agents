import type { NextConfig } from "next";

// The API runs as a separate uvicorn process. The browser sees one origin: requests
// to /api/* are proxied to it. Override with API_PROXY in production if needed.
const API_PROXY = process.env.API_PROXY ?? "http://127.0.0.1:8001";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_PROXY}/api/:path*` }];
  },
};

export default nextConfig;
