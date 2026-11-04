export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: { canvas: "var(--page)", surface: "var(--panel)", ink: "var(--text)", brand: "var(--accent)" },
      fontFamily: { sans: ["var(--font-sans)"] },
      borderRadius: { surface: "var(--radius)" },
    },
  },
  plugins: [],
};
