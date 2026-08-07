/** @type {import('tailwindcss').Config} */

/*
 * Tailwind consumes the CSS custom properties defined in src/styles/index.css.
 * Keeping the values there (rather than here) means light/dark swap in exactly
 * one place, and a component can never hard-code a hex that bypasses the
 * validated ramps.
 */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        surface: {
          page: 'var(--surface-page)',
          card: 'var(--surface-card)',
          raised: 'var(--surface-raised)',
          sunken: 'var(--surface-sunken)',
        },
        ink: {
          DEFAULT: 'var(--ink-primary)',
          primary: 'var(--ink-primary)',
          secondary: 'var(--ink-secondary)',
          muted: 'var(--ink-muted)',
          inverse: 'var(--ink-inverse)',
        },
        line: {
          DEFAULT: 'var(--line-hairline)',
          hairline: 'var(--line-hairline)',
          strong: 'var(--line-strong)',
        },
        // Policy-effect axis poles. NOT political sides.
        div: {
          'neg-4': 'var(--div-neg-4)',
          'neg-3': 'var(--div-neg-3)',
          'neg-2': 'var(--div-neg-2)',
          'neg-1': 'var(--div-neg-1)',
          mid: 'var(--div-mid)',
          'pos-1': 'var(--div-pos-1)',
          'pos-2': 'var(--div-pos-2)',
          'pos-3': 'var(--div-pos-3)',
          'pos-4': 'var(--div-pos-4)',
        },
        seq: {
          1: 'var(--seq-1)',
          2: 'var(--seq-2)',
          3: 'var(--seq-3)',
          4: 'var(--seq-4)',
        },
        status: {
          good: 'var(--status-good)',
          warning: 'var(--status-warning)',
          serious: 'var(--status-serious)',
          critical: 'var(--status-critical)',
          neutral: 'var(--status-neutral)',
        },
        cat: {
          1: 'var(--cat-1)',
          2: 'var(--cat-2)',
          3: 'var(--cat-3)',
          4: 'var(--cat-4)',
          5: 'var(--cat-5)',
          6: 'var(--cat-6)',
          7: 'var(--cat-7)',
          8: 'var(--cat-8)',
        },
        grid: 'var(--grid-line)',
        axis: 'var(--axis-line)',
      },
      fontFamily: {
        sans: ['system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      fontSize: {
        // A restrained type scale — large whitespace, strong hierarchy.
        micro: ['0.6875rem', { lineHeight: '1rem', letterSpacing: '0.04em' }],
        caption: ['0.75rem', { lineHeight: '1.125rem' }],
        body: ['0.9375rem', { lineHeight: '1.6' }],
        lede: ['1.0625rem', { lineHeight: '1.65' }],
        display: ['clamp(2.25rem, 5vw, 3.75rem)', { lineHeight: '1.05', letterSpacing: '-0.03em' }],
        title: ['clamp(1.5rem, 3vw, 2.25rem)', { lineHeight: '1.15', letterSpacing: '-0.02em' }],
      },
      maxWidth: {
        prose: '68ch',
        shell: '80rem',
      },
      borderRadius: {
        // 4px rounded data-ends; everything else stays close to square.
        data: '4px',
      },
      transitionTimingFunction: {
        subtle: 'cubic-bezier(0.22, 1, 0.36, 1)',
      },
      keyframes: {
        'fade-up': {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        shimmer: {
          '100%': { transform: 'translateX(100%)' },
        },
      },
      animation: {
        'fade-up': 'fade-up 0.4s cubic-bezier(0.22, 1, 0.36, 1) both',
        shimmer: 'shimmer 1.6s infinite',
      },
    },
  },
  plugins: [],
}
