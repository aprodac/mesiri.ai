// SS-33 (guided-onboarding-plan.md 6.5): construction and Mesiri words in one plain sentence each, for people who
// don't know them. Definitions follow the team's field guides (docs/learning/src, LRN): change a meaning there and
// here together. `match` lists the spellings found in page text; the first is the one shown as the heading.
//
// withTerms() (components/term.tsx) finds these words in any help text, so a new page's `about` gets its words
// explained with no extra work.

export interface GlossaryTerm {
  /** Words that mean this term in text, most specific first ("RA bill" before "bill"). Matched whole, any case. */
  match: string[]
  /** What it is, in one plain sentence. */
  meaning: string
  /** A real example, when it helps. */
  example?: string
}

export const GLOSSARY: GlossaryTerm[] = [
  { match: ['DPR', 'daily progress report', 'daily report'], meaning: "A site's day on one page: who came, what work was done, what material came or ran out, what is stuck.", example: 'Mesiri makes it every evening from the WhatsApp updates.' },
  { match: ['BOQ', 'bill of quantities'], meaning: "Every work item of the project with its quantity and rate: the project's price and its budget.", example: 'PCC 1:4:8, 42 cum at ₹5,800.' },
  { match: ['estimate'], meaning: 'The expected quantities and cost of the work, before or alongside the BOQ.' },
  { match: ['RA bill', 'running-account bill', 'running account bill'], meaning: 'A stage bill to the client for the work measured so far.', example: 'RA-03: ground-floor slab and brickwork, ₹8.4 L.' },
  { match: ['GRN', 'goods receipt note', 'MRN'], meaning: 'The record of material accepted at site: what came, how much, from whom.' },
  { match: ['PO', 'purchase order'], meaning: 'The order to a supplier: item, quantity, rate, GST and delivery date.' },
  { match: ['indent', 'requisition', 'material request'], meaning: 'A request from site for material, with the quantity and the date it is needed.' },
  { match: ['delivery challan', 'challan'], meaning: "The supplier's delivery note that comes with the lorry." },
  { match: ['opening stock'], meaning: 'What a site had on hand when you started counting in Mesiri.' },
  { match: ['stock register', 'bin card'], meaning: 'The running record of what came in, what went out, and what is left, per item.' },
  { match: ['issue slip', 'material issue'], meaning: 'The record of material given from the store to a team.' },
  { match: ['wastage'], meaning: 'Material used beyond what the work needed; a little is normal, a lot is a leak.' },
  { match: ['reconciliation'], meaning: 'What should have been used for the work done, compared with what was actually used.' },
  { match: ['free-issue material', 'free issue'], meaning: 'Material the client supplies to the contractor, which must be accounted for.' },
  { match: ['3-way match', 'three-way match'], meaning: 'The order, the delivery and the bill agree before the bill is paid.' },
  { match: ['cum', 'CFT', 'brass'], meaning: 'Volumes: 1 cum (cubic metre) is about 35.3 cft (cubic feet); 1 brass is 100 cft.' },
  { match: ['HSN code', 'HSN'], meaning: 'The tax classification code printed on GST bills.' },
  { match: ['GSTIN'], meaning: "A business's GST registration number, printed on its bills and letterhead." },
  { match: ['cost centre', 'cost center'], meaning: 'The bucket a cost is counted in (materials, labour, fuel, equipment).' },
  { match: ['retention'], meaning: 'A share of each bill the client holds back until the defects period ends.' },
  { match: ['defects period', 'defect liability period'], meaning: 'The time after handover when the contractor must fix defects.' },
  { match: ['variation'], meaning: 'Work the client adds or changes, priced and approved separately.' },
  { match: ['mobilisation advance', 'mobilization advance'], meaning: 'Money the client pays at the start, recovered from later bills.' },
  { match: ['QS', 'quantity surveyor'], meaning: 'The person who measures work and prepares and checks bills and costs.' },
  { match: ['work order'], meaning: 'The agreement with a subcontractor: what work, at what rate, for how much.' },
  { match: ['subcontractor', 'subcontract'], meaning: 'A team or firm you give part of the work to, paid by work done.', example: 'A tiling team paid per sq ft.' },
  { match: ['petty cash', 'cash box'], meaning: 'Cash kept at site for small daily spends, refilled and checked.' },
  { match: ['advance'], meaning: 'Money paid before the work or wage is due, recovered from the later payment.' },
  { match: ['muster roll', 'attendance'], meaning: 'Who was present at site each day, the basis for wages.' },
  { match: ['shuttering', 'formwork'], meaning: 'The temporary mould of plywood or steel that holds wet concrete until it sets.' },
  { match: ['slab'], meaning: 'A flat concrete floor or roof.' },
  { match: ['PCC'], meaning: 'Plain cement concrete, without steel: usually the base layer under footings and floors.' },
  { match: ['RCC'], meaning: 'Reinforced cement concrete: concrete with steel bars inside, for columns, beams and slabs.' },
  { match: ['curing'], meaning: 'Keeping new concrete or plaster wet for days so it gains strength.' },
  { match: ['cube test'], meaning: 'A test that crushes sample concrete cubes at 7 and 28 days to check strength.' },
  { match: ['hindrance'], meaning: 'Anything that stops work at site: no water, no material, a team not turning up.' },
  { match: ['labour', 'helper', 'mason'], meaning: 'The workers at site. Masons do the skilled work; helpers carry and mix for them.' },
  { match: ['site engineer', 'supervisor'], meaning: 'The person on site every day who runs the work and reports it.' },
  { match: ['letterhead'], meaning: "Your company's name, address, GSTIN and logo at the top of every document Mesiri makes." },
  { match: ['GST'], meaning: 'Goods and services tax, added to most bills; a GST-registered business can claim it back.' },
  // UX-27 (17 Nov): the words of Project start, the contract and the BOQ page, for someone new to construction.
  { match: ['TDS', 'tax deducted at source'], meaning: 'Income tax the client keeps back from each bill and pays to the government for you; you claim it when you file tax.', example: '2% TDS on a ₹10 lakh bill: ₹20,000 kept back.' },
  { match: ['BOQ line'], meaning: 'One item of work in the BOQ: what it is, its unit, how much, and the rate the client pays.', example: '4.1 Plastering, 1,200 sqm at ₹420 a sqm.' },
  { match: ['BOQ section'], meaning: 'A group of BOQ lines for one part of the building, like Earthwork or Plastering.' },
  { match: ['contract value'], meaning: 'What the client pays you for all the work in the BOQ: each line\'s quantity times its rate, added up.' },
  { match: ['budget cost'], meaning: 'What the work should cost you to build: your own cost rate for each line, added up. Less than the contract value is your profit.' },
  { match: ['margin'], meaning: 'What is left for you: the client\'s rate minus your cost, as a share of the client\'s rate. Red means the line loses money.', example: 'Client pays ₹100, it costs you ₹80: margin 20%.' },
  { match: ['earned so far', 'earned'], meaning: 'The value of the work already done: what the client owes you for it at the BOQ rates.' },
  { match: ['unpriced', 'no budget rate'], meaning: 'A BOQ line with no cost rate yet, so its margin can\'t be worked out.' },
  { match: ['rate'], meaning: 'The price for one unit of work: per sqm of plaster, per cum of concrete.' },
  { match: ['handover'], meaning: 'The day the building is given to the client. The contract says when it is due.' },
]

/** One term by any of its words (UX-27: a hint beside a label). */
export function glossaryTerm(word: string): GlossaryTerm | undefined {
  return BY_WORD.get(word.toLowerCase())
}

export interface GlossaryHit {
  term: GlossaryTerm
  /** The words as they appear in the text. */
  text: string
}

const BY_WORD = new Map<string, GlossaryTerm>()
for (const term of GLOSSARY) for (const word of term.match) if (!BY_WORD.has(word.toLowerCase())) BY_WORD.set(word.toLowerCase(), term)

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
// Longest words first, so "RA bill" wins over a shorter word inside it; whole words only.
const PATTERN = new RegExp(
  `(?<![\\p{L}\\p{N}])(${[...BY_WORD.keys()].sort((a, b) => b.length - a.length).map(escape).join('|')})(?![\\p{L}\\p{N}])`,
  'giu',
)

/** The text split into plain parts and glossary words; each term is marked once (its first time). */
export function splitTerms(text: string): (string | GlossaryHit)[] {
  const out: (string | GlossaryHit)[] = []
  const used = new Set<GlossaryTerm>()
  let last = 0
  for (const m of text.matchAll(PATTERN)) {
    const term = BY_WORD.get(m[0].toLowerCase())
    if (!term || used.has(term)) continue
    // Short capital abbreviations (PO, QS, GST) only when written in capitals: "po" or "qs" inside prose are not them.
    if (/^[A-Z0-9-]{2,5}$/.test(term.match.find((w) => w.toLowerCase() === m[0].toLowerCase()) ?? '') && m[0] !== m[0].toUpperCase()) continue
    used.add(term)
    if (m.index > last) out.push(text.slice(last, m.index))
    out.push({ term, text: m[0] })
    last = m.index + m[0].length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}
