import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import {
  clearStoredToken,
  getStoredToken,
  setStoredToken,
} from "@/api/auth-token"
import { fetchMe, type MeDto } from "@/api/auth"

function IdentityDialog() {
  const [open, setOpen] = useState(false)
  const [me, setMe] = useState<MeDto | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState("")

  useEffect(() => {
    if (!open) return
    const token = getStoredToken()
    setDraft(token ?? "")
    if (!token) {
      setMe(null)
      setError(null)
      return
    }
    fetchMe()
      .then((result) => {
        setMe(result)
        setError(null)
      })
      .catch((err: Error) => {
        setMe(null)
        setError(err.message)
      })
  }, [open])

  function save(): void {
    if (draft.trim().length === 0) return
    setStoredToken(draft)
    fetchMe()
      .then((result) => {
        setMe(result)
        setError(null)
      })
      .catch((err: Error) => {
        setMe(null)
        setError(err.message)
      })
  }

  function clear(): void {
    clearStoredToken()
    setDraft("")
    setMe(null)
    setError(null)
  }

  const label = me ? me.user_id : getStoredToken() ? "token 无效" : "未登录"

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
      }}
    >
      <DialogTrigger
        render={
          <Button
            variant="outline"
            size="sm"
            data-testid="identity-trigger"
            className="max-w-[160px] font-mono text-xs"
          >
            {label}
          </Button>
        }
      >
        {label}
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="text-sm">身份（Bearer token）</DialogTitle>
          <DialogDescription>
            产品端点的 user_id 一律从 token 解析。粘贴 /auth/email/verify 返回的
            token 后保存；留空并清除即回到匿名（仅调试端点可用）。
          </DialogDescription>
        </DialogHeader>
        <Input
          data-testid="identity-token"
          value={draft}
          spellCheck={false}
          placeholder="user_id.device_id.exp.sig"
          className="font-mono text-xs"
          onChange={(e) => setDraft(e.target.value)}
        />
        {me !== null && (
          <div className="font-mono text-xs" data-testid="identity-me">
            user_id: {me.user_id} · device: {me.device_id} · 过期:{" "}
            {new Date(me.expires_at).toLocaleString()}
          </div>
        )}
        {error !== null && (
          <div className="text-xs text-status-error" data-testid="identity-error">
            {error}
          </div>
        )}
        <DialogFooter>
          <Button variant="ghost" size="sm" data-testid="identity-clear" onClick={clear}>
            清除
          </Button>
          <Button size="sm" data-testid="identity-save" onClick={save}>
            保存
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export { IdentityDialog }
