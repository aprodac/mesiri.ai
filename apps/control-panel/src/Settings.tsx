import { useState } from 'react';
import { api } from './api';
import PlatformSettingsCard from './PlatformSettingsCard';

export default function Settings() {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(false);

    if (newPassword !== confirmPassword) {
      setError('New password and confirmation do not match.');
      return;
    }
    if (newPassword.length < 8) {
      setError('New password must be at least 8 characters.');
      return;
    }

    setSubmitting(true);
    api
      .post('/auth/change-password', { current_password: currentPassword, new_password: newPassword })
      .then(() => {
        setSuccess(true);
        setCurrentPassword('');
        setNewPassword('');
        setConfirmPassword('');
      })
      .catch((err) => {
        setError(err.response?.data?.detail || 'Failed to change password');
      })
      .finally(() => setSubmitting(false));
  };

  return (
    <div className="animate-fade-in" style={{ maxWidth: '640px' }}>
      <header style={{ marginBottom: 'var(--space-6)' }}>
        <h1>Settings</h1>
        <p className="subtitle">Platform-wide rules, and your account password.</p>
      </header>

      <div style={{ marginBottom: 'var(--space-6)' }}>
        <PlatformSettingsCard />
      </div>

      <div className="card">
        <h3 style={{ marginTop: 0, fontSize: '16px' }}>Your password</h3>
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Current password</label>
            <input
              required
              type="password"
              className="form-input"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
            />
          </div>
          <div className="form-group">
            <label>New password</label>
            <input
              required
              type="password"
              className="form-input"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
            />
          </div>
          <div className="form-group">
            <label>Confirm new password</label>
            <input
              required
              type="password"
              className="form-input"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
            />
          </div>

          {error && (
            <p style={{ color: 'var(--error)', fontSize: '13px', marginBottom: 'var(--space-4)' }}>{error}</p>
          )}
          {success && (
            <p style={{ color: 'var(--success)', fontSize: '13px', marginBottom: 'var(--space-4)' }}>
              Password changed successfully.
            </p>
          )}

          <button type="submit" className="btn-primary" disabled={submitting}>
            {submitting ? 'Saving…' : 'Change password'}
          </button>
        </form>
      </div>
    </div>
  );
}
