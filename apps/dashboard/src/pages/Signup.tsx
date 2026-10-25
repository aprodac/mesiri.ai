import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { signup, verifySignupCode } from '@/lib/api'
import { apiErrorMessage } from '@/lib/logo-upload'
import { WhatsAppCodeForm } from '@/components/auth/whatsapp-code-form'
import { AuthShell } from '@/components/auth/auth-shell'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

/**
 * Web signup (SS-06): WhatsApp number → code → the same questions as the
 * WhatsApp signup → a trial company and straight into the dashboard.
 */
export default function Signup() {
  const navigate = useNavigate()
  const [ticket, setTicket] = useState<string | null>(null)
  const [ownerName, setOwnerName] = useState('')
  const [companyName, setCompanyName] = useState('')
  const [siteName, setSiteName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault()
    if (!ticket) return
    setError(null)
    setLoading(true)
    try {
      await signup({
        signup_token: ticket,
        owner_name: ownerName,
        company_name: companyName,
        site_name: siteName,
      })
      navigate('/today', { replace: true })
    } catch (err) {
      setError(apiErrorMessage(err))
      setLoading(false)
    }
  }

  return (
    <AuthShell
      title={ticket ? 'About your company' : 'Start your free trial'}
      subtitle={
        <>
          <span className="font-medium text-foreground">Step {ticket ? 2 : 1} of 2.</span>{' '}
          {ticket ? 'Three quick questions and your daily reports are ready.' : 'No password needed: we send a code to your WhatsApp.'}
        </>
      }
      footer={
        <>
          Already using Mesiri?{' '}
          <Link to="/login" className="font-medium text-foreground underline underline-offset-2">
            Sign in
          </Link>
        </>
      }
    >
      {!ticket ? (
        <WhatsAppCodeForm
          purpose="signup"
          submitLabel="Continue"
          phoneHint="The number you use on WhatsApp. Your site team reports to Mesiri on WhatsApp too."
          onCode={async (phone, code) => setTicket(await verifySignupCode(phone, code))}
        />
      ) : (
        <form onSubmit={handleCreate} className="grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor="owner-name">Your name</Label>
            <Input
              id="owner-name"
              autoComplete="name"
              required
              autoFocus
              value={ownerName}
              onChange={(e) => setOwnerName(e.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="company-name">Company name</Label>
            <Input
              id="company-name"
              autoComplete="organization"
              required
              value={companyName}
              onChange={(e) => setCompanyName(e.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="site-name">Which site are you working on now?</Label>
            <Input
              id="site-name"
              placeholder="Green Villa, Kakkanad"
              required
              value={siteName}
              onChange={(e) => setSiteName(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">You can add more sites later.</p>
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <Button type="submit" className="w-full" disabled={loading}>
            {loading ? 'Setting up…' : 'Start free trial'}
          </Button>
        </form>
      )}
    </AuthShell>
  )
}
