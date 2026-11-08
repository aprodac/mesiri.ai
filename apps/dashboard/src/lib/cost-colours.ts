import type { VarianceColour } from './cost'

// The one colour language of Cost control (CC-07): green / amber / red, and grey for "not judged" (never a colour
// made up). Shared by Overview, Green / red and Materials vs BOQ so the three never drift apart.
export const COLOUR_DOT: Record<VarianceColour, string> = {
  green: 'bg-success',
  amber: 'bg-draft',
  red: 'bg-destructive',
  grey: 'bg-muted-foreground/40',
}
export const COLOUR_TEXT: Record<VarianceColour, string> = {
  green: 'text-success',
  amber: 'text-draft',
  red: 'text-destructive',
  grey: 'text-muted-foreground',
}
export const COLOUR_WORD: Record<VarianceColour, string> = { green: 'Green', amber: 'Amber', red: 'Red', grey: 'Not judged' }
