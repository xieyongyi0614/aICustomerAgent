import type { ReactNode } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import {
  Drawer,
  DrawerContent,
  DrawerDescription,
  DrawerHeader,
  DrawerTitle,
  DrawerTrigger,
} from "@/components/ui/drawer"
import { Input } from "@/components/ui/input"
import { Progress } from "@/components/ui/progress"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { MeterBar } from "@/components/ui/meter-bar"
import {
  BEHAVIOR_VALUES,
  DEGRADED_BADGE_CLASS,
  EMOTION_VALUES,
  MODE_VALUES,
  STAGE_VALUES,
  enumBadgeClass,
} from "@/lib/enum-colors"
import { cn } from "@/lib/utils"

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-mono text-sm text-muted-foreground">{title}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">{children}</CardContent>
    </Card>
  )
}

function BadgeGroup({ kind, values }: { kind: "mode" | "emotion" | "behavior" | "stage"; values: readonly string[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {values.map((value) => (
        <Badge key={value} variant="outline" className={enumBadgeClass(kind, value)}>
          {value}
        </Badge>
      ))}
      <Badge variant="outline" className={DEGRADED_BADGE_CLASS}>
        degraded
      </Badge>
      <Badge variant="outline" className={cn(enumBadgeClass(kind, "__unknown__"))}>
        __unknown__
      </Badge>
    </div>
  )
}

function TokenDemoPage() {
  return (
    <TooltipProvider>
      <main className="mx-auto flex min-h-screen max-w-4xl flex-col gap-4 p-6">
        <header className="flex items-baseline justify-between">
          <h1 className="text-lg font-semibold">Design Tokens Demo</h1>
          <p className="font-mono text-xs text-fg-tertiary">dev only · hash #demo</p>
        </header>

        <Section title="surfaces & borders">
          <div className="grid grid-cols-2 gap-2 font-mono text-xs sm:grid-cols-4">
            <div className="rounded-md border border-border bg-background p-3">background</div>
            <div className="rounded-md border border-border bg-card p-3">card</div>
            <div className="rounded-md border border-border bg-muted p-3">muted</div>
            <div className="rounded-md border border-border bg-accent p-3">accent</div>
          </div>
          <div className="flex flex-col gap-1 text-sm">
            <span>foreground 一级文本</span>
            <span className="text-muted-foreground">muted-foreground 二级文本</span>
            <span className="text-fg-tertiary">fg-tertiary 三级文本</span>
          </div>
          <p className="font-mono text-sm">mono 123ms · 0.735 · session_id=8f3a</p>
        </Section>

        <Section title="status colors">
          <div className="flex flex-wrap gap-2 font-mono text-xs">
            <span className="inline-flex items-center gap-1.5">
              <span className="size-2 rounded-full bg-status-ok" /> ok
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="size-2 rounded-full bg-status-warn" /> warn / degraded
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="size-2 rounded-full bg-status-error" /> error
            </span>
          </div>
        </Section>

        <Section title="enum badges">
          <div className="flex flex-col gap-2">
            <BadgeGroup kind="mode" values={MODE_VALUES} />
            <BadgeGroup kind="emotion" values={EMOTION_VALUES} />
            <BadgeGroup kind="behavior" values={BEHAVIOR_VALUES} />
            <BadgeGroup kind="stage" values={STAGE_VALUES} />
          </div>
        </Section>

        <Section title="meter bar (ticks at 0.35 / 0.55 / 0.75)">
          <MeterBar value={0.62} ticks={[0.35]} toneClassName="bg-sky-400" />
          <MeterBar value={0.48} ticks={[0.55, 0.75]} toneClassName="bg-violet-400" />
          <MeterBar value={0.82} ticks={[0.75]} toneClassName="bg-pink-400" />
          <MeterBar value={1.4} ticks={[0.9]} toneClassName="bg-emerald-400" />
          <Progress value={62} />
        </Section>

        <Section title="shadcn components">
          <Tabs defaultValue="a">
            <TabsList>
              <TabsTrigger value="a">tab-a</TabsTrigger>
              <TabsTrigger value="b">tab-b</TabsTrigger>
            </TabsList>
            <TabsContent value="a">
              <p className="text-sm text-muted-foreground">tabs content a</p>
            </TabsContent>
            <TabsContent value="b">
              <p className="text-sm text-muted-foreground">tabs content b</p>
            </TabsContent>
          </Tabs>

          <ScrollArea className="h-24 rounded-md border border-border p-2">
            {Array.from({ length: 12 }, (_, i) => (
              <p key={i} className="font-mono text-xs text-muted-foreground">
                scroll item {i}
              </p>
            ))}
          </ScrollArea>

          <Input placeholder="input" />
          <Textarea placeholder="textarea" rows={2} />

          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm">send</Button>
            <Button size="sm" variant="secondary">
              secondary
            </Button>
            <Button size="sm" variant="outline">
              outline
            </Button>
            <Button size="sm" variant="ghost">
              ghost
            </Button>
            <Button size="sm" variant="destructive">
              destructive
            </Button>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Dialog>
              <DialogTrigger render={<Button size="sm" variant="outline" />}>dialog</DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>清空会话</DialogTitle>
                  <DialogDescription>dialog sample</DialogDescription>
                </DialogHeader>
              </DialogContent>
            </Dialog>

            <Drawer>
              <DrawerTrigger render={<Button size="sm" variant="outline" />}>drawer</DrawerTrigger>
              <DrawerContent>
                <DrawerHeader>
                  <DrawerTitle>Debug Pane</DrawerTitle>
                  <DrawerDescription>drawer sample</DrawerDescription>
                </DrawerHeader>
              </DrawerContent>
            </Drawer>

            <Tooltip>
              <TooltipTrigger render={<Button size="sm" variant="ghost" />}>tooltip</TooltipTrigger>
              <TooltipContent>tooltip sample</TooltipContent>
            </Tooltip>
          </div>
        </Section>
      </main>
    </TooltipProvider>
  )
}

export { TokenDemoPage }
