/**
 * The shell: owns the store, mounts whichever skin is chosen, and puts the
 * drawer beside it. It is the only thing here that knows React -- skins are
 * plain DOM behind a contract, so a new one never touches this file.
 */

import { useEffect, useRef, useState, useSyncExternalStore } from "react"

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

  const empty = Object.keys(stage.workers).length === 0

  return (
    <>
      <header className="shell-bar">
        <span className="shell-title">poieo</span>
        <span className="shell-status" data-status={status}>
          {STATUS_LABEL[status] ?? status}
        </span>
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
      </header>

      <div className="shell-board" ref={boardRef} />

      {empty ? (
        <p className="shell-empty">
          Nothing is running yet. When the daemon picks up work, it shows up here.
        </p>
      ) : null}

      {selected ? (
        <Drawer
          flow={selected}
          pending={flows.find((row) => row.name === selected)?.pending ?? 0}
          into={flows.find((row) => row.name === selected)?.into ?? null}
          onClose={() => setSelected(null)}
          onDecided={() => void theStore.resync()}
        />
      ) : null}
    </>
  )
}
