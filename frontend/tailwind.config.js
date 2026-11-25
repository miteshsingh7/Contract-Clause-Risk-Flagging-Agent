/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        page: "#EFECE6",
        panel: "#F7F5F1",
        divider: "#D9D5CC",
        ink: "#22303C",
        subtle: "#6B7480",
        status: {
          acceptable: "#5E7A63",
          negotiation: "#9A7B2F",
          unacceptable: "#A4493D",
        },
      },
      fontFamily: {
        sans: ["Inter", "sans-serif"],
        serif: ['"Source Serif 4"', "Georgia", "serif"],
      },
      borderRadius: {
        custom: "6px",
      },
    },
  },
  plugins: [],
};
