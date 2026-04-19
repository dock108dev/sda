"use client";

import { useEffect, useState, useCallback } from "react";
import styles from "./styles.module.css";

interface UserRecord {
  id: number;
  email: string;
  role: string;
  isActive: boolean;
  createdAt: string;
}

export default function UsersPage() {
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Create user form
  const [showForm, setShowForm] = useState(false);
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState("user");
  const [creating, setCreating] = useState(false);

  // Inline edit state
  const [editingEmailId, setEditingEmailId] = useState<number | null>(null);
  const [editEmailValue, setEditEmailValue] = useState("");
  const [resetPasswordId, setResetPasswordId] = useState<number | null>(null);
  const [resetPasswordValue, setResetPasswordValue] = useState("");

  const fetchUsers = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch("/proxy/api/admin/users");
      if (!res.ok) throw new Error(`Failed to load users (${res.status})`);
      const data = await res.json();
      setUsers(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load users");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true);
    try {
      const res = await fetch("/proxy/api/admin/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: newEmail, password: newPassword, role: newRole }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Failed to create user (${res.status})`);
      }
      setNewEmail("");
      setNewPassword("");
      setNewRole("user");
      setShowForm(false);
      fetchUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create user");
    } finally {
      setCreating(false);
    }
  }

  async function handleRoleChange(userId: number, role: string) {
    try {
      const res = await fetch(`/proxy/api/admin/users/${userId}/role`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role }),
      });
      if (!res.ok) throw new Error(`Failed to update role (${res.status})`);
      fetchUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update role");
    }
  }

  async function handleToggleActive(userId: number, isActive: boolean) {
    try {
      const res = await fetch(`/proxy/api/admin/users/${userId}/active`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: !isActive }),
      });
      if (!res.ok) throw new Error(`Failed to update status (${res.status})`);
      fetchUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update status");
    }
  }

  async function handleEmailUpdate(userId: number) {
    try {
      const res = await fetch(`/proxy/api/admin/users/${userId}/email`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: editEmailValue }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Failed to update email (${res.status})`);
      }
      setEditingEmailId(null);
      setEditEmailValue("");
      fetchUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update email");
    }
  }

  async function handleResetPassword(userId: number) {
    try {
      const res = await fetch(`/proxy/api/admin/users/${userId}/password`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: resetPasswordValue }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Failed to reset password (${res.status})`);
      }
      setResetPasswordId(null);
      setResetPasswordValue("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reset password");
    }
  }

  async function handleDelete(userId: number, email: string) {
    if (!confirm(`Delete user ${email}? This cannot be undone.`)) return;
    try {
      const res = await fetch(`/proxy/api/admin/users/${userId}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error(`Failed to delete user (${res.status})`);
      fetchUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete user");
    }
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Users</h1>
          <p className={styles.subtitle}>
            Manage user accounts for downstream consuming applications
          </p>
        </div>
        <button
          className={styles.createBtn}
          onClick={() => setShowForm(!showForm)}
        >
          {showForm ? "Cancel" : "Create User"}
        </button>
      </div>

      {error && (
        <div className={styles.error}>
          {error}
          <button onClick={() => setError(null)} className={styles.dismissBtn}>
            Dismiss
          </button>
        </div>
      )}

      {showForm && (
        <form onSubmit={handleCreate} className={styles.form}>
          <div className={styles.formRow}>
            <label className={styles.label}>
              Email
              <input
                type="email"
                value={newEmail}
                onChange={(e) => setNewEmail(e.target.value)}
                required
                className={styles.input}
                placeholder="user@example.com"
              />
            </label>
            <label className={styles.label}>
              Password
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
                minLength={8}
                className={styles.input}
                placeholder="Min 8 characters"
              />
            </label>
            <label className={styles.label}>
              Role
              <select
                value={newRole}
                onChange={(e) => setNewRole(e.target.value)}
                className={styles.select}
              >
                <option value="user">user</option>
                <option value="admin">admin</option>
              </select>
            </label>
            <button
              type="submit"
              disabled={creating}
              className={styles.submitBtn}
            >
              {creating ? "Creating..." : "Create"}
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <div className={styles.loading}>Loading users...</div>
      ) : users.length === 0 ? (
        <div className={styles.empty}>No user accounts yet.</div>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>ID</th>
              <th>Email</th>
              <th>Role</th>
              <th>Status</th>
              <th>Created</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((user) => (
              <tr key={user.id} className={!user.isActive ? styles.inactive : ""}>
                <td>{user.id}</td>
                <td>
                  {editingEmailId === user.id ? (
                    <span className={styles.inlineEdit}>
                      <input
                        type="email"
                        value={editEmailValue}
                        onChange={(e) => setEditEmailValue(e.target.value)}
                        className={styles.inlineInput}
                        autoFocus
                      />
                      <button
                        className={styles.inlineSave}
                        onClick={() => handleEmailUpdate(user.id)}
                      >
                        Save
                      </button>
                      <button
                        className={styles.inlineCancel}
                        onClick={() => setEditingEmailId(null)}
                      >
                        Cancel
                      </button>
                    </span>
                  ) : (
                    <button
                      type="button"
                      className={styles.editableEmail}
                      onClick={() => {
                        setEditingEmailId(user.id);
                        setEditEmailValue(user.email);
                      }}
                      title="Click to edit email"
                    >
                      {user.email}
                    </button>
                  )}
                </td>
                <td>
                  <select
                    value={user.role}
                    onChange={(e) => handleRoleChange(user.id, e.target.value)}
                    className={styles.roleSelect}
                  >
                    <option value="user">user</option>
                    <option value="admin">admin</option>
                  </select>
                </td>
                <td>
                  <span
                    className={`${styles.badge} ${user.isActive ? styles.badgeActive : styles.badgeInactive}`}
                  >
                    {user.isActive ? "Active" : "Disabled"}
                  </span>
                </td>
                <td>{new Date(user.createdAt).toLocaleDateString()}</td>
                <td>
                  <div className={styles.actions}>
                    <button
                      className={`${styles.actionBtn} ${user.isActive ? styles.disableBtn : styles.enableBtn}`}
                      onClick={() => handleToggleActive(user.id, user.isActive)}
                    >
                      {user.isActive ? "Disable" : "Enable"}
                    </button>
                    {resetPasswordId === user.id ? (
                      <span className={styles.inlineEdit}>
                        <input
                          type="password"
                          value={resetPasswordValue}
                          onChange={(e) => setResetPasswordValue(e.target.value)}
                          className={styles.inlineInput}
                          placeholder="New password"
                          minLength={8}
                          autoFocus
                        />
                        <button
                          className={styles.inlineSave}
                          onClick={() => handleResetPassword(user.id)}
                          disabled={resetPasswordValue.length < 8}
                        >
                          Set
                        </button>
                        <button
                          className={styles.inlineCancel}
                          onClick={() => {
                            setResetPasswordId(null);
                            setResetPasswordValue("");
                          }}
                        >
                          Cancel
                        </button>
                      </span>
                    ) : (
                      <button
                        className={`${styles.actionBtn} ${styles.resetBtn}`}
                        onClick={() => setResetPasswordId(user.id)}
                      >
                        Reset PW
                      </button>
                    )}
                    <button
                      className={`${styles.actionBtn} ${styles.deleteBtn}`}
                      onClick={() => handleDelete(user.id, user.email)}
                    >
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
