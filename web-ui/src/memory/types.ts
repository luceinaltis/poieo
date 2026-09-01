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

export interface MemoryOverview {
  /** Opaque validator used only while this memory place remains open. */
  revision?: string
  enabled: boolean
  page: string | null
  stats: {
    page_chars: number
    page_budget: number
    kept: number
    set_aside: number
    lookup: string
    disagreements: string[][]
    second_look: string[]
  } | null
  capabilities: { words: boolean; meaning: boolean; ask: boolean }
  graph: MemoryGraph
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
