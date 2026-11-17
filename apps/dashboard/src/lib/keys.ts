/** A key press inside a text field (or anything editable) is typing, never a shortcut. */
export function typingIn(e: KeyboardEvent): boolean {
  const t = e.target as HTMLElement | null
  return !!t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.getAttribute('role') === 'combobox')
}
