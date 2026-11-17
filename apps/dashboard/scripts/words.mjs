#!/usr/bin/env node
// UX-14: the words on a page. Reads every .tsx under src/pages and src/components and lists text a person would
// have to read: a run of words in JSX (a paragraph, a callout, a note) longer than LIMIT words.
//
//   node scripts/words.mjs              # the report: files, worst first
//   node scripts/words.mjs --list       # every long text, with its line
//   node scripts/words.mjs --check      # CI: fails when any text is over the limit
//   LIMIT=8 node scripts/words.mjs
//
// A text over the limit belongs in the page's help (lib/page-help.ts), a legend of dots (page kit `Legend`), a
// chip, or nowhere. docs/DESIGN.md "Space, words and help".
//
// Text inside a dialog, a sheet, a tooltip, the help panel, tours and Learn is not counted: a person asked for it.
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const here = dirname(fileURLToPath(import.meta.url))
const SRC = join(here, '..', 'src')
const LIMIT = Number(process.env.LIMIT || 12)

// A person opened these to read: not page chrome.
const SKIP_FILES = [/components\/ui\//, /help-button/, /tour\.tsx$/, /walkthrough/, /LearnPage/, /components\/onboarding\//, /page-guide\.tsx$/, /guide-voice/, /Login\.tsx$/, /Signup\.tsx$/, /WelcomePage/, /ClientViewPage/, /DocumentPage\.tsx$/, /dpr-document/, /components\/live\//, /LivePage|LivePlansPage/, /tell-mesiri/, /whatsapp-preview/, /whatsapp-phone-mockup/, /trial-banner/, /getting-started-card/, /first-report-moment/, /PlannedPage/]
const SKIP_PARENTS = /^(Dialog|DialogContent|DialogDescription|Sheet|SheetContent|SheetDescription|Tooltip|TooltipContent|DetailSheet|DropdownMenuContent|PageError|title|option)$/
// Props that are read aloud to nobody on the page.
const SKIP_ATTRS = /^(className|aria-label|aria-description|title|placeholder|alt|to|href|data-guide|key|id|name|type|d|viewBox|message|description)$/

function walk(dir, out = []) {
  for (const f of readdirSync(dir)) {
    const p = join(dir, f)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (p.endsWith('.tsx')) out.push(p)
  }
  return out
}

// A legend ("P present · ½ half day · A absent") is short labels, not a sentence: count its longest part.
const words = (s) => Math.max(0, ...s.split(' · ').map((part) => part.replace(/\s+/g, ' ').trim().split(' ').filter((w) => /[A-Za-z]/.test(w)).length))

function tagName(node) {
  if (ts.isJsxElement(node)) return node.openingElement.tagName.getText()
  if (ts.isJsxSelfClosingElement(node)) return node.tagName.getText()
  return null
}

function inSkipped(node) {
  for (let n = node.parent; n; n = n.parent) {
    const t = tagName(n)
    if (t && SKIP_PARENTS.test(t.split('.').pop())) return true
    if (ts.isJsxAttribute(n) && SKIP_ATTRS.test(n.name.getText())) return true
  }
  return false
}

function inJsx(node) {
  for (let n = node.parent; n; n = n.parent) {
    if (ts.isJsxElement(n) || ts.isJsxFragment(n) || ts.isJsxAttribute(n) || ts.isJsxExpression(n)) return true
    if (ts.isFunctionLike(n) && !ts.isArrowFunction(n)) return false
  }
  return false
}

const hits = []
for (const file of walk(SRC)) {
  const rel = relative(join(here, '..'), file)
  if (SKIP_FILES.some((r) => r.test(rel))) continue
  const sf = ts.createSourceFile(file, readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const visit = (node) => {
    // A paragraph is its element's whole text: "Showing <b>x</b> only." is one run, not three.
    if (ts.isJsxElement(node) || ts.isJsxFragment(node)) {
      const own = node.children.filter((c) => ts.isJsxText(c)).map((c) => c.text).join(' ')
      const n = words(own)
      if (n > LIMIT && !inSkipped(node.children[0])) {
        hits.push({ rel, line: sf.getLineAndCharacterOfPosition(node.getStart()).line + 1, n, text: own.replace(/\s+/g, ' ').trim() })
      }
    } else if ((ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) && inJsx(node)) {
      const n = words(node.text)
      if (n > LIMIT && !inSkipped(node)) hits.push({ rel, line: sf.getLineAndCharacterOfPosition(node.getStart()).line + 1, n, text: node.text })
    }
    ts.forEachChild(node, visit)
  }
  visit(sf)
}

const byFile = new Map()
for (const h of hits) byFile.set(h.rel, [...(byFile.get(h.rel) || []), h])
const files = [...byFile.entries()].sort((a, b) => b[1].length - a[1].length)
if (process.argv.includes('--list')) {
  for (const [rel, list] of files) {
    console.log(`\n${rel}`)
    for (const h of list) console.log(`  ${h.line}  (${h.n})  ${h.text.slice(0, 170)}`)
  }
} else {
  for (const [rel, list] of files) console.log(`${String(list.length).padStart(3)}  ${rel}`)
}
console.log(`\n${hits.length} texts over ${LIMIT} words in ${files.length} files`)
if (process.argv.includes('--check') && hits.length) {
  for (const h of hits) console.log(`FAIL ${h.rel}:${h.line} (${h.n} words) ${h.text.slice(0, 120)}`)
  console.log('Move the explanation to lib/page-help.ts (the Help panel), or cut it to a label.')
  process.exit(1)
}
