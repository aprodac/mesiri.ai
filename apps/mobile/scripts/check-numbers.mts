// MOB-06: the spoken-quantity reader against the ways the speech step writes numbers. Run: pnpm check
import { spokenNumber } from '../src/lib/numbers.ts'
const cases: [string, number | null][] = [
  ['Fifty bags', 50], ['50 bags', 50], ['one hundred and twenty bags', 120], ['two and a half cum', 2.5],
  ['1,200 kg', 1200], ['1.5 lakh', 150000], ['a hundred nos', 100], ['twenty-five', 25], ['three thousand four hundred', 3400],
  ['eight helpers', 8], ['a bag of cement', null], ['no number here', null], ['Seventy five bags of cement came', 75], ['zero', 0],
]
let bad = 0
for (const [w, want] of cases) { const got = spokenNumber(w); if (got !== want) { bad++; console.log('FAIL', w, got, want) } }
console.log(bad ? `${bad} failed` : `all ${cases.length} passed`)
if (bad) process.exit(1)
