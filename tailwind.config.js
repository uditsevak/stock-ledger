/** Rebuild CSS after changing classes:  npx tailwindcss@3 -i styles/input.css -o static/app.css --minify */
module.exports = {
  content: ['./static/index.html', './static/app.js'],
  theme: { extend: {} },
};
