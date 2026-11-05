import { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import { api } from './api';

export interface OrgSite {
  id: string;
  name: string;
}

export interface OrgProject {
  id: string;
  name: string;
  sites: OrgSite[];
}

export interface EditableUser {
  id: string;
  full_name: string | null;
  email: string | null;
  role: string | null;
  whatsapp_number: string | null;
  access_mode: string;
  project_access: { project_id: string; project_name: string; site_access: string }[];
  // WA-246: this person's own "show what was heard" switch; null follows the company.
  voice_transcript?: boolean | null;
}

type VoiceTranscript = 'company' | 'on' | 'off';

const ROLES = ['ADMIN', 'PROJECT_MANAGER', 'SITE_ENGINEER', 'FINANCE'];

const ROLE_LABELS: Record<string, string> = {
  ADMIN: 'Admin',
  PROJECT_MANAGER: 'Project manager',
  SITE_ENGINEER: 'Site engineer',
  FINANCE: 'Finance',
};

// Mirrors the backend's access_policy shape (users/access_service.py).
interface SiteAccess {
  mode: 'all_sites' | 'custom_sites';
  siteIds?: string[];
}

interface ProjectGrant {
  projectId: string;
  siteAccess: SiteAccess;
}

interface Props {
  orgId: string;
  user: EditableUser;
  projects: OrgProject[];
  onClose: () => void;
  onSaved: () => void;
}

export default function UserAccessEditor({ orgId, user, projects, onClose, onSaved }: Props) {
  const [role, setRole] = useState(user.role || 'SITE_ENGINEER');
  const [whatsapp, setWhatsapp] = useState(user.whatsapp_number || '');
  const [voiceTranscript, setVoiceTranscript] = useState<VoiceTranscript>(
    user.voice_transcript === true ? 'on' : user.voice_transcript === false ? 'off' : 'company'
  );
  const [allProjects, setAllProjects] = useState(user.access_mode === 'all_projects');
  const [grants, setGrants] = useState<Record<string, SiteAccess>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Seed the checkboxes from what the user already has. The list endpoint
  // returns site access as a rendered label rather than ids, so an existing
  // grant starts as "all sites" and is narrowed only if the operator
  // explicitly picks sites.
  useEffect(() => {
    const seeded: Record<string, SiteAccess> = {};
    for (const grant of user.project_access) {
      seeded[grant.project_id] = { mode: 'all_sites' };
    }
    setGrants(seeded);
  }, [user]);

  const isAdmin = role === 'ADMIN';

  const toggleProject = (projectId: string, on: boolean) => {
    setGrants((prev) => {
      const next = { ...prev };
      if (on) next[projectId] = { mode: 'all_sites' };
      else delete next[projectId];
      return next;
    });
  };

  const toggleSite = (projectId: string, siteId: string, on: boolean) => {
    setGrants((prev) => {
      const current = prev[projectId] || { mode: 'all_sites' };
      const existing = current.mode === 'custom_sites' ? current.siteIds || [] : [];
      const siteIds = on ? [...existing, siteId] : existing.filter((s) => s !== siteId);
      return {
        ...prev,
        [projectId]: siteIds.length ? { mode: 'custom_sites', siteIds } : { mode: 'all_sites' },
      };
    });
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      // Profile first: role feeds the org-wide bypass, so it must be stored
      // before access is evaluated against it.
      await api.patch(`/admin/organizations/${orgId}/users/${user.id}`, {
        role,
        whatsapp_number: whatsapp.trim(),
        voice_transcript: voiceTranscript,
      });

      const projectGrants: ProjectGrant[] = Object.entries(grants).map(([projectId, siteAccess]) => ({
        projectId,
        siteAccess,
      }));

      await api.put(`/admin/organizations/${orgId}/users/${user.id}/access`, {
        mode: allProjects ? 'all_projects' : 'custom_projects',
        projects: allProjects ? [] : projectGrants,
      });

      onSaved();
      onClose();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to save. Nothing was changed.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      style={{
        // `fixed`, matching DeleteOrgModal — the page has no positioned
        // ancestor, so `absolute` would anchor to the document and scroll
        // away from the viewport on a long user list.
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.45)',
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'center',
        padding: 'var(--space-6)',
        zIndex: 50,
      }}
      onClick={onClose}
    >
      <div
        className="card"
        style={{ maxWidth: '640px', width: '100%', maxHeight: '80vh', overflowY: 'auto' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
            marginBottom: 'var(--space-4)',
          }}
        >
          <div>
            <h2 style={{ fontSize: '17px', margin: 0 }}>
              {user.full_name || user.email || 'User'}
            </h2>
            <p style={{ fontSize: '13px', color: 'var(--neutral-500)', margin: '2px 0 0' }}>
              {user.email}
            </p>
          </div>
          <button
            style={{ background: 'none', border: 'none', cursor: 'pointer' }}
            onClick={onClose}
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>

        {error && (
          <p style={{ color: 'var(--error)', fontSize: '13px', marginBottom: 'var(--space-3)' }}>
            {error}
          </p>
        )}

        <label style={{ display: 'block', fontSize: '13px', fontWeight: 500, marginBottom: 4 }}>
          Role
        </label>
        <select
          value={role}
          onChange={(e) => setRole(e.target.value)}
          style={{ width: '100%', marginBottom: 'var(--space-4)', padding: '8px' }}
        >
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {ROLE_LABELS[r] || r}
            </option>
          ))}
        </select>

        <label style={{ display: 'block', fontSize: '13px', fontWeight: 500, marginBottom: 4 }}>
          WhatsApp number
        </label>
        <input
          value={whatsapp}
          onChange={(e) => setWhatsapp(e.target.value)}
          placeholder="919876543210"
          style={{ width: '100%', marginBottom: 4, padding: '8px' }}
        />
        <p style={{ fontSize: '12px', color: 'var(--neutral-500)', margin: '0 0 var(--space-4)' }}>
          This is how an incoming WhatsApp message is matched to this person. Leave blank to unmap.
        </p>

        <label style={{ display: 'block', fontSize: '13px', fontWeight: 500, marginBottom: 4 }}>
          Show what was heard on voice-note replies
        </label>
        <select
          value={voiceTranscript}
          onChange={(e) => setVoiceTranscript(e.target.value as VoiceTranscript)}
          style={{ width: '100%', marginBottom: 4, padding: '8px' }}
        >
          <option value="company">Same as the company (Settings: voice_transcript)</option>
          <option value="on">On for this person</option>
          <option value="off">Off for this person</option>
        </select>
        <p style={{ fontSize: '12px', color: 'var(--neutral-500)', margin: '0 0 var(--space-4)' }}>
          On: the reply to a voice note starts with "🎤 what Mesiri heard". Off by default for every company.
        </p>

        <div
          style={{
            borderTop: '1px solid var(--border-strong)',
            paddingTop: 'var(--space-4)',
            marginBottom: 'var(--space-3)',
          }}
        >
          <div style={{ fontSize: '13px', fontWeight: 500, marginBottom: 'var(--space-2)' }}>
            Project access
          </div>

          {isAdmin && (
            <p
              style={{
                fontSize: '12px',
                color: 'var(--neutral-500)',
                background: 'var(--neutral-100)',
                padding: '8px 10px',
                borderRadius: 'var(--radius)',
                margin: '0 0 var(--space-3)',
              }}
            >
              Admins reach every project in the organization automatically — this applies
              everywhere, including WhatsApp. The selection below is ignored while the role is
              Admin.
            </p>
          )}

          <label
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              fontSize: '13px',
              marginBottom: 'var(--space-3)',
              opacity: isAdmin ? 0.5 : 1,
            }}
          >
            <input
              type="checkbox"
              checked={allProjects || isAdmin}
              disabled={isAdmin}
              onChange={(e) => setAllProjects(e.target.checked)}
            />
            All projects, including ones created later
          </label>

          {!allProjects && !isAdmin && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
              {projects.length === 0 ? (
                <p style={{ fontSize: '13px', color: 'var(--neutral-500)' }}>
                  This organization has no projects yet.
                </p>
              ) : (
                projects.map((project) => {
                  const grant = grants[project.id];
                  const selected = !!grant;
                  return (
                    <div
                      key={project.id}
                      style={{
                        border: '1px solid var(--border-strong)',
                        borderRadius: 'var(--radius)',
                        padding: '10px 12px',
                      }}
                    >
                      <label
                        style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '13px' }}
                      >
                        <input
                          type="checkbox"
                          checked={selected}
                          onChange={(e) => toggleProject(project.id, e.target.checked)}
                        />
                        <span style={{ fontWeight: 500 }}>{project.name}</span>
                      </label>

                      {selected && project.sites.length > 0 && (
                        <div style={{ marginTop: 8, marginLeft: 24 }}>
                          <div
                            style={{
                              fontSize: '12px',
                              color: 'var(--neutral-500)',
                              marginBottom: 4,
                            }}
                          >
                            {grant.mode === 'all_sites'
                              ? 'All sites — tick specific sites to narrow it'
                              : 'Selected sites only'}
                          </div>
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
                            {project.sites.map((site) => (
                              <label
                                key={site.id}
                                style={{
                                  display: 'flex',
                                  alignItems: 'center',
                                  gap: 6,
                                  fontSize: '12px',
                                }}
                              >
                                <input
                                  type="checkbox"
                                  checked={
                                    grant.mode === 'custom_sites' &&
                                    (grant.siteIds || []).includes(site.id)
                                  }
                                  onChange={(e) => toggleSite(project.id, site.id, e.target.checked)}
                                />
                                {site.name}
                              </label>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          )}
        </div>

        <div
          style={{
            display: 'flex',
            justifyContent: 'flex-end',
            gap: 'var(--space-2)',
            borderTop: '1px solid var(--border-strong)',
            paddingTop: 'var(--space-4)',
          }}
        >
          <button className="btn-secondary" onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button className="btn-primary" onClick={save} disabled={saving}>
            {saving ? 'Saving…' : 'Save changes'}
          </button>
        </div>
      </div>
    </div>
  );
}
