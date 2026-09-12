"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ApiError,
  changeCustomerMemberRole,
  clearMyAiPreference,
  disengageCustomerKillSwitch,
  engageCustomerKillSwitch,
  getAiFallbackSetting,
  getCustomerKillSwitch,
  getMyAiPreference,
  inviteCustomerMember,
  listArchivedWorkspaces,
  listCustomerAudit,
  listCustomerMembers,
  listCustomerNotifications,
  listMyCustomers,
  listNotificationPreferences,
  listProviderStatuses,
  markCustomerNotificationRead,
  removeCustomerMember,
  restoreWorkspace,
  setAiFallbackSetting,
  setMyAiPreference,
  setNotificationPreference,
  setProviderEnabled,
  testProviderConnection,
  verifyCustomerAuditChain,
  AI_PROVIDERS,
  type AiFallbackSettingOut,
  type AiPreferenceOut,
  type AiProvider,
  type AuditChainVerificationOut,
  type AuditEventOut,
  type CustomerMemberOut,
  type CustomerRole,
  type KillSwitchStatusOut,
  type NotificationOut,
  type NotificationPreferenceOut,
  type NotificationType,
  type ProviderStatusOut,
  type WorkspaceOut,
} from "@/lib/api";
import { KillSwitchPanel } from "@/components/KillSwitchPanel";
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
  const [engagingKillSwitch, setEngagingKillSwitch] = useState(false);
  const [invitingMember, setInvitingMember] = useState(false);
  const [notifications, setNotifications] = useState<NotificationOut[] | null>(null);
  const [preferences, setPreferences] = useState<NotificationPreferenceOut[] | null>(null);
  const [auditEvents, setAuditEvents] = useState<AuditEventOut[] | null>(null);
  const [chainVerification, setChainVerification] = useState<AuditChainVerificationOut | null>(null);
  const [verifyingChain, setVerifyingChain] = useState(false);
  const [archivedWorkspaces, setArchivedWorkspaces] = useState<WorkspaceOut[] | null>(null);
  const [restoringWorkspaceId, setRestoringWorkspaceId] = useState<string | null>(null);
  const [providerStatuses, setProviderStatuses] = useState<ProviderStatusOut[] | null>(null);
  const [testingProvider, setTestingProvider] = useState<string | null>(null);
  const [fallbackSetting, setFallbackSetting] = useState<AiFallbackSettingOut | null>(null);
  const [togglingFallback, setTogglingFallback] = useState(false);
  const [myAiPreference, setMyAiPreferenceState] = useState<AiPreferenceOut | null>(null);
  const [myAiProviderChoice, setMyAiProviderChoice] = useState<AiProvider>("OPENAI");
  const [myAiModelChoice, setMyAiModelChoice] = useState("");
  const [savingMyAiPreference, setSavingMyAiPreference] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    if (sessionId === null) return;
    // Name comes from /v1/me/customers, not /v1/me/workspaces: the latter is
    // workspace-shaped, so for a member holding no workspace role (an auditor,
    // read-only by design) or a customer with no unarchived workspaces it has
    // no row to read the name from, and this page — the only place their access
    // lives — would head itself "Customer".
    listMyCustomers(sessionId)
      .then((customers) => {
        const match = customers.find((c) => c.customer_id === customerId);
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
    // CustomerOwner-only (authorize_view_archived_workspaces) — a plain
    // member/auditor gets 403 here, so this fails silently like the other
    // optional sections above rather than surfacing a spurious error.
    listArchivedWorkspaces(sessionId, customerId).then(setArchivedWorkspaces).catch(() => {});
    listProviderStatuses(sessionId, customerId).then(setProviderStatuses).catch(() => {});
    getAiFallbackSetting(sessionId, customerId).then(setFallbackSetting).catch(() => {});
    getMyAiPreference(sessionId, customerId).then(setMyAiPreferenceState).catch(() => {});
  }, [sessionId, customerId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleEngageKillSwitch(event: FormEvent) {
    event.preventDefault();
    if (sessionId === null || killSwitchReason.trim().length === 0 || engagingKillSwitch) return;
    setEngagingKillSwitch(true);
    try {
      await engageCustomerKillSwitch(sessionId, customerId, killSwitchReason.trim());
      setKillSwitchReason("");
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Kill switch'ni yoqib bo'lmadi.");
    } finally {
      setEngagingKillSwitch(false);
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
    if (sessionId === null || newMemberUserId.trim().length === 0 || invitingMember) return;
    setInvitingMember(true);
    try {
      await inviteCustomerMember(sessionId, customerId, newMemberUserId.trim(), newMemberRole);
      setNewMemberUserId("");
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "A'zo qo'shib bo'lmadi.");
    } finally {
      setInvitingMember(false);
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

  async function handleRestoreWorkspace(workspace: WorkspaceOut) {
    if (sessionId === null || restoringWorkspaceId !== null) return;
    setRestoringWorkspaceId(workspace.id);
    try {
      await restoreWorkspace(sessionId, workspace.id);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Workspace'ni tiklab bo'lmadi.");
    } finally {
      setRestoringWorkspaceId(null);
    }
  }

  async function handleVerifyChain() {
    if (sessionId === null || verifyingChain) return;
    setVerifyingChain(true);
    try {
      const result = await verifyCustomerAuditChain(sessionId, customerId);
      setChainVerification(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Zanjirni tekshirib bo'lmadi.");
    } finally {
      setVerifyingChain(false);
    }
  }

  async function handleMarkRead(notification: NotificationOut) {
    if (sessionId === null) return;
    await markCustomerNotificationRead(sessionId, customerId, notification.id).catch(() => {});
    refresh();
  }

  async function handleToggleProviderEnabled(provider: ProviderStatusOut) {
    if (sessionId === null) return;
    try {
      await setProviderEnabled(sessionId, customerId, provider.provider, !provider.enabled);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Provayderni o'zgartirib bo'lmadi.");
    }
  }

  async function handleTestProviderConnection(provider: ProviderStatusOut) {
    if (sessionId === null || testingProvider !== null) return;
    setTestingProvider(provider.provider);
    try {
      await testProviderConnection(sessionId, customerId, provider.provider);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Ulanishni tekshirib bo'lmadi.");
    } finally {
      setTestingProvider(null);
    }
  }

  async function handleToggleFallback() {
    if (sessionId === null || fallbackSetting === null || togglingFallback) return;
    setTogglingFallback(true);
    try {
      const updated = await setAiFallbackSetting(sessionId, customerId, !fallbackSetting.enabled);
      setFallbackSetting(updated);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Fallback sozlamasini o'zgartirib bo'lmadi.");
    } finally {
      setTogglingFallback(false);
    }
  }

  async function handleSetMyAiPreference(event: FormEvent) {
    event.preventDefault();
    if (sessionId === null || savingMyAiPreference) return;
    setSavingMyAiPreference(true);
    try {
      const updated = await setMyAiPreference(
        sessionId,
        customerId,
        myAiProviderChoice,
        myAiModelChoice.trim().length > 0 ? myAiModelChoice.trim() : null,
      );
      setMyAiPreferenceState(updated);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "AI afzalligini saqlab bo'lmadi.");
    } finally {
      setSavingMyAiPreference(false);
    }
  }

  async function handleClearMyAiPreference() {
    if (sessionId === null || savingMyAiPreference) return;
    setSavingMyAiPreference(true);
    try {
      await clearMyAiPreference(sessionId, customerId);
      setMyAiPreferenceState({ provider: null, model: null });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "AI afzalligini tozalab bo'lmadi.");
    } finally {
      setSavingMyAiPreference(false);
    }
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

      <KillSwitchPanel
        killSwitch={killSwitch}
        reason={killSwitchReason}
        onReasonChange={setKillSwitchReason}
        engaging={engagingKillSwitch}
        onEngage={handleEngageKillSwitch}
        onDisengage={handleDisengageKillSwitch}
      />

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
            aria-label="Yangi a'zo roli"
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
            disabled={newMemberUserId.trim().length === 0 || invitingMember}
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
                  aria-label={`${member.display_name} roli`}
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
            <li className="text-sm text-gray-500">A&apos;zo yo&apos;q.</li>
          )}
        </ul>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">AI provayderlar</h2>
        <ul className="space-y-2">
          {providerStatuses?.map((provider) => (
            <li
              key={provider.provider}
              className="flex items-center justify-between rounded-md border border-gray-200 px-3 py-2 text-sm"
            >
              <div className="flex flex-col">
                <span className="font-medium">{provider.provider}</span>
                <span className="text-xs text-gray-500">
                  {provider.configured ? "sozlangan" : "kalit yo'q"}
                  {provider.verified_at !== null &&
                    (provider.verified_ok
                      ? " · tekshirilgan: ishlaydi"
                      : ` · tekshirilgan: ${provider.verified_error ?? "xato"}`)}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => handleTestProviderConnection(provider)}
                  disabled={testingProvider !== null}
                  className="text-xs text-blue-600 hover:underline disabled:opacity-50"
                >
                  {testingProvider === provider.provider ? "Tekshirilmoqda..." : "Ulanishni tekshirish"}
                </button>
                <button
                  onClick={() => handleToggleProviderEnabled(provider)}
                  className="text-xs text-gray-700 hover:underline"
                >
                  {provider.enabled ? "O'chirish" : "Yoqish"}
                </button>
              </div>
            </li>
          ))}
          {providerStatuses !== null && providerStatuses.length === 0 && (
            <li className="text-sm text-gray-500">Provayder ma&apos;lumoti yo&apos;q.</li>
          )}
        </ul>
        {fallbackSetting !== null && (
          <div className="mt-3 flex items-center justify-between rounded-md border border-gray-200 px-3 py-2 text-sm">
            <div className="flex flex-col">
              <span>Avtomatik fallback</span>
              <span className="text-xs text-gray-500">
                Vaqtinchalik provayder xatosida (timeout/rate-limit) boshqa provayderga avtomatik o&apos;tish.
                Standart — o&apos;chirilgan.
              </span>
            </div>
            <button
              onClick={handleToggleFallback}
              disabled={togglingFallback}
              className="text-xs text-blue-600 hover:underline disabled:opacity-50"
            >
              {fallbackSetting.enabled ? "O'chirish" : "Yoqish"}
            </button>
          </div>
        )}

        {myAiPreference !== null && (
          <form onSubmit={handleSetMyAiPreference} className="mt-3 flex items-center gap-2 text-xs">
            <span className="text-gray-500">
              Mening AI afzalligim ({myAiPreference.provider ?? "tizim standart"}
              {myAiPreference.model ? ` / ${myAiPreference.model}` : ""}):
            </span>
            <select
              aria-label="Mening AI provayderim"
              value={myAiProviderChoice}
              onChange={(event) => setMyAiProviderChoice(event.target.value as AiProvider)}
              className="rounded border border-gray-200 bg-gray-50 px-1 py-1"
            >
              {AI_PROVIDERS.map((provider) => (
                <option key={provider} value={provider}>
                  {provider}
                </option>
              ))}
            </select>
            <input
              type="text"
              value={myAiModelChoice}
              onChange={(event) => setMyAiModelChoice(event.target.value)}
              placeholder="model (ixtiyoriy)"
              className="w-32 rounded border border-gray-200 px-1 py-1"
            />
            <button
              type="submit"
              disabled={savingMyAiPreference}
              className="rounded border border-gray-300 px-2 py-1 font-medium text-gray-700 disabled:opacity-50"
            >
              Saqlash
            </button>
            {myAiPreference.provider !== null && (
              <button
                type="button"
                onClick={handleClearMyAiPreference}
                disabled={savingMyAiPreference}
                className="text-red-600 hover:underline disabled:opacity-50"
              >
                Tizim standartga qaytarish
              </button>
            )}
          </form>
        )}
      </section>

      {archivedWorkspaces !== null && archivedWorkspaces.length > 0 && (
        <section>
          <h2 className="mb-3 text-lg font-semibold">Arxivlangan workspace&apos;lar</h2>
          <ul className="space-y-1">
            {archivedWorkspaces.map((workspace) => (
              <li key={workspace.id} className="flex items-center justify-between text-sm">
                <span className="text-gray-500">{workspace.name}</span>
                <button
                  onClick={() => handleRestoreWorkspace(workspace)}
                  disabled={restoringWorkspaceId === workspace.id}
                  className="text-xs text-blue-600 hover:underline disabled:opacity-50"
                >
                  Tiklash
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

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
            <li className="text-sm text-gray-500">Bildirishnoma yo&apos;q.</li>
          )}
        </ul>
      </section>

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Audit</h2>
          <button
            onClick={handleVerifyChain}
            disabled={verifyingChain}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 disabled:opacity-50"
          >
            {verifyingChain ? "Tekshirilmoqda..." : "Zanjirni tekshirish"}
          </button>
        </div>
        {chainVerification && (
          <div
            className={`mb-3 rounded-md border p-3 text-sm ${
              chainVerification.ok
                ? "border-green-300 bg-green-50 text-green-900"
                : "border-red-300 bg-red-50 text-red-900"
            }`}
          >
            {chainVerification.ok ? (
              <p>
                Zanjir sog&apos;lom — {chainVerification.checked_count} ta yozuv tekshirildi, buzilish
                topilmadi.
              </p>
            ) : (
              <p>
                {chainVerification.violations.length} ta buzilish topildi ({chainVerification.checked_count}{" "}
                ta yozuvdan)!
              </p>
            )}
          </div>
        )}
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
            <li className="text-sm text-gray-500">Audit yozuvi yo&apos;q.</li>
          )}
        </ul>
      </section>
    </main>
  );
}
