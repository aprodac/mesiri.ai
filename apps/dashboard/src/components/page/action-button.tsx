import * as React from 'react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { DropdownMenuItem } from '@/components/ui/dropdown-menu'
import { ACTION_LOOK, ACTION_TONE_ICON, type ActionKind } from '@/lib/actions'
import { cn } from '@/lib/utils'

// UX-15: a button that looks like what it does, from lib/actions.ts. Outline by default with the kind's icon in the
// kind's colour (Import from Excel: green sheet; Remove: red bin). `primary` makes it the page's one yellow button
// (docs/DESIGN.md section 3); a primary remove (a dialog's "Remove") is the red destructive button.

type ButtonProps = Omit<React.ComponentProps<typeof Button>, 'asChild' | 'children'>

export function ActionIcon({ kind, className }: { kind: ActionKind; className?: string }) {
  const look = ACTION_LOOK[kind]
  const Icon = look.icon
  return <Icon className={cn('size-4 shrink-0', ACTION_TONE_ICON[look.tone], className)} />
}

export function ActionButton({
  kind,
  primary,
  iconOnly,
  to,
  href,
  label,
  children,
  className,
  variant,
  size = 'sm',
  ...props
}: ButtonProps & {
  kind: ActionKind
  /** The page's one main button (yellow), or for a remove, the red one. */
  primary?: boolean
  /** Only the icon; the label becomes its tooltip and name. */
  iconOnly?: boolean
  /** Opens a page in the app. */
  to?: string
  /** Opens a file or another site, in a new tab. */
  href?: string
  /** The words; the kind's own words when left out. */
  label?: string
  children?: React.ReactNode
}) {
  const look = ACTION_LOOK[kind]
  const words = children ?? label ?? look.label
  const name = label ?? (typeof children === 'string' ? children : look.label)
  const danger = look.tone === 'danger'
  const v = variant ?? (primary ? (danger ? 'destructive' : 'default') : iconOnly ? 'ghost' : 'outline')
  // On a filled button the icon takes the button's ink, so it never sits coloured on yellow or red.
  const icon = <ActionIcon kind={kind} className={cn(primary && 'text-current', iconOnly && 'size-4')} />
  const content = iconOnly ? icon : (
    <>
      {icon}
      {words}
    </>
  )
  const cls = cn(
    primary && !danger && 'font-semibold',
    iconOnly && 'size-8 text-muted-foreground',
    iconOnly && danger && 'hover:bg-destructive/10 hover:text-destructive',
    className,
  )
  const a11y = iconOnly ? { 'aria-label': name, title: props.title ?? name } : {}
  if (to || href) {
    return (
      <Button asChild variant={v} size={iconOnly ? 'icon' : size} className={cls} {...a11y} {...props}>
        {to ? (
          <Link to={to}>{content}</Link>
        ) : (
          <a href={href} target="_blank" rel="noreferrer">
            {content}
          </a>
        )}
      </Button>
    )
  }
  return (
    <Button type="button" variant={v} size={iconOnly ? 'icon' : size} className={cls} {...a11y} {...props}>
      {content}
    </Button>
  )
}

/** A row menu's item with the kind's icon; a remove or refuse is red. */
export function ActionMenuItem({
  kind,
  children,
  className,
  ...props
}: React.ComponentProps<typeof DropdownMenuItem> & { kind: ActionKind }) {
  const danger = ACTION_LOOK[kind].tone === 'danger'
  return (
    <DropdownMenuItem className={cn(danger && 'text-destructive focus:text-destructive', className)} {...props}>
      <ActionIcon kind={kind} className="mr-2 size-3.5" />
      {children ?? ACTION_LOOK[kind].label}
    </DropdownMenuItem>
  )
}
