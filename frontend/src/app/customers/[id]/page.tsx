"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ApiError,
  changeCustomerMemberRole,
  disengageCustomerKillSwitch,
  engageCustomerKillSwitch,
  getCustomerKillSwitch,
  inviteCustomerMember,
  listCustomerAudit,
  listCustomerMembers,
  listCustomerNotifications,
  listMyWorkspaces,
  listNotificationPreferences,
  markCustomerNotificationRead,
  removeCustomerMember,
  setNotificationPreference,
  type AuditEventOut,
  type CustomerMemberOut,
  type CustomerRole,
  type KillSwitchStatusOut,
  type NotificationOut,
  type NotificationPreferenceOut,
  type NotificationType,
} from "@/lib/api";
import { useSession } from "@/lib/useSession";

const CUSTOMER_ROLES: CustomerRole[] = ["customer_owner", "member", "auditor"];
const ALWAYS_ON_NOTIFICATION_TYPE: NotificationType = "SECURITY_ALERT";

export default function CustomerPage() {
  const params = useParams<{ id: string }>();
  const customerId = params.id;
  const sessionId = useSession();

  const [customerName, setCustomerName] = useState<string | null>(null);
  const [killSwitch, setKillSwitch] = useState<KillSwitchStatusOut | null>(null);
  const [killSwitchReason, setKillSwitchReason] = useState("");
  const [members, setMembers] = useState<CustomerMemberOut[] | null>(null);
  const [newMemberUserId, setNewMemberUserId] = useState("");
  const [newMemberRole, setNewMemberRole] = useState<CustomerRole>("member");
  const [notifications, setNotifications] = useState<NotificationOut[] | null>(null);
  const [preferences, setPreferences] = useState<NotificationPreferenceOut[] | null>(null);
  const [auditEvents, setAuditEvents] = useState<AuditEventOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    if (sessionId === null) return;
    listMyWorkspaces(sessionId)
      .then((workspaces) => {
        const match = workspaces.find((w) => w.customer_id === customerId);
        if (match) setCustomerName(match.customer_name);
      })
      .catch(() => {});
    getCustomerKillSwitch(sessionId, customerId).then(setKillSwitch).catch(() => {});
    listCustomerMembers(sessionId, customerId)
      .then(setMembers)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Yuklab bo'lmadi."));
    listCustomerNotifications(sessionId, customerId).then(setNotifications).catch(() => {});
    listNotificationPreferences(sessionId, customerId).then(setPreferences).catch(() => {});
    listCustomerAudit(sessionId, customerId).then(setAuditEvents).catch(() => {});
  }, [sessionId, customerId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleEngageKillSwitch(event: FormEvent) {
    event.preventDefault();
    if (sessionId === null || killSwitchReason.trim().length === 0) return;
    try {
      await engageCustomerKillSwitch(sessionId, customerId, killSwitchReason.trim());
      setKillSwitchReason("");
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Kill switch'ni yoqib bo'lmadi.");
    }
  }

  async function handleDisengageKillSwitch() {
    if (sessionId === null) return;
    try {
      await disengageCustomerKillSwitch(sessionId, customerId);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Kill switch'ni o'chirib bo'lmadi.");
    }
  }

  async function handleInviteMember(event: FormEvent) {
    event.preventDefault();
    if (sessionId === null || newMemberUserId.trim().length === 0) return;
    try {
      await inviteCustomerMember(sessionId, customerId, newMemberUserId.trim(), newMemberRole);
      setNewMemberUserId("");
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "A'zo qo'shib bo'lmadi.");
    }
  }

  async function handleChangeMemberRole(member: CustomerMemberOut, role: CustomerRole) {
    if (sessionId === null || role === member.role) return;
    try {
      await changeCustomerMemberRole(sessionId, customerId, member.membership_id, role);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Rolni o'zgartirib bo'lmadi.");
    }
  }

  async function handleRemoveMember(member: CustomerMemberOut) {
    if (sessionId === null) return;
    try {
      await removeCustomerMember(sessionId, customerId, member.membership_id);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "A'zoni chiqarib bo'lmadi.");
    }
  }

  async function handleMarkRead(notification: NotificationOut) {
    if (sessionId === null) return;
    await markCustomerNotificationRead(sessionId, customerId, notification.id).catch(() => {});
    refresh();
  }

  async function handleTogglePreference(preference: NotificationPreferenceOut) {
    if (sessionId === null || preference.notification_type === ALWAYS_ON_NOTIFICATION_TYPE) return;
    try {
      await setNotificationPreference(
        sessionId,
        customerId,
        preference.notification_type,
        !preference.enabled,
      );
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sozlamani o'zgartirib bo'lmadi.");
    }
  }

  if (sessionId === null) return null;

  return (
    <main className="mx-auto w-full max-w-3xl flex-1 space-y-8 p-6">
      <div>
        <Link href="/workspaces" className="text-sm text-gray-500 hover:text-black">
          &larr; Workspace&apos;lar
        </Link>
      </div>

      <h1 className="text-xl font-semibold">{customerName ?? "Customer"}</h1>

      {error && <p className="text-sm text-red-600">{error}</p>}

      <section>
        <h2 className="mb-3 text-lg font-semibold">Kill switch</h2>
        {killSwitch?.engaged ? (
          <div className="space-y-2 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900">
            <p>
              <strong>Faol.</strong> Sabab: {killSwitch.reason}
            </p>
            <button
              onClick={handleDisengageKillSwitch}
              className="rounded-md bg-red-600 px-3 py-1.5 text-xs font-medium text-white"
            >
              O&apos;chirish
            </button>
          </div>
        ) : (
          <form onSubmit={handleEngageKillSwitch} className="flex gap-2">
            <input
              type="text"
              value={killSwitchReason}
              onChange={(event) => setKillSwitchReason(event.target.value)}
              placeholder="Sabab"
              className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-black focus:outline-none"
            />
            <button
              type="submit"
              disabled={killSwitchReason.trim().length === 0}
              className="rounded-md bg-red-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              Yoqish
            </button>
          </form>
        )}
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">A&apos;zolar</h2>
        <form onSubmit={handleInviteMember} className="mb-3 flex gap-2">
          <input
            type="text"
            value={newMemberUserId}
            onChange={(event) => setNewMemberUserId(event.target.value)}
            placeholder="User ID (UUID)"
            className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-black focus:outline-none"
          />
          <select
            value={newMemberRole}
            onChange={(event) => setNewMemberRole(event.target.value as CustomerRole)}
            className="rounded-md border border-gray-300 px-2 py-2 text-sm"
          >
            {CUSTOMER_ROLES.map((role) => (
              <option key={role} value={role}>
                {role}
              </option>
            ))}
          </select>
          <button
            type="submit"
            disabled={newMemberUserId.trim().length === 0}
            className="rounded-md bg-black px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            Qo&apos;shish
          </button>
        </form>
        <ul className="space-y-1">
          {members?.map((member) => (
            <li key={member.membership_id} className="flex items-center justify-between text-sm">
              <span>{member.display_name}</span>
              <div className="flex items-center gap-2">
                <select
                  value={member.role}
                  onChange={(event) => handleChangeMemberRole(member, event.target.value as CustomerRole)}
                  className="rounded border border-gray-200 bg-gray-100 px-1 py-0.5 text-xs text-gray-600"
                >
                  {CUSTOMER_ROLES.map((role) => (
                    <option key={role} value={role}>
                      {role}
                    </option>
                  ))}
                </select>
                <button
                  onClick={() => handleRemoveMember(member)}
                  className="text-xs text-red-600 hover:underline"
                >
                  Chiqarish
                </button>
              </div>
            </li>
          ))}
          {members !== null && members.length === 0 && (
            <p className="text-sm text-gray-500">A&apos;zo yo&apos;q.</p>
          )}
        </ul>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">Bildirishnoma sozlamalari</h2>
        <ul className="space-y-1">
          {preferences?.map((preference) => (
            <li
              key={preference.notification_type}
              className="flex items-center justify-between text-sm"
            >
              <span>{preference.notification_type}</span>
              {preference.notification_type === ALWAYS_ON_NOTIFICATION_TYPE ? (
                <span className="text-xs text-gray-500">doim yoqilgan</span>
              ) : (
                <button
                  onClick={() => handleTogglePreference(preference)}
                  className="text-xs text-blue-600 hover:underline"
                >
                  {preference.enabled ? "O'chirish" : "Yoqish"}
                </button>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">Bildirishnomalar (barcha workspace)</h2>
        <ul className="space-y-2">
          {notifications?.map((notification) => (
            <li
              key={notification.id}
              className="flex items-center justify-between rounded-md border border-gray-200 px-3 py-2 text-sm"
            >
              <span className={notification.read_at ? "text-gray-400" : ""}>
                {notification.notification_type} — {notification.reference_type}
              </span>
              {!notification.read_at && (
                <button
                  onClick={() => handleMarkRead(notification)}
                  className="text-xs text-blue-600 hover:underline"
                >
                  O&apos;qildi deb belgilash
                </button>
              )}
            </li>
          ))}
          {notifications !== null && notifications.length === 0 && (
            <p className="text-sm text-gray-500">Bildirishnoma yo&apos;q.</p>
          )}
        </ul>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">Audit</h2>
        <ul className="space-y-2">
          {auditEvents?.map((event) => (
            <li key={event.id} className="rounded-md border border-gray-200 px-3 py-2 text-sm">
              <div className="flex items-center justify-between">
                <span className="font-medium">{event.event_type}</span>
                <span className="text-xs text-gray-500">
                  {new Date(event.occurred_at).toLocaleString()}
                </span>
              </div>
              <div className="text-xs text-gray-500">{event.actor_id}</div>
            </li>
          ))}
          {auditEvents !== null && auditEvents.length === 0 && (
            <p className="text-sm text-gray-500">Audit yozuvi yo&apos;q.</p>
          )}
        </ul>
      </section>
    </main>
  );
}
