# ReefVision Scientist-Ready Phase 12 — Scientist Workspace UI Redesign

## Goal

Replace the older dashboard-and-tabs framing with the approved Home → Project Workspace design while preserving ReefVision's validated backend APIs, database models, provider execution, scientific review gates, and existing feature components.

Phase 12 is a presentation and workflow-composition redesign. It must not create parallel scientific logic.

## Design contract

The target desktop experience is:

- polished Home / Project Launcher with recent and pinned projects;
- dominant project workbench rather than disconnected feature pages;
- persistent left navigation;
- central scientific work area;
- context-sensitive right inspector;
- image/video filmstrip where media context benefits from it;
- workspace presets implemented as arrangements of existing components;
- collapsible/dockable panels with persistent layout state;
- Review Mode that keeps machine output visibly distinct from scientist-verified truth;
- automatic scale-bar calibration surfaced in the normal measurement workflow;
- Node Builder and Active Learning loops retained as canonical workflow-engine views.

## Delivery phases

### 12A — Home and Project Launcher

- recent project cards;
- local pinned projects;
- New Project and Project Exchange entry points;
- quick-start project types;
- local service/release status;
- What's New panel.

### 12B — Project Workbench Shell

- persistent project navigation rail;
- compact global bar and project context;
- central feature stage;
- context inspector;
- preserve current keyboard/tab semantics and existing feature components.

### 12C — Media workspace and layout system

- dominant image/video viewer;
- bottom filmstrip showing nearby media and review state;
- collapsible/dockable panels;
- workspace presets: Detection, Annotation, Segmentation, Pose Tracking,
  Morphometrics, Workflow Builder, Review/QA, and Custom Layout;
- persisted layout preferences;
- detachable/pop-out panels where Tauri behavior is reliable.

### 12D — Scientist workflow UX

- Review Mode;
- explicit machine-output versus scientist-truth visual boundaries;
- model/inference controls;
- measurements/results panels;
- training monitor;
- annotation list;
- video timeline;
- pose controls;
- automatic scale-bar calibration entry points.

### 12E — Polish and acceptance

- accessibility and keyboard behavior;
- responsive desktop sizing;
- loading/error/empty states;
- full frontend regression suite;
- production build;
- packaged desktop smoke;
- final scientist visual acceptance.

## Deferred validation carried forward

These are not silently reported as passing:

- Phase 11C clean install/restart/uninstall on the new PC or another disposable Windows environment;
- Phase 11D RTX 3090 packaged provider matrix;
- Phase 10D visual Node Builder smoke, which will be superseded by the final Phase 12 UI acceptance after the new interface is complete.

## Non-goals

- no backend rewrite;
- no duplicate annotation, training, review, pose, or workflow engine;
- no change to scientific provenance semantics;
- no silent alteration of model/provider behavior;
- no visual-only state that overrides persisted workflow or review truth.
