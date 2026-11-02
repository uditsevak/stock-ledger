/** Rebuild CSS after changing classes:  npx tailwindcss@3 -i styles/input.css -o static/app.css --minify */
module.exports = {
  content: ['./static/index.html', './static/app.js'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'Helvetica Neue', 'Arial', 'sans-serif'],
      },
      // Warm neutrals plus one muted colour per entry type. Colour marks the kind of entry;
      // it is never a whole block, so screens stay calm and the numbers stand out.
      colors: {
        paper: '#f5f4f1',                                   // page background
        ink: { DEFAULT: '#1c1917', soft: '#292524' },       // text, primary buttons, selected options
        copper: { 400: '#d08a5c', 500: '#b8693c', 600: '#9c5530' }, // brand mark only
        moss:  { 50: '#eff5f1', 100: '#dcebe1', 200: '#c3dccb', 600: '#2f6b4f', 700: '#275a42', 800: '#1f4835' }, // Purchase In, + qty
        ochre: { 50: '#fbf4e8', 100: '#f5e6cb', 200: '#ead1a6', 600: '#a2610f', 700: '#86500d', 800: '#6b400c' }, // Labour Out, warnings
        steel: { 50: '#eff3f7', 100: '#dce6ef', 200: '#c3d4e4', 600: '#2f5f86', 700: '#284f70', 800: '#20405b' }, // Labour In, pending
        brick: { 50: '#fbf0ee', 100: '#f4dcd8', 200: '#e9c2bc', 600: '#a3372c', 700: '#882d24', 800: '#6e251e' }, // Sale Out, − qty, errors
      },
      boxShadow: {
        hair: '0 1px 0 rgba(28,25,23,.04), 0 1px 2px rgba(28,25,23,.04)',
        lift: '0 1px 2px rgba(28,25,23,.06), 0 8px 24px -8px rgba(28,25,23,.12)',
        sheet: '0 -8px 40px -12px rgba(28,25,23,.25)',
      },
    },
  },
};
