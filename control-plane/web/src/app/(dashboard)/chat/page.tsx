"use client";

import React from "react";
import { ChatPanel } from "@/components/ChatPanel";

export default function ChatRoutePage() {
  return (
    <div className="border border-zinc-900 rounded-lg overflow-hidden bg-zinc-900/10 flex flex-col h-[600px] max-w-xl mx-auto">
      <ChatPanel />
    </div>
  );
}
