/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#EEF1F4",
        sheet: "#FFFFFF",
        ink: "#1B2430",
        graphite: "#5B6675",
        rule: "#CBD3DC",
        highlight: "#F2D64B",
        "highlight-soft": "#FBF1C2",
        cobalt: "#2F6FDE",
        "cobalt-soft": "#E3ECFB",
        forget: "#C2412D",
        "forget-soft": "#F8E3DF",
        moss: "#3C7A55",
      },
      fontFamily: {
        sans: ['"Atkinson Hyperlegible"', "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        serif: ['"Source Serif 4"', "Georgia", "serif"],
      },
      fontSize: { xs: ["0.75rem", "1.1rem"], sm: ["0.875rem", "1.35rem"] },
    },
  },
  plugins: [],
};
