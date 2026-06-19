import { redirect } from "next/navigation";

// The conversational chat has been replaced by the explicit Operator Actions panel.
// Redirect any stale links to the Operations Queue.
export default function ChatRoutePage() {
  redirect("/ops");
}
