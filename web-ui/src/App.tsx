/**
 * The shell: owns the store, mounts whichever skin is chosen, and puts the
 * drawer beside it. It is the only thing here that knows React -- skins are
 * plain DOM behind a contract, so a new one never touches this file.
 */

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react"

import { Drawer } from "./detail/Drawer"
import { createSkinHost, readSkinPreference, writeSkinPreference } from "./shell/skinHost"
import type { SkinHost } from "./shell/skinHost"
import { createStageStore } from "./shell/stageStore"
import type { StageStore } from "./shell/stageStore"
import { SKINS, skinById } from "./skins/registry"
import "./app.css"

const STATUS_LABEL: Record<string, string> = {
  connecting: "connecting",
  live: "live",
  lost: "reconnecting",
}

export default function App({ store }: { store?: StageStore }) {
  const [theStore] = useState<StageStore>(() => store ?? createStageStore())
  const stage = useSyncExternalStore(theStore.subscribe, theStore.getStage)
  const status = useSyncExternalStore(theStore.subscribe, theStore.getStatus)
  const flows = useSyncExternalStore(theStore.subscribe, theStore.getFlows)

  const boardRef = useRef<HTMLDivElement>(null)
  const hostRef = useRef<SkinHost | null>(null)
  const [skinId, setSkinId] = useState(readSkinPreference)
  const [selected, setSelected] = useState<string | null>(null)

  useEffect(() => {
    void theStore.start()
    return () => theStore.stop()
  }, [theStore])

  useEffect(() => {
    const host = createSkinHost(boardRef.current!, { onSelectWorker: setSelected })
    hostRef.current = host
    return () => {
      host.destroy()
      hostRef.current = null
    }
  }, [])

  useEffect(() => {
    hostRef.current?.show(skinId)
  }, [skinId])

  useEffect(() => {
    hostRef.current?.update(stage)
  }, [stage])

  const chooseSkin = (id: string) => {
    setSkinId(id)
    writeSkinPreference(id)
  }

  // Stable, so the memoized drawer sees the same props while frames stream by.
  const closeDrawer = useCallback(() => setSelected(null), [])
  const decided = useCallback(() => void theStore.resync(), [theStore])

  const empty = Object.keys(stage.workers).length === 0
  const openRow = selected ? flows.find((row) => row.name === selected) : undefined

  return (
    <>
      <header className="shell-bar">
        <span className="shell-title">poieo</span>
        <span className="shell-status" data-status={status}>
          {STATUS_LABEL[status] ?? status}
        </span>
        <label className="shell-pick">
          view
          <select
            className="shell-skin"
            aria-label="View"
            value={skinById(skinId).id}
            onChange={(event) => chooseSkin(event.target.value)}
          >
            {SKINS.map((skin) => (
              <option key={skin.id} value={skin.id}>
                {skin.label}
              </option>
            ))}
          </select>
        </label>
      </header>

      <div className="shell-stage" data-drawer={String(Boolean(selected))}>
        <div className="shell-board" ref={boardRef} />
        {empty ? (
          <p className="shell-empty">
            Nothing is running yet. When the daemon starts a run, it shows up here.
          </p>
        ) : null}
      </div>

      {selected ? (
        <Drawer
          // A fresh drawer per worker: its selected run, its opened files and
          // its expanded-failures toggle all belong to the flow being read.
          key={selected}
          flow={selected}
          status={openRow?.status ?? "waiting"}
          pending={openRow?.pending ?? 0}
          into={openRow?.into ?? null}
          onClose={closeDrawer}
          onDecided={decided}
        />
      ) : null}
    </>
  )
}
