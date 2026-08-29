/**
 * The shell: owns the store, mounts whichever skin is chosen, and puts the
 * drawer beside it. It is the only thing here that knows React -- skins are
 * plain DOM behind a contract, so a new one never touches this file.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react"

import { Drawer } from "./detail/Drawer"
import { createSkinHost, readSkinPreference, writeSkinPreference } from "./shell/skinHost"
import type { SkinHost } from "./shell/skinHost"
import { recall, remember } from "./shell/remember"
import { Models } from "./models/Models"
import { createStageStore } from "./shell/stageStore"
import type { StageStore } from "./shell/stageStore"
import { SKINS, skinById } from "./skins/registry"
import { keyOfTask, onlyProject } from "./state/stage"
import "./app.css"

const PROJECT_KEY = "poieo.project"

const STATUS_LABEL: Record<string, string> = {
  connecting: "connecting",
  live: "live",
  lost: "reconnecting",
}

export default function App({ store }: { store?: StageStore }) {
  const [theStore] = useState<StageStore>(() => store ?? createStageStore())
  const stage = useSyncExternalStore(theStore.subscribe, theStore.getStage)
  const status = useSyncExternalStore(theStore.subscribe, theStore.getStatus)
  const tasks = useSyncExternalStore(theStore.subscribe, theStore.getFlows)
  const projects = useSyncExternalStore(theStore.subscribe, theStore.getProjects)
  const [asked, setAsked] = useState(() => recall(PROJECT_KEY, ""))
  // What the reader asked for, if the daemon is still running it. A remembered
  // project the daemon was restarted without would otherwise leave the board
  // filtering on nothing, which looks exactly like broken.
  const project =
    projects.find((one) => one.name === asked) ?? projects[0] ?? null

  const boardRef = useRef<HTMLDivElement>(null)
  const hostRef = useRef<SkinHost | null>(null)
  const [skinId, setSkinId] = useState(readSkinPreference)
  const [selected, setSelected] = useState<string | null>(null)
  // Not remembered across reloads, unlike the skin and the project: this is a
  // thing you open to answer a question, not a way you like the board to sit.
  const [showModels, setShowModels] = useState(false)

  useEffect(() => {
    void theStore.start()
    return () => theStore.stop()
  }, [theStore])

  useEffect(() => {
    const host = createSkinHost(boardRef.current!, { onSelectTask: setSelected })
    hostRef.current = host
    return () => {
      host.destroy()
      hostRef.current = null
    }
  }, [])

  useEffect(() => {
    hostRef.current?.show(skinId)
  }, [skinId])

  // The tab, not just the bar. Two boards open side by side are two tabs
  // reading `poieo`, and the tab is what a person clicks between.
  useEffect(() => {
    document.title = project ? `${project.name} · poieo` : "poieo"
  }, [project])

  // One project's board at a time. Every arrow on it stays inside a project,
  // so two of them side by side share nothing but a machine.
  const shown = useMemo(() => onlyProject(stage, project?.name ?? null), [stage, project])

  useEffect(() => {
    hostRef.current?.update(shown)
  }, [shown])

  const chooseProject = useCallback((name: string) => {
    setAsked(name)
    remember(PROJECT_KEY, name)
    // The drawer belongs to a task on the board that was there a moment ago.
    setSelected(null)
  }, [])

  const chooseSkin = (id: string) => {
    setSkinId(id)
    writeSkinPreference(id)
  }

  // Stable, so the memoized drawer sees the same props while frames stream by.
  const closeDrawer = useCallback(() => setSelected(null), [])
  const decided = useCallback(() => void theStore.resync(), [theStore])

  // One panel on that edge at a time. Both are fixed to the right at one
  // width, and the stage reserves one margin for whichever is open.
  const openModels = useCallback(() => {
    setShowModels(true)
    setSelected(null)
  }, [])
  const closeModels = useCallback(() => setShowModels(false), [])

  const empty = Object.keys(shown.tasks).length === 0
  // `selected` is the board's key -- the project and the task -- because a
  // name alone stopped picking out one task.
  const openRow = selected
    ? tasks.find((row) => keyOfTask(row.project, row.name) === selected)
    : undefined

  return (
    <>
      <header className="shell-bar">
        <span className="shell-title">poieo</span>
        {/* One project is a name, not a thing to choose between: a picker with
            one option in it is furniture. The folder is the tooltip either
            way -- two worktrees of one repository are two projects whose names
            can collide, and the path is what does not. */}
        {projects.length > 1 ? (
          <select
            className="shell-project-pick"
            aria-label="Project"
            title={project?.root}
            value={project?.name ?? ""}
            onChange={(event) => chooseProject(event.target.value)}
          >
            {projects.map((one) => (
              <option key={one.name} value={one.name}>
                {one.name}
              </option>
            ))}
          </select>
        ) : project ? (
          <span className="shell-project" title={project.root}>
            {project.name}
          </span>
        ) : null}
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
        {/* On the bar and not on a card: a project's models are the project's,
            and every task on the board would otherwise carry the same answer. */}
        {project ? (
          <button
            type="button"
            className="shell-pick shell-models"
            data-do="open-models"
            aria-expanded={showModels}
            onClick={openModels}
          >
            models
          </button>
        ) : null}
      </header>

      <div className="shell-stage" data-drawer={String(Boolean(selected || showModels))}>
        <div className="shell-board" ref={boardRef} />
        {empty ? (
          <p className="shell-empty">
            Nothing is running yet. When the daemon starts a run, it shows up here.
          </p>
        ) : null}
      </div>

      {showModels && project ? (
        <Models project={project.name} onClose={closeModels} />
      ) : null}

      {selected ? (
        <Drawer
          // A fresh drawer per flowState: its selected run, its opened files and
          // its expanded-failures toggle all belong to the task being read.
          key={selected}
          project={openRow?.project ?? ""}
          task={openRow?.name ?? selected}
          status={openRow?.status ?? "waiting"}
          pending={openRow?.pending ?? 0}
          into={openRow?.into ?? null}
          asking={openRow?.asking ?? null}
          onClose={closeDrawer}
          onDecided={decided}
        />
      ) : null}
    </>
  )
}
