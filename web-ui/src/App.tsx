/**
 * The shell: owns the store, mounts whichever skin is chosen, and puts the
 * drawer beside it. It is the only thing here that knows React -- skins are
 * plain DOM behind a contract, so a new one never touches this file.
 */

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react"

import { ThemeSwitch } from "./shell/ThemeSwitch"
import { ChatIcon, ModelsIcon } from "./shell/icons"
import { Drawer } from "./detail/Drawer"
import { createSkinHost, readSkinPreference, writeSkinPreference } from "./shell/skinHost"
import type { SkinHost } from "./shell/skinHost"
import { recall, remember } from "./shell/remember"
import { Models } from "./models/Models"
import { MakeTask } from "./make/MakeTask"
import { Chat } from "./chat/Chat"
import { Memory } from "./memory/Memory"
import { createStageStore } from "./shell/stageStore"
import type { StageStore } from "./shell/stageStore"
import { DEFAULT_SKIN_ID, SKINS, skinById } from "./skins/registry"
import { chatTaskOf, keyOfTask, onlyProject } from "./state/stage"
import lockupUrl from "../../site/img/lockup.svg"
import "./app.css"

const PROJECT_KEY = "poieo.project"
// The rendering the *board* was last drawn with, apart from `poieo.skin`
// (which may name a standalone place): it is what the board tab comes back
// to after a visit to runs.
const BOARD_SKIN_KEY = "poieo.skin.board"
const MEMORY_PLACE_KEY = "poieo.place.memory"

const STATUS_LABEL: Record<string, string> = {
  connecting: "connecting",
  live: "live",
  lost: "reconnecting",
}

type TaskFields = { name: string; folder: string; prompt: string }

type PanelState =
  | { kind: "closed" }
  // `runId` when the drawer was opened on one run -- from a memory entry's
  // source -- rather than on the task's latest.
  | { kind: "task"; taskKey: string; runId?: string }
  | { kind: "models" }
  | { kind: "chat" }
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
  // These panels share one margin, so only one can be open at a time.
  // Unlike the skin and project, the open panel is not remembered across reloads.
  const [activePanel, setActivePanel] = useState<PanelState>(CLOSED_PANEL)
  // A card the form just wrote, by the key the stage will file it under. The
  // daemon looks at the folder the moment it is written and says "ask again";
  // when the listing then carries it, it opens where the form was.
  const [awaitedTaskKey, setAwaitedTaskKey] = useState<string | null>(null)
  // Which conversation the chat has open, held here rather than in its panel
  // so a task picked off the board -- which takes the one margin -- does not
  // close it. The conversation itself is the chat task's runs, which the
  // daemon keeps; this is only which of them is on screen.
  const [chatThread, setChatThread] = useState<string | null>(null)
  const panelOpenerRef = useRef<HTMLElement | null>(null)
  const panelWasOpenRef = useRef(false)
  const panelIsOpen = activePanel.kind !== "closed"

  // Capture this before opening changes the DOM: on a phone that render hides
  // the stage, and a browser is then free to drop its focus. An
  // opener inside the current panel is deliberately ignored so a handoff such
  // as "make one like it" still returns to the card that began the visit.
  const rememberPanelOpener = useCallback((opener: Element | null) => {
    if (
      opener instanceof HTMLElement &&
      opener !== document.body &&
      !opener.closest(".panel")
    ) {
      panelOpenerRef.current = opener
    }
  }, [])

  // The panel is the next place to read after its button, not a visual layer
  // left behind that button in the tab order. Move focus in the same commit
  // that hides the phone background so there is no frame between the two.
  useLayoutEffect(() => {
    if (panelIsOpen) {
      const panel = document.querySelector<HTMLElement>(".panel")
      if (panel) {
        panel.tabIndex = -1
        panel.focus()
      }
    } else if (panelWasOpenRef.current) {
      // A tab or board click has already put focus exactly where the reader
      // asked to go. Restore only when closing removed the focused panel and
      // the browser fell back to the page itself.
      if (document.activeElement === document.body) {
        // The opener may have gone: the first task made from the bare board's
        // invitation replaces that invitation with the board while the panel
        // is still open. The corner button is where that act now lives.
        const opener = panelOpenerRef.current?.isConnected
          ? panelOpenerRef.current
          : document.querySelector<HTMLElement>('[data-do="open-make"]')
        opener?.focus()
      }
      panelOpenerRef.current = null
    }
    panelWasOpenRef.current = panelIsOpen
  }, [activePanel, panelIsOpen])
  // Remembered across reloads like the skin and project: memory is a place the
  // reader returns to, not a temporary panel over the board.
  const [showMemory, setShowMemory] = useState(
    () => recall(MEMORY_PLACE_KEY, "false") === "true",
  )
  // The entry the memory place opens on, when a drawer sent the reader there.
  // Not remembered across reloads: it is a step, not a place.
  const [memoryFocus, setMemoryFocus] = useState<{ slug: string } | null>(null)

  useEffect(() => {
    void stageStore.start()
    return () => stageStore.stop()
  }, [stageStore])

  // The stage reserves one margin. A task picked on the board takes it, so a
  // panel that was holding it has to let go -- the tabs already do this for
  // their own, and this is the other way in.
  const selectTask = useCallback(
    (taskKey: string | null, opener?: HTMLElement) => {
      if (taskKey) rememberPanelOpener(opener ?? null)
      setActivePanel((current) =>
        taskKey
          ? { kind: "task", taskKey }
          : current.kind === "task"
            ? CLOSED_PANEL
            : current,
      )
    },
    [rememberPanelOpener],
  )

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
    // As does an entry in focus: a slug names something in one memory.
    setMemoryFocus(null)
    // And a conversation: it was had with that project.
    setChatThread(null)
  }, [])

  // From the picker: a rendering of the board, so it is also what the board
  // tab will come back to.
  const chooseSkin = (id: string) => {
    setSkinId(id)
    writeSkinPreference(id)
    remember(BOARD_SKIN_KEY, id)
  }

  // Standing somewhere other than the board -- a place of its own drawn on
  // the stage, like runs -- rather than a rendering of it.
  const standaloneViewId = skinById(skinId).standalone ? skinById(skinId).id : null
  const memoryOpen = Boolean(showMemory && project)

  const openStandaloneView = useCallback((id: string) => {
    setShowMemory(false)
    remember(MEMORY_PLACE_KEY, "false")
    setSkinId(id)
    writeSkinPreference(id)
    setActivePanel((current) =>
      current.kind === "models" || current.kind === "make" || current.kind === "chat"
        ? CLOSED_PANEL
        : current,
    )
  }, [])

  // Stable, so the memoized drawer sees the same props while frames stream by.
  const closePanel = useCallback(() => setActivePanel(CLOSED_PANEL), [])
  const resyncAfterAction = useCallback(() => void stageStore.resync(), [stageStore])

  // The board tab puts a toggled panel away but leaves a task drawer over its
  // underlying view.
  const closeToolPanel = useCallback(() => {
    setActivePanel((current) =>
      current.kind === "models" || current.kind === "make" || current.kind === "chat"
        ? CLOSED_PANEL
        : current,
    )
  }, [])
  const openMemory = useCallback(() => {
    setShowMemory(true)
    remember(MEMORY_PLACE_KEY, "true")
    setActivePanel(CLOSED_PANEL)
  }, [])
  // From a drawer: the memory place, open on the entry that run was shown.
  const openMemoryAt = useCallback((slug: string) => {
    setMemoryFocus({ slug })
    setShowMemory(true)
    remember(MEMORY_PLACE_KEY, "true")
    setActivePanel(CLOSED_PANEL)
  }, [])
  // The way back: an entry's source run, opened in its task's drawer. The
  // memory place closes because the drawer covers the board, not the place,
  // and the run is what the reader asked to see.
  const openRun = useCallback(
    (task: string, runId: string) => {
      if (!project) return
      setShowMemory(false)
      remember(MEMORY_PLACE_KEY, "false")
      setActivePanel({ kind: "task", taskKey: keyOfTask(project.name, task), runId })
    },
    [project],
  )
  const openModels = useCallback(
    (opener: HTMLElement) => {
      rememberPanelOpener(opener)
      setActivePanel({ kind: "models" })
    },
    [rememberPanelOpener],
  )
  const openMake = useCallback(
    (opener: HTMLElement) => {
      rememberPanelOpener(opener)
      setActivePanel({ kind: "make" })
    },
    [rememberPanelOpener],
  )
  const openChat = useCallback(
    (opener: HTMLElement) => {
      rememberPanelOpener(opener)
      setActivePanel({ kind: "chat" })
    },
    [rememberPanelOpener],
  )
  const openOnceMade = useCallback(
    (task: string) => {
      if (project) setAwaitedTaskKey(keyOfTask(project.name, task))
    },
    [project],
  )
  useEffect(() => {
    if (awaitedTaskKey === null) return
    // Only where the form still is. A reader who has since closed it, opened
    // models, picked another task or switched project has said where they
    // want to be, and a card arriving a moment later must not take that back.
    if (activePanel.kind !== "make") {
      setAwaitedTaskKey(null)
      return
    }
    if (!(awaitedTaskKey in stage.tasks)) return
    setActivePanel({ kind: "task", taskKey: awaitedTaskKey })
    setAwaitedTaskKey(null)
  }, [activePanel.kind, awaitedTaskKey, stage.tasks])
  const makeAlike = useCallback(
    (initialFields: TaskFields) => setActivePanel({ kind: "make", initialFields }),
    [],
  )

  const taskCount = Object.keys(projectStage.tasks).length
  const empty = taskCount === 0
  const selectedTaskKey = activePanel.kind === "task" ? activePanel.taskKey : null
  // `selectedTaskKey` is the board's key -- the project and the task -- because a
  // name alone stopped picking out one task.
  const selectedTask = selectedTaskKey
    ? tasks.find((row) => keyOfTask(row.project, row.name) === selectedTaskKey)
    : undefined
  const selectedTaskState = selectedTaskKey ? stage.tasks[selectedTaskKey] : undefined

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
        {/* One row, and four kinds of thing on it, each with its own look.
            The tabs say where the reader is: the places that take the whole
            stage. The toggles say what is open over it: a panel is over a
            place, not a place, so opening one never moves the tabs' mark.
            Then the daemon's state, and a preference. These used to be split
            between this bar and a rail down the side, in the same lettering,
            which read as two menus whose difference nobody could see.

            One group from here to the end of the bar, so that on a screen too
            narrow for one row the whole group wraps under the name and the
            keyboard's order down the bar stays the order the eye reads. */}
        <div className="shell-row">
        <nav className="shell-nav" aria-label="Views">
          <div className="shell-places">
            {/* `board` is the page with no place over it: a tab rather than a
                close box, because closing is not a place. */}
            <button
              type="button"
              data-do="open-board"
              aria-current={standaloneViewId || memoryOpen ? undefined : "page"}
              onClick={() => {
                setShowMemory(false)
                remember(MEMORY_PLACE_KEY, "false")
                closeToolPanel()
                // Coming back from a place, the board wears the rendering it
                // was left in, not a hard-coded one.
                if (standaloneViewId) chooseSkin(recall(BOARD_SKIN_KEY, DEFAULT_SKIN_ID))
              }}
            >
              board
            </button>
            {/* The skins that are places rather than renderings: "what has
                it been doing" is a thing to come for, where one drawing of
                the board against another would be a taste. */}
            {SKINS.filter((skin) => skin.standalone).map((skin) => (
              <button
                key={skin.id}
                type="button"
                data-do={`open-${skin.id}`}
                aria-current={!memoryOpen && standaloneViewId === skin.id ? "page" : undefined}
                onClick={() => openStandaloneView(skin.id)}
              >
                {skin.id}
              </button>
            ))}
            <button
              type="button"
              data-do="open-memory"
              aria-current={memoryOpen ? "page" : undefined}
              disabled={!project}
              onClick={openMemory}
            >
              memory
            </button>
          </div>
          <div className="shell-tools">
            {/* Both about this project's models -- a word with one, and which
                ones it can reach -- and both nothing to ask about until the
                daemon has named a project. */}
            <button
              type="button"
              className="shell-toggle"
              data-do="open-chat"
              aria-expanded={activePanel.kind === "chat"}
              disabled={!project}
              onClick={(event) => openChat(event.currentTarget)}
            >
              <ChatIcon />
              chat
            </button>
            <button
              type="button"
              className="shell-toggle"
              data-do="open-models"
              aria-expanded={activePanel.kind === "models"}
              disabled={!project}
              onClick={(event) => openModels(event.currentTarget)}
            >
              <ModelsIcon />
              models
            </button>
          </div>
        </nav>
        {/* Renderings of the board. One is a fact and not a choice, so the
            picker only exists when there are two -- the furniture rule the
            project name follows -- and it leaves the bar while the stage is
            showing a place instead, because a control that does not apply
            must not sit there looking like it does. */}
        {standaloneViewId || memoryOpen || SKINS.filter((skin) => !skin.standalone).length < 2 ? null : (
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
        {/* A dot, with the word for a screen reader and the tooltip. */}
        <span
          className="shell-status"
          data-status={status}
          role="status"
          title={`daemon: ${STATUS_LABEL[status] ?? status}`}
        >
          <span className="sr-only">{STATUS_LABEL[status] ?? status}</span>
        </span>
        <ThemeSwitch />
        </div>
      </header>

      <div className="shell-stage" data-drawer={String(panelIsOpen)}>
        {/* The place's own line: its name, what is on it, and the acts that
            land on it. A task is made onto the board, not onto runs or
            memory, so `new task` sits here and leaves with the board; the
            bare board carries its own, in the invitation, and two on one
            screen would be one too many. */}
        <div className="stage-head">
          <span className="stage-place">{memoryOpen ? "memory" : (standaloneViewId ?? "board")}</span>
          {!memoryOpen && taskCount > 0 ? (
            <span className="stage-count">{taskCount === 1 ? "1 task" : `${taskCount} tasks`}</span>
          ) : null}
          {!standaloneViewId && !memoryOpen && !empty ? (
            <button
              type="button"
              className="shell-make"
              data-do="open-make"
              aria-expanded={activePanel.kind === "make"}
              onClick={(event) => openMake(event.currentTarget)}
            >
              new task
            </button>
          ) : null}
        </div>
        <div className="shell-board" data-hidden={String(memoryOpen)} ref={boardRef} />
        {memoryOpen && project ? (
          <Memory key={project.name} project={project.name} focus={memoryFocus} onOpenRun={openRun} />
        ) : null}
        {empty && !memoryOpen ? (
          <div className="shell-empty">
            <p>No tasks yet. Say what you want done.</p>
            <button
              type="button"
              data-do="empty-new-task"
              disabled={!project}
              onClick={(event) => openMake(event.currentTarget)}
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

      {activePanel.kind === "chat" && project ? (
        // Keyed on the project, as models is: the thread is that project's,
        // and switching projects has already emptied it.
        <Chat
          key={project.name}
          project={project.name}
          chatTask={chatTaskOf(stage, project.name)}
          thread={chatThread}
          onThread={setChatThread}
          onClose={closePanel}
          // The other running tasks, with their live timelines: what the
          // chat may speak to instead of the conversation.
          steerable={Object.values(projectStage.tasks)
            .filter((task) => task.status === "running")
            .map((task) => ({ name: task.name, title: task.title, activity: task.activity }))}
        />
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
          onMade={openOnceMade}
          // Where a conversation the project has no model for sends the
          // reader: the panel that connects one, in this panel's place.
          onModels={openModels}
        />
      ) : null}

      {selectedTaskKey ? (
        <Drawer
          // A fresh drawer per task: its selected run and opened disclosures
          // belong to the task being read.
          key={selectedTaskKey}
          project={selectedTask?.project ?? ""}
          task={selectedTask?.name ?? selectedTaskKey}
          title={selectedTaskState?.title}
          status={selectedTaskState?.status ?? selectedTask?.status ?? "waiting"}
          enabled={selectedTaskState?.enabled ?? selectedTask?.enabled ?? true}
          stale={selectedTaskState?.stale || selectedTask?.stale || null}
          heldBecause={selectedTaskState?.heldBecause || selectedTask?.held_because || null}
          pending={selectedTaskState?.pending ?? selectedTask?.pending ?? 0}
          into={selectedTask?.into ?? null}
          asking={selectedTaskState?.asking ?? selectedTask?.asking ?? null}
          others={tasks
            .filter((row) => row.project === selectedTask?.project)
            .map((row) => ({ name: row.name, title: row.title || row.name }))}
          liveRuns={selectedTaskState?.runs ?? []}
          liveActivity={selectedTaskState?.activity ?? []}
          liveRunId={selectedTaskState?.activityRunId ?? null}
          runId={activePanel.kind === "task" ? (activePanel.runId ?? null) : null}
          onClose={closePanel}
          onDecided={resyncAfterAction}
          onAlike={makeAlike}
          onMemory={openMemoryAt}
        />
      ) : null}
    </>
  )
}
