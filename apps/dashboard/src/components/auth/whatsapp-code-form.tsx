import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { requestCode, type CodePurpose } from '@/lib/api'
import { apiErrorMessage } from '@/lib/logo-upload'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

/**
 * Phone number, then the 6-digit code Mesiri sends on WhatsApp (SS-06,
 * WEB-12). Used by code login and by web signup; what a right code does is
 * `onCode`'s job, which throws to show its error here.
 */
export function WhatsAppCodeForm({
  purpose,
  submitLabel,
  onCode,
  phoneHint,
}: {
  purpose: CodePurpose
  submitLabel: string
  onCode: (phone: string, code: string) => Promise<void>
  phoneHint?: ReactNode
}) {
  const [phone, setPhone] = useState('')
  const [code, setCode] = useState('')
  const [sent, setSent] = useState(false)
  const [devCode, setDevCode] = useState<string | null>(null)
  const [resendIn, setResendIn] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (resendIn <= 0) return
    const timer = window.setTimeout(() => setResendIn((s) => s - 1), 1000)
    return () => window.clearTimeout(timer)
  }, [resendIn])

  const send = async () => {
    setError(null)
    setLoading(true)
    try {
      const res = await requestCode(phone, purpose)
      setSent(true)
      setCode('')
      setDevCode(res.dev_code)
      setResendIn(res.resend_after_s)
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  const check = async () => {
    setError(null)
    setLoading(true)
    try {
      await onCode(phone, code)
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    void (sent ? check() : send())
  }

  return (
    <form onSubmit={handleSubmit} className="grid gap-4">
      <div className="grid gap-2">
        <Label htmlFor="phone">WhatsApp number</Label>
        <Input
          id="phone"
          type="tel"
          inputMode="tel"
          autoComplete="tel"
          placeholder="98765 43210"
          required
          disabled={sent}
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
        />
        {!sent && phoneHint && <p className="text-xs text-muted-foreground">{phoneHint}</p>}
        {sent && (
          <button
            type="button"
            className="justify-self-start text-xs text-muted-foreground underline underline-offset-2"
            onClick={() => {
              setSent(false)
              setError(null)
            }}
          >
            Change number
          </button>
        )}
      </div>

      {sent && (
        <div className="grid gap-2">
          <Label htmlFor="code">Code sent on WhatsApp</Label>
          <Input
            id="code"
            inputMode="numeric"
            autoComplete="one-time-code"
            placeholder="6-digit code"
            maxLength={9}
            required
            autoFocus
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
          {devCode && (
            <p className="text-xs text-muted-foreground">
              Test server: nothing was sent. Your code is <span className="font-mono">{devCode}</span>.
            </p>
          )}
          <button
            type="button"
            className="justify-self-start text-xs text-muted-foreground underline underline-offset-2 disabled:no-underline disabled:opacity-60"
            disabled={resendIn > 0 || loading}
            onClick={() => void send()}
          >
            {resendIn > 0 ? `Send a new code in ${resendIn}s` : 'Send a new code'}
          </button>
        </div>
      )}

      {error && <p className="text-sm text-destructive">{error}</p>}
      <Button type="submit" className="w-full" disabled={loading}>
        {loading ? 'Please wait…' : sent ? submitLabel : 'Send code on WhatsApp'}
      </Button>
    </form>
  )
}
