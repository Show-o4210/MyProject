module.exports = {
  content: ['./templates/**/*.html', './static/js/**/*.js'],
  theme: {extend: {
    fontFamily: {sans: ['"Plus Jakarta Sans"', 'Inter', 'system-ui', 'sans-serif']},
    colors: {brand: {50:'#eef4ff',100:'#d9e6ff',500:'#3b6ff5',600:'#2558eb',700:'#1d47d8'}},
    boxShadow: {soft:'0 2px 16px -2px rgba(15, 23, 42, 0.08)','soft-lg':'0 8px 32px -4px rgba(15, 23, 42, 0.12)',glow:'0 0 40px -8px rgba(59, 111, 245, 0.35)'}
  }}
};
