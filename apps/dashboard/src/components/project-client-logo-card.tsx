import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ImagePlus, Loader2, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/lib/AuthContext'
import { fetchClientLogo, removeClientLogo, uploadClientLogo, type ClientLogo } from '@/lib/projects'
import { LOGO_TYPES, apiErrorMessage, logoFileProblem, readAsBase64 } from '@/lib/logo-upload'

// The client's logo, printed on this project's DPRs next to the company's own
// (tracker WEB-08, API BE-33, PDF BE-19). Company admins change it.

export function ProjectClientLogoCard({ projectId, clientName }: { projectId: string; clientName: string | null }) {
  const queryClient = useQueryClient()
  const { me } = useAuth()
  const canEdit = (me?.role || '').toUpperCase() === 'ADMIN'
  const key = ['project-client-logo', projectId]
  const fileInput = React.useRef<HTMLInputElement>(null)
  const [error, setError] = React.useState<string | null>(null)

  const { data, isLoading } = useQuery({ queryKey: key, queryFn: () => fetchClientLogo(projectId) })
  const onSaved = (logo: ClientLogo) => queryClient.setQueryData(key, logo)

  const upload = useMutation({
    mutationFn: async (file: File) => uploadClientLogo(projectId, file.type, await readAsBase64(file)),
    onMutate: () => setError(null),
    onSuccess: onSaved,
    onError: (err) => setError(apiErrorMessage(err)),
  })
  const remove = useMutation({
    mutationFn: () => removeClientLogo(projectId),
    onMutate: () => setError(null),
    onSuccess: onSaved,
    onError: (err) => setError(apiErrorMessage(err)),
  })

  const onPick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    const problem = logoFileProblem(file)
    if (problem) {
      setError(problem)
      return
    }
    upload.mutate(file)
  }

  const busy = upload.isPending || remove.isPending

  return (
    <div className="flex flex-col gap-3 text-sm">
        <p className="text-muted-foreground">
          Printed on this project's DPRs next to your company logo{clientName ? `, with "${clientName}"` : ''}. PNG, JPEG or
          WebP, up to 700 KB.
        </p>
        <div className="flex items-center gap-4">
          <div className="size-16 shrink-0 rounded-lg border bg-muted/30 flex items-center justify-center overflow-hidden">
            {isLoading ? (
              <Loader2 className="size-4 animate-spin text-muted-foreground" />
            ) : data?.url ? (
              <img src={data.url} alt="Client logo" className="max-h-full max-w-full object-contain" />
            ) : (
              <span className="px-1 text-center text-xs text-muted-foreground">
                {data?.hasClientLogo ? 'Preview unavailable' : 'No logo'}
              </span>
            )}
          </div>
          {canEdit ? (
            <div className="flex flex-wrap gap-2">
              <input
                ref={fileInput}
                type="file"
                accept={LOGO_TYPES.join(',')}
                className="hidden"
                onChange={onPick}
              />
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="gap-1.5"
                disabled={busy}
                onClick={() => fileInput.current?.click()}
              >
                {upload.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <ImagePlus className="size-3.5" />}
                {data?.hasClientLogo ? 'Replace' : 'Upload logo'}
              </Button>
              {data?.hasClientLogo && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="gap-1.5 text-destructive"
                  disabled={busy}
                  onClick={() => remove.mutate()}
                >
                  <Trash2 className="size-3.5" /> Remove
                </Button>
              )}
            </div>
          ) : (
            <span className="text-muted-foreground">Only company admins can change this.</span>
          )}
        </div>
        {error && <p className="text-destructive">{error}</p>}
    </div>
  )
}
