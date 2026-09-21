import type { FormEvent } from "react";
import type { KillSwitchStatusOut } from "@/lib/api";

interface KillSwitchPanelProps {
  killSwitch: KillSwitchStatusOut | null;
  reason: string;
  onReasonChange: (reason: string) => void;
  engaging: boolean;
  onEngage: (event: FormEvent) => void;
  onDisengage: () => void;
  /** Extra sentence after the reason when engaged — workspace and customer
   * scope word this slightly differently ("Yangi action'lar bloklangan"). */
  blockedNote?: string;
}

/** FR-CTL-003 kill switch, shared between the workspace (workspace_admin
 * scope) and customer (customer_owner scope) pages — same engage/disengage
 * form and banner, differing only in which API calls the caller wires up. */
export function KillSwitchPanel({
  killSwitch,
  reason,
  onReasonChange,
  engaging,
  onEngage,
  onDisengage,
  blockedNote,
}: KillSwitchPanelProps) {
  return (
    <section>
      <h2 className="mb-3 text-lg font-semibold">Kill switch</h2>
      {killSwitch?.engaged ? (
        <div className="space-y-2 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900">
          <p>
            <strong>Faol.</strong> Sabab: {killSwitch.reason}
            {blockedNote ? `. ${blockedNote}` : ""}
          </p>
          <button
            onClick={onDisengage}
            className="rounded-md bg-red-600 px-3 py-1.5 text-xs font-medium text-white"
          >
            O&apos;chirish
          </button>
        </div>
      ) : (
        <form onSubmit={onEngage} className="flex gap-2">
          <input
            type="text"
            value={reason}
            onChange={(event) => onReasonChange(event.target.value)}
            placeholder="Sabab"
            className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-black focus:outline-none"
          />
          <button
            type="submit"
            disabled={reason.trim().length === 0 || engaging}
            className="rounded-md bg-red-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            Yoqish
          </button>
        </form>
      )}
    </section>
  );
}
