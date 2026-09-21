import type { NextConfig } from 'next';
const config: NextConfig = {
  typescript: { tsconfigPath: 'tsconfig.next.json' },
  distDir: '.next-native',
  poweredByHeader: false,
};
export default config;
