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
import { MakeTask } from "./make/MakeTask"
import { createStageStore } from "./shell/stageStore"
import type { StageStore } from "./shell/stageStore"
import { DEFAULT_SKIN_ID, SKINS, skinById } from "./skins/registry"
import { keyOfTask, onlyProject } from "./state/stage"
import "./app.css"

const PROJECT_KEY = "poieo.project"
// The rendering the *board* was last drawn with, apart from `poieo.skin`
// (which may name a standalone place): it is what the board rail item comes
// back to after a visit to runs.
const BOARD_SKIN_KEY = "poieo.skin.board"

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
  const [showMake, setShowMake] = useState(false)

  useEffect(() => {
    void theStore.start()
    return () => theStore.stop()
  }, [theStore])

  // The stage reserves one margin. A task picked on the board takes it, so a
  // panel that was holding it has to let go -- the rail already does this for
  // its own two, and this is the third way in.
  const selectTask = useCallback((key: string | null) => {
    setSelected(key)
    if (key) {
      setShowModels(false)
      setShowMake(false)
    }
  }, [])

  useEffect(() => {
    const host = createSkinHost(boardRef.current!, { onSelectTask: selectTask })
    hostRef.current = host
    return () => {
      host.destroy()
      hostRef.current = null
    }
  }, [selectTask])

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

  // From the picker: a rendering of the board, so it is also what the board
  // rail item will come back to.
  const chooseSkin = (id: string) => {
    setSkinId(id)
    writeSkinPreference(id)
    remember(BOARD_SKIN_KEY, id)
  }

  // Standing somewhere other than the board -- a rail place drawn on the
  // stage, like runs -- rather than a rendering of it.
  const standing = skinById(skinId).standalone ? skinById(skinId).id : null

  const goPlace = useCallback((id: string) => {
    setSkinId(id)
    writeSkinPreference(id)
    setShowModels(false)
    setShowMake(false)
  }, [])

  // Stable, so the memoized drawer sees the same props while frames stream by.
  const closeDrawer = useCallback(() => setSelected(null), [])
  const decided = useCallback(() => void theStore.resync(), [theStore])

  // One panel on that edge at a time. Both are fixed to the right at one
  // width, and the stage reserves one margin for whichever is open.
  const openModels = useCallback(() => {
    setShowModels(true)
    setShowMake(false)
    setSelected(null)
  }, [])
  const closeModels = useCallback(() => setShowModels(false), [])
  const openMake = useCallback(() => {
    setShowMake(true)
    setShowModels(false)
    setSelected(null)
  }, [])
  const closeMake = useCallback(() => setShowMake(false), [])

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
        {/* Renderings of the board. One is a fact and not a choice, so the
            picker only exists when there are two -- the furniture rule the
            project name follows -- and it leaves the bar while the stage is
            showing a place instead, because a control that does not apply
            must not sit there looking like it does. */}
        {standing || SKINS.filter((skin) => !skin.standalone).length < 2 ? null : (
          <label className="shell-pick">
            view
            <select
              className="shell-skin"
              aria-label="View"
              value={skinById(skinId).id}
              onChange={(event) => chooseSkin(event.target.value)}
            >
              {SKINS.filter((skin) => !skin.standalone).map((skin) => (
                <option key={skin.id} value={skin.id}>
                  {skin.label}
                </option>
              ))}
            </select>
          </label>
        )}
      </header>

      {/* What the page is for, rather than what one task is doing -- so it is
          nav down the side and not a control on the bar, and it is where the
          next view lands beside `models`. `board` is the page with no panel
          over it: a rail item rather than a close box, because closing is not
          a place you can be. */}
      <nav className="shell-rail" aria-label="Views">
        <button
          type="button"
          data-do="open-board"
          aria-current={showModels || showMake || standing ? undefined : "page"}
          onClick={() => {
            closeModels()
            closeMake()
            // Coming back from a place, the board wears the rendering it was
            // left in, not a hard-coded one.
            if (standing) chooseSkin(recall(BOARD_SKIN_KEY, DEFAULT_SKIN_ID))
          }}
        >
          board
        </button>
        {/* The skins that are places rather than renderings. The rail is the
            list of what this page is for, and "what has it been doing" is a
            thing to come for -- where one drawing of the board against
            another would be a taste. */}
        {SKINS.filter((skin) => skin.standalone).map((skin) => (
          <button
            key={skin.id}
            type="button"
            data-do={`open-${skin.id}`}
            aria-current={!showModels && !showMake && standing === skin.id ? "page" : undefined}
            onClick={() => goPlace(skin.id)}
          >
            {skin.id}
          </button>
        ))}
        <button
          type="button"
          data-do="open-models"
          aria-current={showModels ? "page" : undefined}
          // Nothing to ask about until the daemon has named a project.
          disabled={!project}
          onClick={openModels}
        >
          models
        </button>
        <button
          type="button"
          data-do="open-make"
          aria-current={showMake ? "page" : undefined}
          // A card is written into a project's tasks folder, so there has to
          // be a project before there is anywhere to write it.
          disabled={!project}
          onClick={openMake}
        >
          new task
        </button>
      </nav>

      <div className="shell-stage" data-drawer={String(Boolean(selected || showModels || showMake))}>
        <div className="shell-board" ref={boardRef} />
        {empty ? (
          <p className="shell-empty">
            Nothing is running yet. When the daemon starts a run, it shows up here.
          </p>
        ) : null}
      </div>

      {showModels && project ? (
        // Keyed on the project, for the reason `MakeTask` below is. Everything
        // this panel holds is about one project's binding file -- the report,
        // a half-typed address, the name and key variable beside it, and the
        // warning that the daemon would not take the last write. Carried
        // across a switch, that warning is redrawn with every clause about a
        // project the reader has left, captioned with the *new* project's
        // binding path, which was never edited at all.
        <Models key={project.name} project={project.name} onClose={closeModels} />
      ) : null}

      {showMake && project ? (
        // Keyed on the project: a half-typed folder is read against *that*
        // project's tasks folder, so carrying the form across a switch would
        // post it somewhere it means something else.
        <MakeTask
          key={project.name}
          project={project.name}
          // A daemon too old to say is taken at its most careful: the panel
          // then promises no copy it cannot prove, which is the direction to
          // be wrong in when the sentence is about somebody's own files.
          keepsCopies={project.keeps_copies ?? false}
          onClose={closeMake}
        />
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
