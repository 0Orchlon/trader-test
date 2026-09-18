/**
 * ESLint flat config.
 *
 * Гол дүрэм: **мөнгөн талбарт `Number(...)` хоригтой** (AC-25-ийн frontend
 * тал). Fixed-point тэмдэгт мөрийг float болгох нь тоймлолтыг чимээгүй
 * алдагдуулна — `lib/money.ts` нь тэмдэгт мөрөөр ажилладаг цорын ганц газар.
 */
import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';

export default tseslint.config(
  { ignores: ['dist', 'src/lib/api.generated.ts'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    plugins: { 'react-hooks': reactHooks },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      '@typescript-eslint/no-explicit-any': 'error',
      // `_`-ээр эхэлсэн нэр = ЗОРИУДААР ашиглаагүй (гэрээний гарын үсэг).
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      'no-restricted-syntax': [
        'error',
        {
          selector: "CallExpression[callee.name='Number']",
          message: 'Мөнгөн талбарт Number() хоригтой — lib/money.ts ашигла (AC-25).',
        },
        {
          selector: "CallExpression[callee.name='parseFloat']",
          message: 'parseFloat нь мөнгийг float болгоно — lib/money.ts ашигла (AC-25).',
        },
      ],
    },
  },
  {
    // `money.ts` нь хилийн хэрэгжүүлэлт; тест нь дүрмийг өөрийг нь шалгана.
    files: ['src/lib/money.ts', 'src/**/*.test.ts', 'src/**/*.test.tsx'],
    rules: { 'no-restricted-syntax': 'off' },
  },
);
