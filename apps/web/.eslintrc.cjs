module.exports = {
  root: true,
  extends: ['next/core-web-vitals'],
  rules: {
    '@next/next/no-html-link-for-pages': 'off'
  },
  overrides: [
    {
      files: ['**/test-review.tsx', '**/test-review.ts'],
      rules: {
        'react-hooks/exhaustive-deps': 'off',
        '@next/next/no-img-element': 'off',
        'jsx-a11y/alt-text': 'off',
        'no-console': 'off',
        'react/no-danger': 'off'
      }
    }
  ]
};


