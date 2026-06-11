/** @type {import('next').NextConfig} */
const API = process.env.VFIED_API || "http://localhost:8000";

module.exports = {
  async rewrites() {
    // Proxy /api/* to the FastAPI backend so the browser talks same-origin.
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
};
