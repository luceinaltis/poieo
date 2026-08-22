/**
 * The no-frills skin: flow cards, a status dot, and what each worker is doing.
 *
 * It is the fallback for anyone who wants density over charm, and it is the
 * proof that the contract carries enough -- it renders from StageState alone,
 * with no canvas and no framework.
 */

import type { Skin, SkinCallbacks, SkinHandle } from "../contract"
import type { StageState, Worker } from "../../state/stage"
import "./ledger.css"

interface Card {
  root: HTMLElement
  node: HTMLElement
  text: HTMLElement
  tools: HTMLElement
  last: HTMLElement
}

function element(tag: string, className: string, parent: HTMLElement): HTMLElement {
  const node = document.createElement(tag)
  node.className = className
  parent.append(node)
  return node
}

function buildCard(flow: string, callbacks: SkinCallbacks): Card {
  const root = document.createElement("button")
  root.type = "button"
  root.className = "ledger-card"
  root.dataset.flow = flow
  root.addEventListener("click", () => callbacks.onSelectWorker(flow))

  const head = element("div", "ledger-head", root)
  element("span", "ledger-dot", head)
  element("span", "ledger-name", head).textContent = flow

  return {
    root,
    node: element("div", "ledger-node", root),
    text: element("p", "ledger-text", root),
    tools: element("ul", "ledger-tools", root),
    last: element("div", "ledger-last", root),
  }
}

function describeNode(worker: Worker): string {
  if (!worker.currentNode) return "idle"
  const parts = [worker.currentNode]
  if (worker.nodeType) parts.push(worker.nodeType)
  parts.push(`step ${worker.step}`)
  if (worker.turn > 0) parts.push(`turn ${worker.turn}`)
  return parts.join(" · ")
}

function describeRecent(worker: Worker): string {
  const recent = worker.recent
  if (recent.works === 0) return "nothing finished yet"

  const parts = [`${recent.works} piece${recent.works === 1 ? "" : "s"} of work`]
  if (recent.insertions || recent.deletions) {
    parts.push(`+${recent.insertions} / -${recent.deletions}`)
  }
  if (recent.nothingToDo) parts.push(`${recent.nothingToDo} found nothing to do`)
  if (recent.failed) parts.push(`${recent.failed} failed`)
  return parts.join(" · ")
}


function paint(card: Card, worker: Worker): void {
  card.root.dataset.status = worker.status
  card.node.textContent = describeNode(worker)

  // A turn with no text but with thinking still has something to show.
  const thinking = !worker.lastText && Boolean(worker.lastThinking)
  card.text.dataset.thinking = String(thinking)
  card.text.textContent = worker.lastText || worker.lastThinking || ""

  card.tools.replaceChildren(
    ...worker.recentToolCalls.map((call) => {
      const item = document.createElement("li")
      item.className = "ledger-tool"
      item.dataset.error = String(Boolean(call.error))
      item.textContent = call.name
      return item
    }),
  )

  card.last.textContent = describeRecent(worker)
}

export const ledger: Skin = {
  id: "ledger",
  label: "Ledger",

  mount(el: HTMLElement, callbacks: SkinCallbacks): SkinHandle {
    const board = element("div", "ledger", el)
    const cards = new Map<string, Card>()

    return {
      update(stage: StageState) {
        for (const [flow, worker] of Object.entries(stage.workers)) {
          let card = cards.get(flow)
          if (!card) {
            card = buildCard(flow, callbacks)
            cards.set(flow, card)
            board.append(card.root)
          }
          paint(card, worker)
        }
        for (const [flow, card] of cards) {
          if (!(flow in stage.workers)) {
            card.root.remove()
            cards.delete(flow)
          }
        }
      },

      destroy() {
        cards.clear()
        board.remove()
      },
    }
  },
}
