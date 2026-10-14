import { describe, expect, it } from "vitest";

import {
  readGalleryPreference,
  resolveGalleryNavigation,
  writeGalleryPreference,
} from "./galleryNavigation";

function memoryStorage(initial: Record<string, string> = {}): Storage {
  const values = new Map(Object.entries(initial));
  return {
    get length() {
      return values.size;
    },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => values.delete(key),
    setItem: (key, value) => values.set(key, value),
  };
}

describe("gallery preferences", () => {
  it("persists the recent image and page per project", () => {
    const storage = memoryStorage();

    writeGalleryPreference(storage, "project-a", {
      imageId: "image-49",
      page: 3,
      wrap: true,
    });

    expect(readGalleryPreference(storage, "project-a")).toEqual({
      imageId: "image-49",
      page: 3,
      wrap: true,
    });
    expect(readGalleryPreference(storage, "project-b")).toEqual({
      imageId: null,
      page: 1,
      wrap: false,
    });
  });

  it("falls back safely when stored data is corrupt", () => {
    const storage = memoryStorage({
      "reefvision.gallery.project-a.v1": '{"imageId":7,"page":-3}',
    });

    expect(readGalleryPreference(storage, "project-a")).toEqual({
      imageId: null,
      page: 1,
      wrap: false,
    });
  });
});

describe("resolveGalleryNavigation", () => {
  it("moves within a page without requesting another page", () => {
    expect(
      resolveGalleryNavigation({
        action: "next",
        index: 3,
        itemCount: 24,
        page: 9,
        pages: 100_000,
        wrap: false,
      }),
    ).toEqual({ page: 9, edge: "index", index: 4 });
  });

  it("crosses page boundaries without loading the full collection", () => {
    expect(
      resolveGalleryNavigation({
        action: "next",
        index: 23,
        itemCount: 24,
        page: 9,
        pages: 100_000,
        wrap: false,
      }),
    ).toEqual({ page: 10, edge: "first" });
    expect(
      resolveGalleryNavigation({
        action: "previous",
        index: 0,
        itemCount: 24,
        page: 9,
        pages: 100_000,
        wrap: false,
      }),
    ).toEqual({ page: 8, edge: "last" });
  });

  it("supports first, last, optional wrapping, and single-image no-ops", () => {
    expect(
      resolveGalleryNavigation({
        action: "first",
        index: 4,
        itemCount: 24,
        page: 9,
        pages: 10,
        wrap: false,
      }),
    ).toEqual({ page: 1, edge: "first" });
    expect(
      resolveGalleryNavigation({
        action: "last",
        index: 4,
        itemCount: 24,
        page: 9,
        pages: 10,
        wrap: false,
      }),
    ).toEqual({ page: 10, edge: "last" });
    expect(
      resolveGalleryNavigation({
        action: "previous",
        index: 0,
        itemCount: 24,
        page: 1,
        pages: 10,
        wrap: true,
      }),
    ).toEqual({ page: 10, edge: "last" });
    expect(
      resolveGalleryNavigation({
        action: "next",
        index: 0,
        itemCount: 1,
        page: 1,
        pages: 1,
        wrap: true,
      }),
    ).toBeNull();
  });
});
