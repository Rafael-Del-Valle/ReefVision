import { expect, test } from "@playwright/test";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

const project = {
  id: "project-1",
  name: "Task 21 georeferencing project",
  slug: "task-21-georeferencing-project",
  description: "Task 21 browser acceptance fixture",
  storage_root: "projects/project-1",
  default_annotation_type: "bbox",
  georeference_height_offset_m: 0,
  georeference_height_evidence: null,
  created_at: "2026-09-24T00:00:00Z",
  updated_at: "2026-09-24T00:00:00Z",
  archived_at: null,
  label_classes: [
    {
      id: "class-1",
      project_id: "project-1",
      class_index: 0,
      display_order: 0,
      name: "Animal",
      scientific_name: null,
      state_name: null,
      description: null,
      display_color: "#336699",
      is_active: true,
      archived_at: null,
      created_at: "2026-09-24T00:00:00Z",
      updated_at: "2026-09-24T00:00:00Z",
    },
  ],
};

const alignmentEvidence = "Task 21 known flight-log/video start alignment";

const importedVideo = {
  id: "video-1",
  project_id: project.id,
  original_filename: "task21-flight.mp4",
  managed_path: "projects/project-1/videos/originals/video-1.mp4",
  sha256: "a".repeat(64),
  media_type: "video/mp4",
  width_px: 1920,
  height_px: 1080,
  frame_count: 300,
  fps: 30,
  duration_seconds: 10,
  metadata_json: {
    extraction_every_n_frames: 1,
  },
  frame_directory_path: null,
  extraction_job_id: null,
  status: "imported",
  revision: 1,
  created_at: "2026-09-24T00:00:00Z",
  updated_at: "2026-09-24T00:00:00Z",
  telemetry: {
    available: true,
    source_type: "dji_srt",
    source_path: "projects/project-1/videos/telemetry/video-1.srt",
    sample_count: 3,
  },
  airdata_telemetry: {
    available: true,
    source_type: "airdata",
    source_path: "projects/project-1/videos/telemetry/video-1.airdata.csv",
    sample_count: 3,
  },
  airdata_alignment: {
    time_offset_s: 10,
    evidence: alignmentEvidence,
  },
};

async function mountBuiltApp(page: Parameters<typeof test>[0]["page"]) {
  const assetDirectory = path.resolve("dist/assets");
  const assets = await readdir(assetDirectory);

  const scriptName = assets.find((name) => name.endsWith(".js"));
  const styleName = assets.find((name) => name.endsWith(".css"));

  if (!scriptName || !styleName) {
    throw new Error("Vite build assets are missing");
  }

  const [script, style] = await Promise.all([
    readFile(path.join(assetDirectory, scriptName), "utf8"),
    readFile(path.join(assetDirectory, styleName), "utf8"),
  ]);

  await page.route("http://127.0.0.1:8000/", async (route) => {
    await route.fulfill({
      contentType: "text/html",
      body: '<main id="root"></main>',
    });
  });

  await page.goto("http://127.0.0.1:8000/");

  const packageMetadata = JSON.parse(
    await readFile(path.resolve("package.json"), "utf8"),
  ) as { version: string };

  await page.evaluate((version) => {
    window.localStorage.setItem(
      `reefvision.onboarding.dismissed.${version}`,
      "true",
    );
  }, packageMetadata.version);

  await page.addStyleTag({
    content: style,
  });

  await page.addScriptTag({
    content: script,
    type: "module",
  });
}

test("imports SRT and AirData and renders georeferencing readiness warnings", async ({
  page,
}) => {
  let imported = false;
  let importBody = "";

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const pathname = url.pathname;
    const method = request.method();

    if (pathname.endsWith("/health") && method === "GET") {
      await route.fulfill({
        json: {
          status: "ok",
          version: "1.0.3",
        },
      });
      return;
    }

    if (pathname.endsWith("/project-summaries") && method === "GET") {
      await route.fulfill({
        json: [
          {
            id: project.id,
            name: project.name,
            slug: project.slug,
            description: project.description,
            storage_root: project.storage_root,
            default_annotation_type: project.default_annotation_type,
            georeference_height_offset_m: project.georeference_height_offset_m,
            georeference_height_evidence: project.georeference_height_evidence,
            created_at: project.created_at,
            updated_at: project.updated_at,
            archived_at: project.archived_at,
            label_class_count: project.label_classes.length,
            active_label_class_count: project.label_classes.length,
          },
        ],
      });
      return;
    }

    if (pathname.endsWith(`/projects/${project.id}`) && method === "GET") {
      await route.fulfill({
        json: project,
      });
      return;
    }

    if (
      pathname.endsWith(`/projects/${project.id}/images`) &&
      method === "GET"
    ) {
      await route.fulfill({
        json: {
          items: [],
          total: 0,
          page: 1,
          page_size: 50,
        },
      });
      return;
    }

    if (
      pathname.endsWith(`/projects/${project.id}/videos`) &&
      method === "GET"
    ) {
      await route.fulfill({
        json: imported ? [importedVideo] : [],
      });
      return;
    }

    if (
      pathname.endsWith(`/projects/${project.id}/imports/videos`) &&
      method === "POST"
    ) {
      const body = request.postDataBuffer();

      importBody = body?.toString("utf8") ?? "";

      imported = true;

      await route.fulfill({
        json: importedVideo,
      });
      return;
    }

    if (
      pathname.endsWith("/videos/video-1/georeferencing-readiness") &&
      method === "GET"
    ) {
      await route.fulfill({
        json: {
          state: "alignment_problem",
          sampled_frame_count: 3,
          synchronized_frame_count: 1,
          maximum_sync_error_s: 0.125,
          issues: [
            {
              code: "task21_alignment_review",
              message: "AirData/video alignment requires researcher review.",
            },
          ],
        },
      });
      return;
    }

    if (pathname.endsWith("/videos/video-1/tracks") && method === "GET") {
      await route.fulfill({
        json: [],
      });
      return;
    }

    if (
      pathname.endsWith("/videos/video-1/tracking-runs") &&
      method === "GET"
    ) {
      await route.fulfill({
        json: [],
      });
      return;
    }

    if (
      pathname.endsWith("/videos/video-1/georeferenced-observations") &&
      method === "GET"
    ) {
      await route.fulfill({
        json: {
          items: [],
          count: 0,
        },
      });
      return;
    }

    if (pathname.includes("/models") && method === "GET") {
      await route.fulfill({
        json: [],
      });
      return;
    }

    if (method === "GET" && pathname.includes("/annotated")) {
      await route.fulfill({
        json: [],
      });
      return;
    }

    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({
        detail: `Unhandled Task 21 fixture route: ${method} ${pathname}`,
      }),
    });
  });

  await mountBuiltApp(page);

  await page
    .getByRole("button", {
      name: /Task 21 georeferencing project/,
    })
    .click();

  await page
    .getByRole("tab", {
      name: "Video",
    })
    .click();

  await expect(
    page.getByRole("heading", {
      name: "Managed videos",
    }),
  ).toBeVisible();

  await page.getByLabel("Video file").setInputFiles({
    name: "task21-flight.mp4",
    mimeType: "video/mp4",
    buffer: Buffer.from("Task 21 video fixture"),
  });

  await page.getByLabel("DJI SRT telemetry (optional)").setInputFiles({
    name: "task21-flight.SRT",
    mimeType: "text/plain",
    buffer: Buffer.from("Task 21 SRT fixture"),
  });

  await page.getByLabel("AirData CSV telemetry (optional)").setInputFiles({
    name: "task21-AirData.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(
      ["time(millisecond),latitude,longitude", "10000,32.0000,-79.0000"].join(
        "\n",
      ),
    ),
  });

  await page.getByLabel("AirData time offset (seconds)").fill("10");

  await page.getByLabel("Alignment evidence").fill(alignmentEvidence);

  await page
    .getByRole("button", {
      name: "Import video",
    })
    .click();

  const managedVideosSection = page
    .getByRole("heading", {
      name: "Managed videos",
    })
    .locator("xpath=ancestor::section[1]");

  await expect(
    managedVideosSection.getByRole("combobox", {
      name: "Video",
    }),
  ).toHaveValue("video-1");

  expect(importBody).toContain("task21-flight.mp4");
  expect(importBody).toContain("task21-flight.SRT");
  expect(importBody).toContain("task21-AirData.csv");
  expect(importBody).toContain(alignmentEvidence);

  const readiness = page.getByLabel("Georeferencing readiness");

  await expect(readiness).toBeVisible();

  await expect(readiness).toContainText("Status: Alignment problem");

  await expect(readiness).toContainText("Sync: 1/3 representative frames");

  await expect(readiness).toContainText("max 125.0 ms");

  await expect(readiness).toContainText(
    "AirData/video alignment requires researcher review.",
  );

  await expect(
    page.getByText(/AirData: 3 samples \| offset 10\.00 s/),
  ).toBeVisible();
});

test("renders geographic path, synchronizes frames, selects a track, and exposes GIS exports", async ({
  page,
}) => {
  const mapVideo = {
    ...importedVideo,
    frame_directory_path: "projects/project-1/videos/frames/video-1",
    status: "frames_ready",
  };

  const track = {
    id: "track-1",
    video_id: "video-1",
    label_class_id: "class-1",
    track_number: 1,
    geometry_kind: "bbox",
    keyframes_json: [
      {
        frame: 10,
        bbox: [100, 100, 40, 20],
        confidence: 0.9,
      },
      {
        frame: 20,
        bbox: [140, 100, 40, 20],
        confidence: 0.8,
      },
    ],
    interpolation: "linear",
    status: "verified",
    source_model_id: null,
    source_job_id: null,
    metadata_json: null,
    revision: 1,
  };

  const observation = (
    id: string,
    frameIndex: number,
    latitude: number,
    longitude: number,
  ) => ({
    id,
    project_id: project.id,
    video_asset_id: "video-1",
    track_id: "track-1",
    detection_id: null,
    frame_index: frameIndex,
    frame_width_px: 1920,
    frame_height_px: 1080,
    frame_time_s: frameIndex / 30,
    bbox: {
      x_min: 100,
      y_min: 100,
      x_max: 140,
      y_max: 120,
    },
    representative_pixel: {
      x: 120,
      y: 110,
      method: "bbox_center",
    },
    location: {
      latitude_deg: latitude,
      longitude_deg: longitude,
      crs: "EPSG:4326",
    },
    uncertainty_available: false,
    method_version: "opencv-dji-enu-flat-wgs84-v1",
    configuration_hash: "c".repeat(64),
    is_stale: false,
    stale_reason: null,
    stale_at: null,
    created_at: "2026-09-24T00:00:00Z",
  });

  const first = observation("observation-10", 10, 32.75001, -79.93001);

  const second = observation("observation-20", 20, 32.75002, -79.93002);

  const detailFor = (item: ReturnType<typeof observation>) => ({
    schema_version: "geo-referenced-observation-0001",
    id: item.id,
    project_id: project.id,
    video_asset_id: "video-1",
    detection_id: null,
    track_id: "track-1",
    frame_index: item.frame_index,
    frame_width_px: 1920,
    frame_height_px: 1080,
    bbox: item.bbox,
    representative_pixel: item.representative_pixel,
    timestamp: {
      frame_time_s: item.frame_time_s,
      utc: null,
      source: "frame_index_fps",
      fps: 30,
    },
    pose: {
      platform: {
        latitude_deg: 32.75,
        longitude_deg: -79.93,
        altitude_m: 100,
        altitude_datum: "relative_takeoff",
        height_above_surface_m: 100,
        yaw_deg: null,
        pitch_deg: null,
        roll_deg: null,
        heading_reference: "unknown",
      },
      camera: {
        yaw_deg: 0,
        pitch_deg: -90,
        roll_deg: 0,
        orientation_source: "gimbal_telemetry",
      },
    },
    calibration: {
      calibration_id: "sha256:task21-calibration",
      calibration_version: "1",
      checksum_sha256: null,
      camera_model: "task21-camera",
      image_width_px: 1920,
      image_height_px: 1080,
      focal_length_x_px: 1000,
      focal_length_y_px: 1000,
      principal_point_x_px: 960,
      principal_point_y_px: 540,
      distortion_model: "none",
      zoom_state: 1,
    },
    telemetry: {
      source_id: "task21.srt",
      source_type: "dji_srt",
      sample_index: item.frame_index,
      synchronization_method: "nearest",
      telemetry_time_s: item.frame_time_s,
      telemetry_utc: null,
      signed_time_delta_ms: 0,
      absolute_time_error_ms: 0,
      within_sync_tolerance: true,
      sync_tolerance_ms: 100,
      field_provenance: {},
    },
    location: item.location,
    uncertainty: {
      available: false,
      method: "not_estimated",
      reason_unavailable:
        "Task 21 fixture does not estimate positional uncertainty.",
    },
    method: {
      name: "camera_ray_surface_intersection",
      version: "opencv-dji-enu-flat-wgs84-v1",
      surface_model: "local_horizontal_plane",
      representative_pixel_policy_version: "1.0.0",
      synchronization_version: "nearest-frame-time-v1",
      pose_convention_version: "absolute-gimbal-ned-to-enu-v1",
    },
    created_at: item.created_at,
  });

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const pathname = url.pathname;
    const method = request.method();

    if (pathname.endsWith("/health") && method === "GET") {
      await route.fulfill({
        json: {
          status: "ok",
          version: "1.0.3",
        },
      });
      return;
    }

    if (pathname.endsWith("/project-summaries") && method === "GET") {
      await route.fulfill({
        json: [
          {
            id: project.id,
            name: project.name,
            slug: project.slug,
            description: project.description,
            storage_root: project.storage_root,
            default_annotation_type: project.default_annotation_type,
            georeference_height_offset_m: project.georeference_height_offset_m,
            georeference_height_evidence: project.georeference_height_evidence,
            created_at: project.created_at,
            updated_at: project.updated_at,
            archived_at: project.archived_at,
            label_class_count: project.label_classes.length,
            active_label_class_count: project.label_classes.length,
          },
        ],
      });
      return;
    }

    if (pathname.endsWith(`/projects/${project.id}`) && method === "GET") {
      await route.fulfill({
        json: project,
      });
      return;
    }

    if (
      pathname.endsWith(`/projects/${project.id}/images`) &&
      method === "GET"
    ) {
      await route.fulfill({
        json: {
          items: [],
          total: 0,
          page: 1,
          page_size: 50,
        },
      });
      return;
    }

    if (
      pathname.endsWith(`/projects/${project.id}/videos`) &&
      method === "GET"
    ) {
      await route.fulfill({
        json: [mapVideo],
      });
      return;
    }

    if (
      pathname.endsWith("/videos/video-1/georeferencing-readiness") &&
      method === "GET"
    ) {
      await route.fulfill({
        json: {
          state: "ready",
          sampled_frame_count: 3,
          synchronized_frame_count: 3,
          maximum_sync_error_s: 0.02,
          issues: [],
        },
      });
      return;
    }

    if (pathname.endsWith("/videos/video-1/tracks") && method === "GET") {
      await route.fulfill({
        json: [track],
      });
      return;
    }

    if (
      pathname.endsWith("/videos/video-1/tracking-runs") &&
      method === "GET"
    ) {
      await route.fulfill({
        json: [],
      });
      return;
    }

    if (
      pathname.endsWith("/videos/video-1/georeferenced-observations") &&
      method === "GET"
    ) {
      await route.fulfill({
        json: {
          items: [first, second],
          count: 2,
        },
      });
      return;
    }

    if (
      pathname.endsWith("/georeferenced-observations/observation-10") &&
      method === "GET"
    ) {
      await route.fulfill({
        json: detailFor(first),
      });
      return;
    }

    if (
      pathname.endsWith("/georeferenced-observations/observation-20") &&
      method === "GET"
    ) {
      await route.fulfill({
        json: detailFor(second),
      });
      return;
    }

    if (
      pathname.endsWith("/video-tracks/track-1/interpolation") &&
      method === "GET"
    ) {
      await route.fulfill({
        json: {
          track_id: "track-1",
          video_id: "video-1",
          interpolation: "linear",
          frames: [
            {
              frame: 10,
              timestamp_seconds: 10 / 30,
              bbox: [100, 100, 40, 20],
              center_x: 120,
              center_y: 110,
              source: "keyframe",
            },
            {
              frame: 20,
              timestamp_seconds: 20 / 30,
              bbox: [140, 100, 40, 20],
              center_x: 160,
              center_y: 110,
              source: "keyframe",
            },
          ],
        },
      });
      return;
    }

    if (
      pathname.endsWith("/video-tracks/track-1/analytics") &&
      method === "GET"
    ) {
      await route.fulfill({
        json: {
          track_id: "track-1",
          video_id: "video-1",
          track_number: 1,
          label_class_id: "class-1",
          first_frame: 10,
          last_frame: 20,
          observed_frame_count: 2,
          duration_seconds: 10 / 30,
          path_length_pixels: 40,
          mean_speed_pixels_per_second: 120,
          maximum_speed_pixels_per_second: 120,
          displacement_pixels: 40,
          mean_bbox_area_pixels: 800,
          occupancy_grid: {},
        },
      });
      return;
    }

    if (
      pathname.endsWith("/video-tracks/track-1/geographic-analytics") &&
      method === "GET"
    ) {
      await route.fulfill({
        json: {
          track_id: "track-1",
          video_asset_id: "video-1",
          observation_count: 2,
          segment_count: 1,
          first_frame_index: 10,
          last_frame_index: 20,
          first_frame_time_s: 10 / 30,
          last_frame_time_s: 20 / 30,
          elapsed_time_s: 10 / 30,
          total_distance_m: 1.5,
          net_displacement_m: 1.5,
          mean_speed_m_s: 4.5,
          max_segment_speed_m_s: 4.5,
          start_location: first.location,
          end_location: second.location,
          segments: [
            {
              track_id: "track-1",
              video_asset_id: "video-1",
              start_observation_id: first.id,
              end_observation_id: second.id,
              start_frame_index: 10,
              end_frame_index: 20,
              start_frame_time_s: 10 / 30,
              end_frame_time_s: 20 / 30,
              elapsed_time_s: 10 / 30,
              start_location: first.location,
              end_location: second.location,
              distance_m: 1.5,
              speed_m_s: 4.5,
              cumulative_distance_m: 1.5,
              speed_valid: true,
              invalid_reason: null,
            },
          ],
        },
      });
      return;
    }

    if (pathname.includes("/models") && method === "GET") {
      await route.fulfill({
        json: [],
      });
      return;
    }

    if (pathname.includes("annotated") && method === "GET") {
      await route.fulfill({
        json: [],
      });
      return;
    }

    if (pathname.includes("/videos/video-1/frames/") && method === "GET") {
      await route.fulfill({
        status: 204,
      });
      return;
    }

    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({
        detail: `Unhandled Task 21B fixture route: ${method} ${pathname}`,
      }),
    });
  });

  await mountBuiltApp(page);

  await page
    .getByRole("button", {
      name: /Task 21 georeferencing project/,
    })
    .click();

  await page
    .getByRole("tab", {
      name: "Video",
    })
    .click();

  const managedVideosSection = page
    .getByRole("heading", {
      name: "Managed videos",
    })
    .locator("xpath=ancestor::section[1]");

  await expect(
    managedVideosSection.getByRole("combobox", {
      name: "Video",
    }),
  ).toHaveValue("video-1");

  const map = page.getByTestId("georeferenced-map-panel");

  // OpenStreetMap is now ReefVision's default online map.
  // This legacy synchronization/path test exercises the
  // built-in scientific SVG explicitly so its existing
  // observation-button assertions remain deterministic and
  // independent of network availability.
  const scientificPlotButton = map.getByRole("button", {
    name: "Scientific plot",
  });

  await expect(scientificPlotButton).toBeVisible();

  await scientificPlotButton.click();

  await expect(map.getByTestId("georeferenced-scientific-plot")).toBeVisible();

  await expect(map).toBeVisible();

  await expect(
    map.getByRole("button", {
      name: "Observation at frame 10",
    }),
  ).toBeVisible();

  const frame20 = map.getByRole("button", {
    name: "Observation at frame 20",
  });

  await expect(frame20).toBeVisible();

  const trackPath = map.locator('polyline[data-track-id="track-1"]');

  await expect(trackPath).toHaveCount(1);

  await expect(
    map.getByTestId("georeferenced-uncertainty-legend"),
  ).toContainText("temporal synchronization is not geographic accuracy");

  await frame20.click();

  await expect(frame20).toHaveAttribute("aria-pressed", "true");

  const frameSection = page
    .getByRole("heading", {
      name: "Source-coordinate overlay",
    })
    .locator("xpath=ancestor::section[1]");

  const sourceOverlayToggle = frameSection.getByRole("checkbox", {
    name: "Enable source-coordinate overlay",
  });

  await expect(sourceOverlayToggle).not.toBeChecked();

  await sourceOverlayToggle.check();

  await expect(sourceOverlayToggle).toBeChecked();

  await expect(frameSection.locator('input[type="range"]')).toHaveValue("20");

  await expect(trackPath).toHaveAttribute("data-active-track", "true");

  await expect(
    map.getByText("Frame 20", {
      exact: true,
    }),
  ).toBeVisible();

  await page
    .getByRole("combobox", {
      name: "Existing track",
    })
    .selectOption("track-1");

  const geographicAnalytics = page.getByTestId(
    "geographic-movement-analytics-panel",
  );

  await expect(geographicAnalytics).toHaveAttribute("data-track-id", "track-1");

  await expect(geographicAnalytics).toHaveAttribute("data-status", "success");

  await expect(
    geographicAnalytics.getByRole("table", {
      name: "Geographic trajectory segments",
    }),
  ).toBeVisible();

  const wholeVideoGeoJSON = page.getByRole("link", {
    name: "Download whole-video GeoJSON",
  });

  await expect(wholeVideoGeoJSON).toHaveAttribute(
    "href",
    /\/videos\/video-1\/geographic-export\?format=geojson/,
  );

  const selectedTrackGeoJSON = page.getByRole("link", {
    name: "Download selected-track GeoJSON",
  });

  await expect(selectedTrackGeoJSON).toHaveAttribute(
    "href",
    /\/videos\/video-1\/geographic-export\?format=geojson&track_id=track-1/,
  );

  await expect(selectedTrackGeoJSON).toHaveAttribute(
    "download",
    "reefvision-selected-track.geojson",
  );
});
