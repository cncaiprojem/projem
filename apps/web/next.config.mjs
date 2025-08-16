/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Enterprise Docker optimization: Standalone output for minimal production image
  output: 'standalone',
  experimental: {
    typedRoutes: true,
  },
  eslint: {
    // CI/prod build sırasında eslint hataları nedeniyle derlemeyi durdurma
    ignoreDuringBuilds: false,
  },
  typescript: {
    // Strict mode enforced
    ignoreBuildErrors: false,
  },
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          {
            key: 'X-DNS-Prefetch-Control',
            value: 'on'
          },
          {
            key: 'Strict-Transport-Security',
            value: 'max-age=63072000; includeSubDomains; preload'
          },
          {
            key: 'X-Frame-Options',
            value: 'SAMEORIGIN'
          },
          {
            key: 'X-Content-Type-Options',
            value: 'nosniff'
          },
          {
            key: 'Referrer-Policy',
            value: 'origin-when-cross-origin'
          },
          {
            // Content Security Policy - Production güvenliği artırıldı
            key: 'Content-Security-Policy',
            value: process.env.NODE_ENV === 'production' 
              ? "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob: https://cdn.jsdelivr.net https://fonts.gstatic.com https://images.unsplash.com; font-src 'self' data: https://fonts.gstatic.com; connect-src 'self' https://*.projem.com wss://*.projem.com; frame-ancestors 'none'; base-uri 'self'; form-action 'self';"
              : "default-src 'self'; script-src 'self' 'unsafe-eval' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; font-src 'self' data:; connect-src 'self' http://localhost:* ws://localhost:* wss://localhost:*;"
          },
        ],
      },
      {
        source: '/healthz',
        headers: [
          {
            key: 'Cache-Control',
            value: 'no-store, no-cache, must-revalidate, proxy-revalidate'
          },
        ],
      },
    ]
  },
  webpack: (config, { dev }) => {
    // Geliştirmede dosya sistemi cache'ini kapat (Docker volume üzerinde rename hatalarını azaltır)
    if (dev) {
      config.cache = false;
    }
    return config;
  }
};

export default nextConfig;


