import type { LlmProfileDto } from "@/types/backend/llm"

function LlmProfileSelect({
  options,
  value,
  onChange,
}: {
  options: LlmProfileDto[]
  value: string | null
  onChange(profileId: string): void
}) {
  return (
    <select
      data-testid="llm-profile-select"
      title="切换模型后，下一条消息开始生效"
      className="max-w-[220px] cursor-pointer truncate rounded border border-border bg-transparent px-2 py-1 font-mono text-xs text-muted-foreground hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
      value={value ?? ""}
      onChange={(event) => onChange(event.target.value)}
    >
      {options.map((profile) => (
        <option key={profile.id} value={profile.id}>
          {profile.label}
        </option>
      ))}
    </select>
  )
}

export { LlmProfileSelect }