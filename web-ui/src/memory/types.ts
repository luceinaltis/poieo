export type MemorySearchMode = "words" | "meaning"

export interface MemoryNode {
  slug: string
  preview: string
  updated_at: string
  scope: string[]
  anchors: string[]
  standing: boolean
  superseded_by: string | null
  second_look: string[]
  degree: number
}

export type MemoryEdgeKind = "mentions" | "depends_on" | "contradicts" | "supersedes"

export interface MemoryEdge {
  source: string
  target: string
  kind: MemoryEdgeKind
  strength: number
}

export interface MemoryGraph {
  nodes: MemoryNode[]
  edges: MemoryEdge[]
  total_nodes: number
  total_edges: number
  truncated: boolean
  edges_truncated: boolean
}

/**
 * One learning pass, exactly as the pass log records it. A failed pass is
 * still a pass: `error` says why, and the same records are read again next
 * time. `dropped` holds the reason each proposal was let go.
 */
export interface LearningPass {
  at: string
  read: number
  upto: string | null
  kept: string[]
  set_aside: string[]
  dropped: string[]
  error: string | null
  page: string | null
  /** How big the question was and the window it faced; null where nobody said. */
  prompt_chars?: number | null
  prompt_tokens?: number | null
  context?: number | null
  let_go: string[]
}

export interface MemoryOverview {
  /** Opaque validator used only while this memory place remains open. */
  revision?: string
  enabled: boolean
  /** The page as a run sees it: comments stripped, empty as null. */
  page: string | null
  /** The page as a person wrote it, for editing. */
  page_text: string
  /** The line the last learning pass suggested for the page, until a person writes the page. */
  suggestion: string | null
  stats: {
    page_chars: number
    page_budget: number
    kept: number
    set_aside: number
    lookup: string
    disagreements: string[][]
    second_look: Array<{ slug: string; reason: string }>
  } | null
  capabilities: { words: boolean; meaning: boolean; ask: boolean }
  graph: MemoryGraph
  /** The last few passes, newest first. Absent from an older daemon. */
  learning?: LearningPass[]
  /** The learner's next question, sized now, against the window it will face. */
  learner?: {
    prompt_chars: number
    entries: number
    model: string | null
    context: number | null
  } | null
}

export interface MemoryResult {
  slug: string
  preview: string
  updated_at: string
  standing: boolean
  mode: MemorySearchMode
  rank: number
  score?: number
  channels?: MemorySearchMode[]
  fusion_score?: number
}

export interface MemorySearchReply {
  ok: boolean
  error?: string
  query?: string
  mode?: MemorySearchMode
  model?: string
  results?: MemoryResult[]
}

export interface MemoryAskReply {
  ok: boolean
  error?: string
  answer?: string
  citations?: string[]
  evidence?: MemoryResult[]
  model?: string | null
  usage?: Record<string, number | null> | null
  degraded?: string | null
}

export interface MemoryEntry {
  slug: string
  body: string
  updated_at: string
  mentions: string[]
  scope: string[]
  anchors: string[]
  source: string[]
  /**
   * Each source run with the task it belonged to, so the id can be followed.
   * `task` is null when the run's record is gone -- runs/ is disposable --
   * and the id is then a fact with nowhere to go. Absent from an older daemon.
   */
  sources?: Array<{ run_id: string; task: string | null }>
  valid_from: string | null
  superseded_by: string | null
  links: { depends_on: string[]; contradicts: string[] }
  second_look: string[]
  history: Array<{
    at: string
    writer: string
    did: string
    slug: string | null
  }>
}

export interface MemoryWriteReply {
  ok: boolean
  error?: string
  slug?: string
  because?: string
  accepted?: boolean
  suggestion?: string
}
