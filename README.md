<p align="center">
  <img src="assets/reefvision-banner.svg" alt="ReefVision — computer vision for marine research" width="100%">
</p>

<p align="center">
  Desktop software for marine image and video analysis.<br>
  Annotation, model training, tracking, measurements, and review in one local workspace.
</p>

<p align="center">
  <a href="https://github.com/Rafael-Del-Valle/ReefVision/releases/download/v1.0.1-rc.1/ReefVision_Windows_Downloader.exe"><strong>Download for Windows — 1.0.1 RC (test build)</strong></a>
  · <a href="https://github.com/Rafael-Del-Valle/ReefVision/releases/tag/v1.0.0">Stable v1.0.0</a>
  · <a href="#installation">Installation</a>
  · <a href="#documentation">Documentation</a>
  · <a href="https://github.com/Rafael-Del-Valle/ReefVision/issues">Report an issue</a>
</p>

<p align="center">
  <a href="https://github.com/Rafael-Del-Valle/ReefVision/releases"><img alt="Latest stable release" src="https://img.shields.io/github/v/release/Rafael-Del-Valle/ReefVision?label=stable"></a>
  <img alt="Windows x64" src="https://img.shields.io/badge/platform-Windows%20x64-235b76">
  <a href="https://github.com/Rafael-Del-Valle/ReefVision/commits/main"><img alt="Last commit" src="https://img.shields.io/github/last-commit/Rafael-Del-Valle/ReefVision"></a>
</p>

---

ReefVision is built for researchers who work with large sets of underwater images and video. The idea is simple: keep the images, annotations, model results, and checks together, rather than moving between unrelated tools at every stage of a project.

It began with octocoral imagery, but the annotation and computer-vision workflows can also be used for other marine research datasets. ReefVision runs on your computer, and projects and research records are managed locally.

## What you can do

| Area | Tools |
| --- | --- |
| **Annotate images** | Bounding boxes, rotated boxes, polygons, brush masks, Fill, class management, and editable segmentation results. |
| **Train and run models** | Detection, segmentation, and image classification workflows using supported local models. Review predictions before including them in verified annotations. |
| **Work with video** | Object detection and tracking with ByteTrack or BoT-SORT, plus annotated video exports and tracking summaries. |
| **Measure corals** | Centerlines, scale and calibration tools, and measurements derived from masks or annotated geometry. |
| **Review datasets** | Quality-control checks, ranked review queues, versioned annotation snapshots, dataset exports, and active-learning workflows. |
| **Build repeatable workflows** | Visual workflow graphs with saved revisions, execution history, review steps, and artifact records. |

For a more detailed list, see the [feature reference](docs/FEATURE_REFERENCE.md). Some tools depend on a compatible model, GPU, or separately installed provider.

## A look at ReefVision

The panels below mark where screenshots from the desktop application will go. They are **placeholders, not screenshots**.

| Project workspace | Annotation editor |
| :---: | :---: |
| ![Placeholder for ReefVision project workspace screenshot](assets/screenshots/workspace-placeholder.svg) | ![Placeholder for ReefVision annotation editor screenshot](assets/screenshots/annotation-placeholder.svg) |
| Browse projects and organize imagery. | Draw, edit, and review annotations. |

| Video tracking | Workflow builder |
| :---: | :---: |
| ![Placeholder for ReefVision video tracking screenshot](assets/screenshots/tracking-placeholder.svg) | ![Placeholder for ReefVision workflow builder screenshot](assets/screenshots/workflow-placeholder.svg) |
| Review tracks and export annotated video. | Connect analysis steps and review results. |

## Installation

ReefVision currently has a **1.0.1 release candidate for external-PC testing** and a **1.0.0 stable release**. Both are for Windows x64; the packaged desktop application does not need Python or Node.js.

1. [Download the Windows downloader for ReefVision 1.0.1 RC](https://github.com/Rafael-Del-Valle/ReefVision/releases/download/v1.0.1-rc.1/ReefVision_Windows_Downloader.exe).
2. Open `ReefVision_Windows_Downloader.exe`. It checks GitHub for the newest complete Windows release (including release candidates). It currently selects `v1.0.1-rc.1`, then downloads the MSI and **all five required CAB files** to `Downloads\\ReefVision-1.0.1-rc.1`.
3. The downloader checks each file's SHA-256 against the release provenance. After verification, press Enter to start the Windows installer.

The downloader is unsigned, so Windows may warn about an unknown publisher. Download it only from the [official release](https://github.com/Rafael-Del-Valle/ReefVision/releases/tag/v1.0.1-rc.1). If a download fails, run it again to reuse already verified files.

**Prefer a stable build?** The [v1.0.0 release](https://github.com/Rafael-Del-Valle/ReefVision/releases/tag/v1.0.0) has a separate MSI and six CAB files. Alternatively, run the downloader with `--stable` from a terminal to download only a stable release.

**Working from source?** See the [developer setup guide](docs/DEVELOPMENT.md) instead.

### Models and hardware

The v1.0.0 installer does not include pretrained model checkpoints. Register a compatible local checkpoint for model-based analysis, or use the supported training tools to build your own model. GPU acceleration is useful for training and larger inference jobs; availability depends on the provider and local environment.

## A typical project

1. Create a project and import images or video.
2. Define classes and make a set of reference annotations.
3. Train or register a model, then inspect its predictions.
4. Review and correct results before treating them as verified data.
5. Save a dataset version or export the annotations, tracks, and measurements needed for analysis.

The distinction between model predictions and reviewed annotations is intentional. ReefVision keeps those states separate so that a model suggestion is not automatically treated as a confirmed observation.

## Documentation

- [Desktop installation and packaging](docs/DESKTOP_BUILD_AND_INSTALL.md)
- [Developer setup and validation](docs/DEVELOPMENT.md)
- [Feature reference](docs/FEATURE_REFERENCE.md)
- [Quality-control guide](docs/QUALITY_CONTROL_GUIDE.md)
- [Review queue guide](docs/REVIEW_QUEUE_GUIDE.md)
- [Known issues](docs/KNOWN_ISSUES.md)
- [Changelog](CHANGELOG.md)

## Development

ReefVision uses a React and Tauri desktop interface with a FastAPI backend. The repository contains the application, test suites, database migrations, Windows build scripts, and supporting research documentation.

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidance and the [developer setup guide](docs/DEVELOPMENT.md) for commands. Bug reports and reproducible examples are welcome in [GitHub Issues](https://github.com/Rafael-Del-Valle/ReefVision/issues).

## Research use and licensing

For research using ReefVision, record the application version, model and checkpoint used, dataset version, and how model outputs were reviewed. A formal software citation has not yet been published.

The repository is public, but it does not currently contain a software license. Please do not assume that public access grants permission to redistribute or reuse the code until a license is added.
