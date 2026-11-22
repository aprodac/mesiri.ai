// MOB-06: the number in a spoken quantity. The speech step hands back English, written either way:
// "50 bags", "fifty bags", "one hundred and twenty", "two and a half", "1,200 kg", "1.5 lakh". Returns null when the
// words hold no number.

const SMALL: Record<string, number> = {
  zero: 0, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10,
  eleven: 11, twelve: 12, thirteen: 13, fourteen: 14, fifteen: 15, sixteen: 16, seventeen: 17, eighteen: 18,
  nineteen: 19, twenty: 20, thirty: 30, forty: 40, fifty: 50, sixty: 60, seventy: 70, eighty: 80, ninety: 90,
  a: 1, an: 1,
}
const SCALE: Record<string, number> = { hundred: 100, thousand: 1000, lakh: 100000, lakhs: 100000, lac: 100000, crore: 10000000 }

export function spokenNumber(words: string): number | null {
  const text = words.toLowerCase().replace(/,(?=\d{2,3}\b)/g, '').replace(/-/g, ' ')
  const digits = text.match(/\d+(?:\.\d+)?/)
  if (digits) {
    // "1.5 lakh", "2 thousand": a figure with a scale word after it.
    const after = text.slice((digits.index ?? 0) + digits[0].length).trim().split(/\s+/)[0] ?? ''
    return Number(digits[0]) * (SCALE[after] ?? 1)
  }
  let total = 0
  let current = 0
  let seen = false
  const tokens = text.split(/[^a-z]+/).filter(Boolean)
  for (let i = 0; i < tokens.length; i++) {
    const w = tokens[i]
    if (w === 'half' && seen) {
      current += 0.5 // "two and a half"
      continue
    }
    if (w in SMALL) {
      // "a"/"an" only count before a scale or "half" ("a hundred", "a half"), never as an article.
      if ((w === 'a' || w === 'an') && !(tokens[i + 1] in SCALE)) continue
      current += SMALL[w]
      seen = true
    } else if (w in SCALE && seen) {
      const scale = SCALE[w]
      if (scale === 100) current *= 100
      else {
        total += current * scale
        current = 0
      }
    } else if (w !== 'and' && seen && !(w in SCALE)) {
      break // the number has ended: "fifty bags"
    }
  }
  return seen ? total + current : null
}
