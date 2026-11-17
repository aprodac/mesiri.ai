/**
 * A person's or company's initials for an avatar: the first and last word's first letters ("Asha Menon" -> AM).
 * One rule for every avatar (found 17 Nov: seven copies, and "Anil (project manager)" showed "A(").
 * What is in brackets is a note, not the name, and only letters and digits count.
 */
export function initialsOf(name: string | null | undefined): string {
  const words = (name ?? '').replace(/\([^)]*\)/g, ' ').split(/[^\p{L}\p{N}]+/u).filter(Boolean)
  if (words.length === 0) return '?'
  return (words[0][0] + (words.length > 1 ? words[words.length - 1][0] : '')).toUpperCase()
}
