// Shared AI helper. NVIDIA (OpenAI-compatible) is the primary provider when
// NVIDIA_API_KEY is set; Lovable AI Gateway is the fallback. Every AI call in
// the app should route through here so switching providers is a one-file change.

export type ChatMessage = { role: "system" | "user" | "assistant"; content: string };

export type CallAIOptions = {
  model?: string;
  temperature?: number;
  maxTokens?: number;
};

export async function callAI(messages: ChatMessage[], opts: CallAIOptions = {}): Promise<string> {
  const nvidiaKey = process.env.NVIDIA_API_KEY;
  const useNvidia = Boolean(nvidiaKey);
  const apiKey = useNvidia ? nvidiaKey! : process.env.LOVABLE_API_KEY;
  if (!apiKey) throw new Error("No AI provider key set (NVIDIA_API_KEY or LOVABLE_API_KEY)");

  const url = useNvidia
    ? "https://integrate.api.nvidia.com/v1/chat/completions"
    : "https://ai.gateway.lovable.dev/v1/chat/completions";
  const model =
    opts.model ?? (useNvidia ? "meta/llama-3.1-70b-instruct" : "google/gemini-2.5-flash");

  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model,
      messages,
      temperature: opts.temperature ?? 0.7,
      max_tokens: opts.maxTokens ?? 800,
    }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(
      `${useNvidia ? "NVIDIA" : "Lovable AI"} error ${res.status}: ${text.slice(0, 200)}`,
    );
  }
  const json = (await res.json()) as { choices?: Array<{ message?: { content?: string } }> };
  return json.choices?.[0]?.message?.content?.trim() ?? "";
}

export function aiProviderName(): "nvidia" | "lovable" | "none" {
  if (process.env.NVIDIA_API_KEY) return "nvidia";
  if (process.env.LOVABLE_API_KEY) return "lovable";
  return "none";
}
