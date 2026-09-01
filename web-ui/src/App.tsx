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
import lockupUrl from "../../site/img/lockup.svg"
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

type TaskFields = { name: string; folder: string; prompt: string }

type PanelState =
  | { kind: "closed" }
  | { kind: "task"; taskKey: string }
  | { kind: "models" }
  | { kind: "make"; initialFields?: TaskFields }

const CLOSED_PANEL: PanelState = { kind: "closed" }

export default function App({ store }: { store?: StageStore }) {
  const [stageStore] = useState<StageStore>(() => store ?? createStageStore())
  const stage = useSyncExternalStore(stageStore.subscribe, stageStore.getStage)
  const status = useSyncExternalStore(stageStore.subscribe, stageStore.getStatus)
  const tasks = useSyncExternalStore(stageStore.subscribe, stageStore.getTasks)
  const projects = useSyncExternalStore(stageStore.subscribe, stageStore.getProjects)
  const [preferredProjectName, setPreferredProjectName] = useState(() =>
    recall(PROJECT_KEY, ""),
  )
  // What the reader asked for, if the daemon is still running it. A remembered
  // project the daemon was restarted without would otherwise leave the board
  // filtering on nothing, which looks exactly like broken.
  const project =
    projects.find((one) => one.name === preferredProjectName) ?? projects[0] ?? null

  const boardRef = useRef<HTMLDivElement>(null)
  const hostRef = useRef<SkinHost | null>(null)
  const [skinId, setSkinId] = useState(readSkinPreference)
  // These three panels share one margin, so only one can be open at a time.
  // Unlike the skin and project, the open panel is not remembered across reloads.
  const [activePanel, setActivePanel] = useState<PanelState>(CLOSED_PANEL)
  const panelOpenerRef = useRef<HTMLElement | null>(null)
  const panelWasOpenRef = useRef(false)
  const panelIsOpen = activePanel.kind !== "closed"

  // The panel is the next place to read after its button, not a visual layer
  // left behind that button in the tab order. A switch from one panel to
  // another remembers the latest rail button; a handoff inside a panel keeps
  // the original opener because the old panel disappears under the new one.
  useEffect(() => {
    if (panelIsOpen) {
      const focused = document.activeElement
      if (!panelWasOpenRef.current) {
        panelOpenerRef.current = focused instanceof HTMLElement ? focused : null
      } else if (
        focused instanceof HTMLElement &&
        focused !== document.body &&
        !focused.closest(".panel")
      ) {
        panelOpenerRef.current = focused
      }

      const panel = document.querySelector<HTMLElement>(".panel")
      if (panel) {
        panel.tabIndex = -1
        panel.focus()
      }
    } else if (panelWasOpenRef.current) {
      // A rail or board click has already put focus exactly where the reader
      // asked to go. Restore only when closing removed the focused panel and
      // the browser fell back to the page itself.
      if (
        document.activeElement === document.body &&
        panelOpenerRef.current?.isConnected
      ) {
        panelOpenerRef.current.focus()
      }
      panelOpenerRef.current = null
    }
    panelWasOpenRef.current = panelIsOpen
  }, [activePanel, panelIsOpen])

  useEffect(() => {
    void stageStore.start()
    return () => stageStore.stop()
  }, [stageStore])

  // The stage reserves one margin. A task picked on the board takes it, so a
  // panel that was holding it has to let go -- the rail already does this for
  // its own two, and this is the third way in.
  const selectTask = useCallback((taskKey: string | null) => {
    setActivePanel((current) =>
      taskKey
        ? { kind: "task", taskKey }
        : current.kind === "task"
          ? CLOSED_PANEL
          : current,
    )
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
  const projectStage = useMemo(
    () => onlyProject(stage, project?.name ?? null),
    [stage, project],
  )

  useEffect(() => {
    hostRef.current?.update(projectStage)
  }, [projectStage])

  const chooseProject = useCallback((name: string) => {
    setPreferredProjectName(name)
    remember(PROJECT_KEY, name)
    // A task drawer and make form belong to the project that opened them.
    // Models stays open and remounts for the new project below.
    setActivePanel((current) => (current.kind === "models" ? current : CLOSED_PANEL))
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
  const standaloneViewId = skinById(skinId).standalone ? skinById(skinId).id : null

  const openStandaloneView = useCallback((id: string) => {
    setSkinId(id)
    writeSkinPreference(id)
    setActivePanel((current) =>
      current.kind === "models" || current.kind === "make" ? CLOSED_PANEL : current,
    )
  }, [])

  // Stable, so the memoized drawer sees the same props while frames stream by.
  const closePanel = useCallback(() => setActivePanel(CLOSED_PANEL), [])
  const resyncAfterAction = useCallback(() => void stageStore.resync(), [stageStore])

  // Board closes a rail panel but leaves a task drawer over its underlying view.
  const closeRailPanel = useCallback(() => {
    setActivePanel((current) =>
      current.kind === "models" || current.kind === "make" ? CLOSED_PANEL : current,
    )
  }, [])
  const openModels = useCallback(() => setActivePanel({ kind: "models" }), [])
  const openMake = useCallback(() => setActivePanel({ kind: "make" }), [])
  const makeAlike = useCallback(
    (initialFields: TaskFields) => setActivePanel({ kind: "make", initialFields }),
    [],
  )

  const empty = Object.keys(projectStage.tasks).length === 0
  const selectedTaskKey = activePanel.kind === "task" ? activePanel.taskKey : null
  const railPanelIsOpen = activePanel.kind === "models" || activePanel.kind === "make"
  // `selectedTaskKey` is the board's key -- the project and the task -- because a
  // name alone stopped picking out one task.
  const selectedTask = selectedTaskKey
    ? tasks.find((row) => keyOfTask(row.project, row.name) === selectedTaskKey)
    : undefined

  return (
    <>
      <header className="shell-bar">
        <img className="shell-lockup" src={lockupUrl} alt="poieo" />
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
        {standaloneViewId || SKINS.filter((skin) => !skin.standalone).length < 2 ? null : (
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
      <nav
        className="shell-rail"
        aria-label="Views"
        data-covered={String(panelIsOpen)}
      >
        <button
          type="button"
          data-do="open-board"
          aria-current={railPanelIsOpen || standaloneViewId ? undefined : "page"}
          onClick={() => {
            closeRailPanel()
            // Coming back from a place, the board wears the rendering it was
            // left in, not a hard-coded one.
            if (standaloneViewId) chooseSkin(recall(BOARD_SKIN_KEY, DEFAULT_SKIN_ID))
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
            aria-current={
              !railPanelIsOpen && standaloneViewId === skin.id ? "page" : undefined
            }
            onClick={() => openStandaloneView(skin.id)}
          >
            {skin.id}
          </button>
        ))}
        <button
          type="button"
          data-do="open-models"
          aria-current={activePanel.kind === "models" ? "page" : undefined}
          // Nothing to ask about until the daemon has named a project.
          disabled={!project}
          onClick={openModels}
        >
          models
        </button>
        <button
          type="button"
          data-do="open-make"
          aria-current={activePanel.kind === "make" ? "page" : undefined}
          // A card is written into a project's tasks folder, so there has to
          // be a project before there is anywhere to write it.
          disabled={!project}
          onClick={openMake}
        >
          new task
        </button>
      </nav>

      <div className="shell-stage" data-drawer={String(panelIsOpen)}>
        <div className="shell-board" ref={boardRef} />
        {empty ? (
          <div className="shell-empty">
            <p>No tasks yet. Create one to put your models to work.</p>
            <button
              type="button"
              data-do="empty-new-task"
              disabled={!project}
              onClick={openMake}
            >
              New task
            </button>
          </div>
        ) : null}
      </div>

      {activePanel.kind === "models" && project ? (
        // Keyed on the project, for the reason `MakeTask` below is. Everything
        // this panel holds is about one project's binding file -- the report,
        // a half-typed address, the name and key variable beside it, the role
        // a click moves, and the warning that the daemon would not take the
        // last write. Carried across a switch, that warning is redrawn with
        // every clause about a project the reader has left, captioned with the
        // *new* project's binding path, which was never edited at all.
        //
        // The filter box goes with them, and that one is a choice rather than
        // a consequence: a model name reads the same in both projects, so it
        // could have been carried. An empty list under a filter the reader had
        // forgotten typing reads as "this project has nothing", which is the
        // worse of the two ways to be wrong.
        <Models key={project.name} project={project.name} onClose={closePanel} />
      ) : null}

      {activePanel.kind === "make" && project ? (
        // Keyed on the project: a half-typed folder is read against *that*
        // project's tasks folder, so carrying the form across a switch would
        // post it somewhere it means something else.
        <MakeTask
          // ...and on the seed: a panel already open must take a fresh seed,
          // and a keyed remount is how a form starts over.
          key={`${project.name}:${activePanel.initialFields?.name ?? ""}`}
          project={project.name}
          seed={activePanel.initialFields}
          // A daemon too old to say is taken at its most careful: the panel
          // then promises no copy it cannot prove, which is the direction to
          // be wrong in when the sentence is about somebody's own files.
          keepsCopies={project.keeps_copies ?? false}
          // The names this project's tasks are filed under -- TaskRow.name is
          // already the filename, which is what a collision is about.
          taken={tasks.filter((one) => one.project === project.name).map((one) => one.name)}
          onClose={closePanel}
        />
      ) : null}

      {selectedTaskKey ? (
        <Drawer
          // A fresh drawer per task: its selected run, its opened files and
          // its expanded-failures toggle all belong to the task being read.
          key={selectedTaskKey}
          project={selectedTask?.project ?? ""}
          task={selectedTask?.name ?? selectedTaskKey}
          status={selectedTask?.status ?? "waiting"}
          enabled={selectedTask?.enabled ?? true}
          stale={selectedTask?.stale ?? null}
          pending={selectedTask?.pending ?? 0}
          into={selectedTask?.into ?? null}
          asking={selectedTask?.asking ?? null}
          onClose={closePanel}
          onDecided={resyncAfterAction}
          onAlike={makeAlike}
        />
      ) : null}
    </>
  )
}
