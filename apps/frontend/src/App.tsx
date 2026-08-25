import { cn } from '@/lib/utils'

const apiMode = import.meta.env.VITE_API_MODE === 'mock' ? 'mock' : 'real'

function App() {
  return (
    <main
      className={cn(
        'flex min-h-screen flex-col items-center justify-center gap-2 bg-neutral-950 font-mono text-sm text-neutral-300',
      )}
    >
      <p className="text-base text-neutral-100">Asuna Debug Console</p>
      <p>scaffold ready</p>
      <p>
        apiMode = {apiMode}
      </p>
    </main>
  )
}

export default App
