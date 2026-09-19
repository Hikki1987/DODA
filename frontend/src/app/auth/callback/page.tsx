import { Suspense } from "react";
import CallbackHandler from "./CallbackHandler";

export default function AuthCallbackPage() {
  return (
    <main className="flex flex-1 items-center justify-center p-6">
      <Suspense fallback={<p className="text-sm text-gray-500">Kirish tasdiqlanmoqda...</p>}>
        <CallbackHandler />
      </Suspense>
    </main>
  );
}
