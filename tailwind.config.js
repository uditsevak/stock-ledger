/** Rebuild CSS after changing classes:  npx tailwindcss@3 -i styles/input.css -o static/app.css --minify */
module.exports = {
  content: ['./static/index.html', './static/app.js'],
  theme: {
    extend: {
      fontFamily: {
        // Geist is bundled in static/vendor/geist so phones without it still get the same look.
        sans: ['Geist', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'Helvetica Neue', 'Arial', 'sans-serif'],
      },
      colors: {
        paper: '#fafafa',   // page background (phone) / content panel (desktop)
        ink: '#09090b',     // text, primary buttons, selected options
      },
      boxShadow: {
        hair: '0 1px 2px rgba(9,9,11,.05)',
        card: '0 1px 2px rgba(9,9,11,.04), 0 2px 8px -2px rgba(9,9,11,.05)',
        lift: '0 2px 4px rgba(9,9,11,.04), 0 12px 32px -8px rgba(9,9,11,.14)',
        sheet: '0 -12px 48px -12px rgba(9,9,11,.28)',
        glow: 'inset 0 1px 0 rgba(255,255,255,.28), 0 1px 2px rgba(9,9,11,.12)',
      },
    },
  },
};
