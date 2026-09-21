"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getStoredSessionId } from "@/lib/session";

export default function RootPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace(getStoredSessionId() ? "/workspaces" : "/login");
  }, [router]);

  return null;
}
