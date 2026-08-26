import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { JsonViewer } from "@/features/json-viewer/json-viewer"
import { isTraceNotFound, useTurnTrace } from "@/hooks/use-observability"
import { useChatStore } from "@/stores/chat-store"
import { useUiStore } from "@/stores/ui-store"

function RawSection({ title, data }: { title: string; data: unknown }) {
  return (
    <Card>
      <CardHeader className="pb-1">
        <CardTitle className="font-mono text-xs">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <JsonViewer data={data} />
      </CardContent>
    </Card>
  )
}

function RawPanel() {
  const selectedTurnId = useUiStore((s) => s.selectedTurnId)
  const messages = useChatStore((s) => s.messages)
  const turnMeta = useChatStore((s) => s.turnMeta)
  const sessionId = useChatStore((s) => s.sessionId)
  const traceQuery = useTurnTrace(selectedTurnId)

  const requestPayload =
    selectedTurnId === null
      ? null
      : {
          turn_id: selectedTurnId,
          session_id: sessionId,
          endpoint: "/api/v1/chat/message",
        }

  return (
    <div data-testid="raw-panel" className="flex flex-col gap-3">
      <RawSection title="① 请求 / 会话终稿" data={requestPayload ?? { note: "尚无轮次" }} />
      <RawSection title="② turn_meta（实际生效值）" data={turnMeta} />
      <RawSection
        title="③ turn trace 快照"
        data={
          traceQuery.data ??
          (traceQuery.error && isTraceNotFound(traceQuery.error)
            ? { note: "该轮数据已被清理" }
            : { note: "加载中…" })
        }
      />
      <RawSection title="④ 消息终稿（本轮会话）" data={messages} />
    </div>
  )
}

export { RawPanel }
