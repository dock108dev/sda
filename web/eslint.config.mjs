import nextConfig from "eslint-config-next";

const config = [
  {
    ignores: ["coverage/**", ".next/**", "out/**", "node_modules/**"],
  },
  ...nextConfig,
  {
    rules: {
      "react-hooks/set-state-in-effect": "off",
    },
  },
];

export default config;
