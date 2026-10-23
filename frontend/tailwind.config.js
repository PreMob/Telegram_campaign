/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#1c1915",
        paper: "#f3efe6",
        panel: "#fffdf8",
        line: "#e3dac8",
        pine: "#1f6f5b",
        copper: "#9a5b32",
        moss: "#2f6b4f",
        clay: "#8f3d3d",
      },
      fontFamily: {
        sans: ["var(--font-outfit)", "Segoe UI", "sans-serif"],
        display: ["var(--font-fraunces)", "Georgia", "serif"],
      },
    },
  },
  plugins: [],
};
